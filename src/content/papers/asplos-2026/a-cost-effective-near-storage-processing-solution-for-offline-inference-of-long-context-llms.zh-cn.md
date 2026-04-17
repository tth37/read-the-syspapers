---
title: "A Cost-Effective Near-Storage Processing Solution for Offline Inference of Long-Context LLMs"
oneline: "HILOS 把 attention 下放到 SmartSSD，在主机侧复用 X-cache 并延迟 KV 回写，让单张 GPU 也能承载 175B、128K 上下文的离线推理。"
authors:
  - "Hongsun Jang"
  - "Jaeyong Song"
  - "Changmin Shin"
  - "Si Ung Noh"
  - "Jaewon Jung"
  - "Jisung Park"
  - "Jinho Lee"
affiliations:
  - "Seoul National University, Seoul, South Korea"
  - "POSTECH, Pohang, South Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790119"
code_url: "https://github.com/hongsunjang/HILOS/tree/asplos26"
tags:
  - llm-inference
  - storage
  - hardware
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

HILOS 面向的是这样一种离线 LLM 推理场景：上下文很长、batch 很大，于是系统的真正瓶颈不再是算力，而是 KV cache 在 PCIe 上来回搬运。它把精确 attention 下放到 SmartSSD，在主机侧保留一部分 pre-projection activation 以便按需重算 KV，再把新生成的 KV 延迟回写到 SSD，从而把关键路径上的大规模 KV 传输改写成设备内部流量。基于真实的 16 块 SmartSSD 原型，作者证明单 GPU 主机也能支撑 `175B` 模型、`128K` 上下文，并取得最高 `7.86x` 吞吐提升与最高 `85%` 能耗下降。

## 问题背景

这篇论文关注的不是在线聊天那种强交互推理，而是离线推理。对这类工作负载来说，更长的 prompt、更大的 batch 都是可以接受的，因为目标是把吞吐做高，用于 benchmark、信息抽取之类任务。但离线推理会把内存问题放大：模型参数本来就大，KV cache 还会随着上下文长度和 batch 大小一起增长。对大模型和长上下文而言，单是 KV cache 就可能达到 TB 级，GPU 显存和主机 DRAM 都很难装下。

FlexGen、DeepSpeed-Inference 这类现有 offloading 系统的思路，是把 GPU 内存扩展到 CPU DRAM 和 SSD。这样确实能让权重“放得下”，而且 batch 化还能摊薄权重传输成本，但新的瓶颈随之出现：在 decode 阶段，每一层都要反复把巨大的历史 KV cache 取回来。论文在 OPT-175B 上的动机实验显示，长上下文离线推理中，KV cache 传输占总推理时间超过 `60%`。换句话说，系统已经不是 compute-bound，而是彻底变成了一台围绕 PCIe 搬运数据的机器。

继续堆 GPU 也不是令人满意的答案。作者指出，decode 本质上是 memory-bound 的，因此昂贵 GPU 的算力会大量闲置，多 GPU 服务器还会把部署成本迅速抬高。更重要的是，哪怕把 near-storage processing 引进来，朴素版本也未必有效，因为 attention 下放以后，瓶颈会转移到设备内部：存储侧读取、细粒度 KV 写入，以及受限 FPGA 资源，都可能把理论收益重新吃掉。

## 核心洞察

论文的核心判断是：长上下文离线 decode 真正昂贵的，并不是抽象意义上的“attention 计算”，而是每一步都把整段历史 KV cache 拉回主机。只要 attention 能在存储旁边完成，主机其实不需要看到整个 KV cache，只需要拿到最终 attention 输出即可。这样一来，主导流量的项就不再随上下文长度线性膨胀，而是回到和 hidden size 相关的规模。

第二个洞察是，一旦 attention 离开 GPU，主机侧就出现了可利用的空闲。HILOS 用两种方式消费这部分空闲。第一，它不为所有历史 token 都保存 K 和 V，而是对一部分工作负载保存 pre-projection activation `X`，再让 GPU 在需要时把 K、V 重算出来。第二，它不再要求每个新生成的 KV 向量立刻同步落盘，而是先在主机内存中缓冲，并只把继续执行精确 attention 所需的部分信息暴露给加速器。论文真正想表达的是：NSP 只有在“主机和存储协作”时才有价值，而不是让存储单独包办一切。

## 设计

HILOS 的核心机制是 attention near storage（ANS）。在 decode 路径中，GPU 仍然负责加载权重并执行 QKV projection，但生成的 query、key、value 会被送到 SmartSSD。近存储加速器从本地 flash 读入历史 KV cache 到设备 DRAM，在设备内完成 attention，再只把最终 attention output 返回给主机，之后 GPU 继续执行 MLP 部分。论文用一个简单模型说明流量变化：在半精度下，基线每步 decode 的互连读流量约为 `4sh + 4h` 字节，而 HILOS 变成 `2h + 6h`，因此上下文越长，收益越明显。

但只有 ANS 还不够，因为新的瓶颈会落到存储内部 I/O 上。为此 HILOS 又加入 cooperative X-cache。对 batch-head 空间中的 `alpha` 部分，系统不存 K/V，而是存 pre-projection activation `X`。由于 `X` 的大小只有 KV 的一半，这会同时降低该部分的 flash 读流量和存储占用。decode 时，GPU 通过 GPUDirect Storage 取回 X-cache，再本地重算 K 和 V；SmartSSD 加速器则处理剩下的 `1 - alpha` 部分。两边并行进行，因此作者希望把这部分重算延迟隐藏掉。论文还给出一个一阶模型，用 PCIe 带宽和 SSD 带宽平衡来选 `alpha`，并把结果近似到 2 的幂；在他们的平台上，profiling 得到的较优值大约是 `50%`。

接下来要解决的是写回问题。新生成的 KV 很小，但 SSD 喜欢页粒度写入。若采用朴素方案，每轮 decode 都要做细粒度 direct write，再把更新后的 cache 读回来，这会让写延迟直接进入关键路径。HILOS 使用 delayed KV cache writeback：新的 K/V 先留在主机内存缓冲区里，CPU 预先算出这些 buffered key 对当前 query 的部分 `QK^T` 结果，加速器收到这些标量以及 buffered V 后，就能继续完成精确 attention。真正写回 SSD 则推迟到后面，用更大的块完成。默认 spill interval 设为 `16`，正好与典型每 head `256 B` KV 项和 `4 KiB` 页粒度对齐。

加速器本身是一个定制的 SmartSSD FPGA 设计。它采用 temporal、block-based 的 attention 架构，而不是全空间展开的设计，因为长上下文 attention 否则会吃掉过多片上存储。这里有三个关键硬件点。第一，HILOS 使用 two-pass softmax，而不是常见的 three-pass 版本，以降低 off-chip memory traffic。第二，它通过块内原地转置来解决“KV 按行写入、key 却要按列读取”的布局冲突。第三，它原生支持 grouped-query attention，可把共享的 KV 数据广播给多个 query group，避免重复读取。实现上，存储仍是 FP16，但中间累加和指数运算使用 FP32 来保证数值稳定性。

## 实验评估

这套原型是真实硬件，而不是纯模拟：最多 `16` 块 Samsung SmartSSD，每块都带 `3.84 TB` SSD、Kintex UltraScale+ KU15P FPGA 和 `4 GB` DDR4，通过 PCIe 扩展箱接到 `A100-40GB` 或 `H100-80GB` 主机上。对比基线包括：KV 放在 DRAM 的 FlexGen、KV 放在 SSD 的 FlexGen、在同一批 16 块 SSD 上但关闭 FPGA 的 FlexGen，以及扩展了 UVM 的 DeepSpeed-Inference。工作负载覆盖 OPT-30B、OPT-66B、OPT-175B、Qwen2.5-32B、Mixtral-8x7B 和 GLaM-143B，上下文最长到 `128K`，默认 batch size 为 `16`，输出长度为 `64`。

主结果相当扎实。只用四块 SmartSSD 时，HILOS 相比 DRAM-offloading 基线就已经快 `1.10x-1.36x`，原因是它既减少了 PCIe 流量，又能维持更大的有效 batch。扩展到十六块 SmartSSD 后，优势提升到 `1.88x-2.49x`。在那些 FlexGen(DRAM) 即使 batch size 为 `1` 也会 host-memory OOM 的长上下文场景里，HILOS 相比 FlexGen(SSD) 的 decode 吞吐提升达到 `5.3x-7.8x`。论文的总体最佳数字就是 `7.86x`。

敏感性实验也把收益来源讲清楚了。在 66B 模型上，DRAM-offloading 方案因为主机内存限制，batch size 最多只能到 `2`；HILOS 则能继续扩展到 `16`。对于 GQA 和 MoE 模型，HILOS 依然能带来 `1.16x-3.36x` 的端到端加速，说明它并不只对普通 MHA 模型有效。系统参数扫描也和分析模型对上了：`alpha = 50%` 一直是最优的 X-cache 比例，spill interval `c = 16` 是最好的写回设置。ablation 结果也很干净：只有 ANS 时最高可得 `3.39x`，加入 delayed writeback 还能在 ANS 基础上再拿到最高 `1.32x`，再加入 X-cache 则还能比 ANS 高最高 `1.64x`。

这篇论文还做了吞吐之外的评估。对 66B 模型，HILOS 的 cost-efficiency 最多比 FlexGen(SSD) 高 `2.02x`；对 175B 模型，最多高 `1.68x`。如果把基线从 A100 升级到昂贵得多的 H100，速度虽然也能提升，但 HILOS 仍能以相近的 `1.29x` 加速拿到 `2.91x` 更高的 cost-efficiency。耐久度方面，论文估计 HILOS 比基线高 `1.34x-1.47x`，并且在他们的假设下，面对 175B 长请求仍能支撑超过 `4.08 million` 次请求后才触及 SSD 写入寿命。能耗分析则给出最高 `85%` 的下降；作者还拿两节点、八张 RTX A6000 的 vLLM 配置做比较，HILOS 依然快 `1.64x-1.81x`。整体来看，实验确实支撑了论文的核心主张：HILOS 不只是更快，而是把单 GPU 长上下文离线推理推到了一个新的成本/性能点上。

## 创新性与影响

相对 _Sheng et al. (ICML '23)_，HILOS 最关键的一步是停止把存储当成被动溢出层，而是直接在 KV cache 旁边执行精确 attention。相对 _Pan et al. (HPCA '25)_，这篇论文的区别在于它追求 lossless 的长上下文推理，并且是在现代真实 SmartSSD 平台上完成，而不是依赖有损稀疏检索与偏旧、偏仿真的基础设施。相对 _Heo et al. (ASPLOS '24)_ 这类 PIM 方案，HILOS 则在主张：对极长上下文和超大模型，基于 flash 的 near-storage processing 可能落在另一个更便宜的成本点上。

因此，这篇论文对两类人都很重要。对系统工程团队来说，它提供了一套相当完整的方案，把“单张 GPU + 大量闪存”真正变成可用的离线推理服务器。对体系结构研究者来说，它说明未来的 CSD/ISP 设计不该只围绕泛化存储卸载，而应围绕精确 attention、页粒度写回以及主机/设备协作式执行来共同设计。

## 局限性

这个设计明显是为离线推理定制的，强调的是吞吐而不是单请求延迟。它并不声称能解决在线 serving 中严格的 TTFT/TPOT 目标，尤其 delayed writeback 这类机制放到强交互场景里就没有这么自然。HILOS 还依赖 SmartSSD 级硬件、定制 FPGA bitstream、GPUDirect Storage，以及能同时编排 GPU、CPU、SSD controller 和 FPGA 的 middleware，这离“开箱即用部署”还有相当距离。

此外，论文消除的是 KV-cache 瓶颈，而不是所有瓶颈。模型权重仍要从主机内存或存储中读取，超过 `100B` 参数的模型仍然要把权重 spill 到存储。作者也在 discussion 中明确指出，当前加速器主要是把 PCIe 3.0 时代的 SmartSSD 带宽吃满；如果未来换成 PCIe 5.0 设备，所需吞吐大约要再提高 `4x`，而现有 SmartSSD 的 DSP 预算未必扛得住。论文还提到一个现实的不匹配：为了拿到总带宽，HILOS 必须把 KV 数据分散到很多 SSD 上，这会让每块 `3.84 TB` 设备的大量容量其实用不上。最后，关于 ISP 和 CXL 可迁移性的讨论更多是基于分析的推演，而不是已经做完的端到端实现。

## 相关工作

- _Sheng et al. (ICML '23)_ — FlexGen 是最直接的软件基线：它把权重和 KV 在 GPU、DRAM、SSD 间分层放置，但仍要把 KV 数据拉回主机，而不是在存储侧完成 attention。
- _Aminabadi et al. (SC '22)_ — DeepSpeed-Inference 同样处理受内存约束的 Transformer 推理，但 HILOS 瞄准的是离线长上下文场景，此时真正主导开销的是 KV 流量而不只是权重摆放。
- _Pan et al. (HPCA '25)_ — InstAttention 也探索了 storage-side attention offload，而 HILOS 更强调精确计算、现代 SmartSSD 实机部署，以及让这件事真正可用所需的额外系统机制。
- _Heo et al. (ASPLOS '24)_ — NeuPIMs 用 PIM 加速 batched LLM inference；HILOS 则选择 flash-backed near-storage 设计，用更复杂的存储协同换取更低介质成本。

## 我的笔记

<!-- 留空；由人工补充 -->
