---
title: "REPA: Reconfigurable PIM for the Joint Acceleration of KV Cache Offloading and Processing"
oneline: "用可重构 ReRAM PIM 同时承接 KV cache 持久化与 scoring/context 计算，再用 GPU-PIM 流水和局部性感知映射把解码加速起来。"
authors:
  - "Yang Hong"
  - "Junlong Yang"
  - "Bo Peng"
  - "Jianguo Yao"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790212"
tags:
  - llm-inference
  - caching
  - memory
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

REPA 认为，KV cache offloading 和 decode 阶段的 KV 处理本来就是同一个问题，不该拆成两套优化。它把 KV 数据放进既能非易失保存缓存、又能执行 `q x K^T` 与 `S x V` 的可重构 ReRAM PIM 里，再配合批量内存指令、局部性感知数据放置和 GPU-PIM 流水，从而在长上下文场景下把性能推到超过纯 GPU 方案。

## 问题背景

论文从两个通常被拆开优化的痛点出发。第一是 KV cache 太大。作者引用先行工作指出，KV cache 可占 GPU 内存的 `30%-80%`；他们在 Azure23 上还测得，Llama2-7B 的单请求平均 KV 占用达到 `670 MiB`。因此系统不得不频繁 offload，但基于 SSD 的逐出代价很高：当发生 `1-4` 次 eviction 时，中位长度请求会慢 `0.3-0.8x`，P99 长请求会慢 `0.5-2.0x`。

第二个问题是 decoding 和 GPU 并不天然契合。scoring 与 context 算术强度低，需要频繁搬运 KV 切片，也不像 prefill 那样能明显吃到跨请求 batching 的好处。现有系统往往只解其中一半：offloading 系统改进数据移动策略，但不会在被移出的 KV 上继续计算；stage-split 系统把 decode 挪到别处，却没有解决 KV 处理本身的低效。REPA 因而瞄准的是组合问题：在同一底座上同时完成 KV cache 的低成本持久化与 decode 阶段不可 batch 的 KV 计算。

## 核心洞察

论文的核心洞察是：KV cache offloading 和 KV cache processing 实际上需要同一组硬件特性，即大容量、非易失性，以及靠近数据的高带宽计算能力。可重构 ReRAM PIM 同时具备存储与计算属性，因此可以让同一块设备既保存被移出的 KV 状态，又执行 decode 阶段最棘手的 scoring 和 context。

但这个想法要成立，前提是用更高的并行度补偿可重构 PIM 单次操作偏慢的弱点。REPA 的判断是，per-head KV matrix 的结构正好允许这种重塑：批量 memory instruction 暴露多 wordline 并行性，局部性感知放置把中间结果留在 tile 内，GPU-PIM 流水则把传输空隙藏掉。真正该记住的命题不是“PIM 能帮 attention”，而是“只要并行度设计对，ReRAM PIM 可以把 KV 的 offload 存储层变成活跃的 decode 加速器”。

## 设计

REPA 是一个混合式分工系统。GPU 负责整个 prefill，以及 decode 中适合 batch 的部分，例如 QKV generation、projection 和 FFN；REPA-PIM 负责 decode 中不易 batch 的部分，也就是 scoring（`q x K^T`）和 context（`S x V`）。PIM 设备本身是 3D-stacked 结构，由一个 buffer die 和八个 PIM die 组成；每个 die 里有 tile，每个 tile 里有 processing unit，每个 PU 再包含由多组控制器管理的 ReRAM array。

第一项关键设计在控制面。可重构 PIM 做算术需要的 memory operation 远多于 DRAM-PIM，所以 REPA 提出 `BLK_SET` 指令，一次把同样的 memory-setting 原语施加到连续 64 条 wordline 上。随后它又在 tile-group、tile 和 PU 三层放置控制器，把这种内部并行性真正调度起来。作者报告说，把每个 PU 的控制器从 1 个增到 4 个，会增加 `5.76 mm^2`/die 的面积，但可换来 `3.91x` 的 `q x K^T` 加速。

第二项关键设计是数据布局。REPA 先按 attention head 划分 KV cache，再把每个 per-head matrix 放到四个彼此邻近、属于不同 array group 的数组里，而不是细粒度打散到遥远的 bank。`K` 按行切片，方便复制 query 后并行做点积；`V^T` 则切成固定宽度的小块，让 score 的切片能在局部复制并归约。同一套映射同时服务于 offload 持久化与 decode 局部性。

第三项关键设计是流水。REPA 把请求拆成 sub-batch，让 GPU 与 PIM 同时忙碌，并在 prefill 与 decode 两个阶段都尽量重叠传输和计算。系统追求的核心不变量很直接：PIM 尽量只处理已经放到附近的数据，而 GPU 持续推进下一批可 batch 的工作。

## 实验评估

宿主机器是真实的 8xA100 服务器，但 REPA-PIM 本身仍是基于 NeuroSim-3D 的自研模拟器，工作频率 `1 GHz`，因此这更像体系结构研究而不是已流片原型。工作负载使用 Llama2 的 `7B`、`13B` 和 `70B` 模型，并与 GPU、AttAcc、PAPI、DRISA、AiF 对比。

主实验里，REPA 在论文预期的区间里赢得最明显：长上下文、大 batch、大模型。相对 NVIDIA A100，当序列长度为 `2048` 时，token generation 提升 `1.8-4.8x`；当序列长度为 `4096` 时，提升扩大到 `2.1-6.5x`；在较短的 `1024` 序列上则缩小到 `1.5-4.7x`。相对 AttAcc，REPA 在 `4096` 上领先 `0.4-1.4x`，但在 `1024` 上只剩 `-0.3-0.8x`，这也正好说明它需要足够多的并行工作去摊平慢原语成本。

集成结果也有说服力。接入 FlexGen 且不改变其 offloading policy 时，REPA 可把 offloading speed 提高 `1.4-2.0x`，摘要将端到端收益概括为约 `1.2-1.4x` 的 speedup。能效方面，REPA 的 tokens-per-joule 相比 GPU 提升 `2.1-4.3x`，scoring/context 的单位能耗优势扩大到 `6.2-6.3x`。此外，消融实验也支撑了设计本身：相对纯 stage-split 变体，REPA 的 end-to-end latency 改善 `1.2-1.6x`，而且其 mapping 让超过 `92%` 的计算停留在单个 tile 内。整体上，这些证据较好支撑了论文在长序列、内存压力大场景下的主张，但对短序列、轻负载推理的支撑明显弱一些。

## 创新性与影响

和 _Park et al. (ASPLOS '24)_ 相比，REPA 不只是又一个 PIM attention accelerator：AttAcc 用 DRAM PIM 加速 batched transformer inference，而 REPA 把 decode 加速与非易失 KV 持久化绑在一起。和 _He et al. (ASPLOS '25)_ 相比，REPA 的重点不是动态分派，而是重做存储/计算底座，让 KV cache 直接驻留在 scoring 与 context 执行的位置。和 _Patel et al. (ISCA '24)_ 相比，它没有把 decode 丢给更弱的 GPU 层，而是把瓶颈送进另一类硬件。

因此，这篇论文最值得做 ReRAM PIM 的体系结构研究者，以及探索专用 memory device 的 LLM serving 系统研究者引用。它的贡献主要是新机制加工作负载导向的 framing，而不是测量论文。

## 局限性

最大的局限是方法论上的：REPA-PIM 仍停留在模拟器层面，没有真实芯片，因此所有性能与能耗结论都依赖模拟器以及 ReRAM 参数假设是否足够准确。第二个局限是胜场区间比较集中。REPA 的优势来自大工作集上的细粒度并行，而论文自己的结果也显示，在短序列设置下，它相对 AttAcc 的收益明显缩小，甚至可能落后。

部署层面也比论文动机看起来更窄。实验围绕 Llama2 单模型展开，而不是多模型服务集群；与现有系统的整合也主要展示在 FlexGen 上，且沿用了原有策略，而不是证明其在生产级 disaggregated scheduler 中的效果。最后，耐久性问题虽然被讨论了，但证据仍是分析式的：作者按 `20 tokens/s` 的连续 decode 假设估算，每个单元每年少于 `2.8 x 10^10` 次 memset，并据此说明高耐久 ReRAM 足够使用；这仍不是实际部署数据。

## 相关工作

- _Park et al. (ASPLOS '24)_ — AttAcc 用 DRAM PIM 加速 batched transformer attention，而 REPA 额外提供非易失 KV 存储，并专门面向 offloaded decode 路径。
- _He et al. (ASPLOS '25)_ — PAPI 研究的是 PIM-enabled decoding 中的动态并行性，而 REPA 更强调可重构 ReRAM、批量指令和局部性感知的 KV 放置。
- _Patel et al. (ISCA '24)_ — Splitwise 将 prefill 与 decode 拆到不同设备；REPA 则保留 GPU 上的 batchable decode 工作，只把不可 batch 的 KV 处理下沉到 PIM。
- _Sheng et al. (ICML '23)_ — FlexGen 通过 offloading 换取 GPU 内存容量，而 REPA 把自己定位成与其正交的加速器，用来加速那条被 offload 的路径。

## 我的笔记

<!-- empty; left for the human reader -->
