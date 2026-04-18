---
title: "Towards High-Goodput LLM Serving with Prefill-decode Multiplexing"
oneline: "MuxWise 在同一组 GPU 内在线重分配 SM 给 prefill 与 decode，并保持统一 KV cache 池，从而提升严格 SLO 下的 LLM goodput。"
authors:
  - "Yukang Chen"
  - "Weihao Cui"
  - "Han Zhao"
  - "Ziyi Xu"
  - "Xiaoze Fan"
  - "Xusheng Chen"
  - "Yangjie Zhou"
  - "Shixuan Sun"
  - "Bingsheng He"
  - "Quan Chen"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "National University of Singapore, Singapore"
  - "Researcher, Shanghai, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790236"
code_url: "https://github.com/ykcombat/sglang/tree/slo_config"
project_url: "https://zenodo.org/records/18062118"
tags:
  - llm-inference
  - scheduling
  - gpu
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

MuxWise 的核心主张是，LLM serving 不该把 GPU 粗暴地切成“prefill 机器”和“decode 机器”，而应该在同一块 GPU 内把一部分 SM 分给 decode，其余 SM 动态借给 prefill。它通过 layer-wise prefill、最坏情况 contention guard 和 SLO-aware dispatcher，在保住 decode 延迟目标的同时回收原本闲置的算力。论文报告其 peak goodput 平均提升 `2.20x`，最高达到 `3.06x`。

## 问题背景

这篇论文抓住的是生产级 LLM 服务里一个非常现实的矛盾。真实负载会同时包含短对话、长上下文分析、推理任务和多轮 agent，请求之间的输入长度、输出长度以及 reused context 长度差异很大；但服务又希望同时满足严格的 `TTFT` 和 `TBT`，尤其是 decode 阶段的 token 级延迟目标。

现有两类主流方案都不理想。像 Splitwise、LoongServe 这样的 disaggregated serving 把 prefill 和 decode 放到不同实例里，确实更容易保护 decode 延迟，但代价是 GPU 会随着负载结构变化而闲置，而且有效 KV-cache 池会缩小。论文给出的动机实验很直观：同样四张 GPU，如果被拆成两个两卡实例，cache hit rate 可能从 `36.6%` 掉到 `4.2%`，原本可复用的 KV 就会变成重新计算。另一条路线是 chunked-prefill，它不做完全拆分，而是把 prefill 切成块并和 decode iteration 融合执行；但这样一来，token budget 同时决定了 decode 能否满足 SLO 以及 GPU 是否能被跑满。作者展示，对于 8 张 A100 上的 Llama-70B，要接近饱和需要大约 `4K` 的 budget，而 `100 ms` `TBT` 目标只能容忍约 `256`；当 budget 到 `4K` 时，`TBT` 会涨到 `505 ms`。

因此，问题不只是“如何给 prefill 和 decode 排队”，而是现有系统把 compute placement 和 memory placement 绑定得太死。只要两阶段不能在共享 KV 状态的同时独立借用算力，系统就会在吞吐和延迟之间反复做坏交易。

## 核心洞察

论文最重要的洞察是：prefill 和 decode 应该在同一块 GPU 内做空间复用，而不是仅仅时间交错，或者干脆拆到不同实例上。decode 真正需要的是“足够满足 SLO 的 SM 数量”，剩余 SM 完全可以动态转交给 prefill；与此同时，两阶段依旧留在同一地址空间里，共享一个 KV-cache 池。这样，动态算力分配和 KV reuse 就不再互相冲突。

但作者也说明，朴素的 intra-GPU multiplexing 仍然不够。prefill launch 更慢、执行时间更不稳定，而且共享内存带宽带来的 contention 很难在线精准预测，所以简单地“先发 decode，再发 prefill”仍会产生 bubbles，甚至继续 miss deadline。MuxWise 真正成立的关键是两点：一是把 prefill 切到 layer granularity，使其可中断、可插空；二是对 contention 不追求精确在线预测，而是使用保守的 worst-case 上界来保护 decode。

## 设计

MuxWise 由三个核心模块组成。第一个是 bubble-less multiplex engine。它基于 NVIDIA GreenContext，把不同 CUDA stream 绑定到不同 SM 子集，同时让 prefill 和 decode 仍处于同一个进程和同一片显存地址空间中。这样系统既能低开销地重分配 SM，又能保留跨阶段、跨请求的 KV reuse。接着，engine 把 prefill 切成以 transformer layer 为粒度的 prefill layer（`PL`）。因为单层的启动和执行都比整个 prefill 短得多，调度器就可以只发够覆盖 decode 时间的若干层，等 decode 结束后立即切换，或者在超长 prefill 运行中途让更短的请求插队。

仅有 layer granularity 还不够，因为 inflight batching 仍要求“prefill 完成后尽快并入 decode batch”。MuxWise 因此加入 query-based synchronization：系统持续异步发射 decode iteration 和 prefill layers，同时轮询 CUDA event；一旦发现某个 prefill 已完成，就立刻把它并入当前 decode batch，而不是在粗粒度 barrier 上等待。论文报告，即便把 prefill 切到最细的 layer-wise launching，额外 runtime overhead 也不超过 `1.5%`。

第二个模块是 contention-tolerant estimator，用来回答“decode 最多能让出多少 SM”。MuxWise 先通过离线 profiling 训练 prefill 和 decode 的 solo-run latency predictor，输入特征包括 reused length、new token length、output length、batch size 和 partition configuration。然后，它再叠加一个 contention guard，为不同 prefill/decode 尺度和 SM 划分组合保存最坏情况下的 decode slowdown 因子。论文强调，保证 SLO 并不需要完美预测，只需要一个足够保守的上界，让 decode 不会超出目标即可。作者观测到，在粗粒度 profiling 下，contention 带来的额外延迟在 A100 上最高约 `20%`，在 H100 上最高约 `30%`。

第三个模块是 dispatcher。它会在每次 decode iteration 结束后，以及每个 prefill batch 完成后重新决策，先为 decode 分配一个 best-fit 的 SM 数量来守住 SLO，再把剩余 SM 留给 prefill。如果一个新的短 prefill 在一个长 prefill 执行中途到达，MuxWise 可以允许前者 preempt 后者，但前提是被抢占者不会因此 miss 自己的 `TTFT`；而且系统禁止 recursive preemption。整体上，这个调度器是明显偏向 decode 的，prefill SLO 只有在 decode 被保护之后才尽力满足。

## 实验评估

这组实验对论文的目标场景支撑得比较扎实：它关注的是 strict-SLO、single-instance 的在线 serving。主平台是运行 SGLang 的 8 张 `A100-80GB` GPU，同时作者又在 8 张 H100 和 8 张 H200 上做了补充实验。模型覆盖 Llama-8B、Llama-70B，以及激活参数量为 22B 的 Qwen3-235B；基线包括 SGLang 中的 chunked-prefill、NanoFlow、LoongServe 和 SGLang-PD。工作负载既有真实的多轮 Conversation、Tool&Agent trace，也有 ShareGPT、OpenThoughts 和 LooGLE 这样的合成负载。

最核心的指标是 peak goodput。论文汇总后给出的总结果是：MuxWise 平均把 goodput 提升 `2.20x`，最高达到 `3.06x`。在 Tool&Agent 负载下逐步提高请求率、同时要求 99 分位 SLO 时，Llama-8B 上，MuxWise 相比 chunked-prefill、NanoFlow、LoongServe 和 SGLang-PD 的 goodput 分别提高 `2.6x`、`5.2x`、`2.0x` 和 `1.3x`；在 Llama-70B 上，相比 chunked-prefill、LoongServe 和 SGLang-PD 分别提高 `3.06x`、`2.62x` 和 `1.62x`。在真实 trace 中，chunked-prefill 和 NanoFlow 经常守不住 `TBT`，而 MuxWise 与两类 disaggregated baseline 通常能把 decode 延迟控住。代价是，SGLang-PD 由于静态保留了更多 decode 算力，`TBT` 有时会略低；但 MuxWise 几乎总能拿到更好的 `TTFT`，因为它只给 decode 分配“刚好够用”的 SM，把剩余算力收回给 prefill。

跨硬件结果同样重要。在 H100 和 H200 上，MuxWise 相对 chunked-prefill 的 99 分位 `TTFT` 平均提升 `2.28x`，99 分位 `TBT` 平均提升 `1.81x`。这说明收益并不只是某个实现小技巧带来的，而更像是 serving paradigm 本身更合理。我对实验的主要保留意见是边界条件：论文几乎都在单实例、单模型族、严格在线 SLO 的设定下评测，因此它并没有真正回答 cluster-level routing、autoscaling 或 multi-model interference 这些更高层问题。

## 创新性与影响

和 _Patel et al. (ISCA '24)_、_Zhong et al. (OSDI '24)_ 相比，MuxWise 最核心的新意在于拒绝继续支付 disaggregation 在 KV-cache 容量和重计算上的代价。和 _Agrawal et al. (OSDI '24)_ 相比，它不再把 token-budget 融合作为基本抽象，而是把两阶段的边界在 GPU 内部重新显式化。和 _Feng et al. (ISCA '25)_ 相比，它不仅做 stream overlap，还把 bubble 控制和 contention-aware scheduling 补全成一个完整系统。

因此，这篇论文的影响面会比较明确。对系统研究者来说，它提供了一种新的 serving 抽象，即 intra-GPU PD multiplexing，以及一套把这种抽象落地的调度和估计方法。对工程实践者来说，它的启发是：很多 today 的 LLM goodput 损失，不一定源于模型本身太重，而是源于 prefill/decode 到硬件映射方式本身设计得不对。

## 局限性

MuxWise 依赖像 GreenContext 这样支持低开销、进程内 SM 划分的硬件和软件能力，因此并不是所有推理栈都能直接迁移。它还需要针对每个模型和每类机器做离线 profiling，既要训练 solo-run predictor，也要构建 contention guard。论文认为这些成本可以接受，但与固定策略调度器相比，它显然增加了运维复杂度。

此外，这个系统在设计上明显优先保护 decode。contention guard 只为 decode 构建，而 prefill SLO 更多是间接处理；一旦系统负载超过峰值容量，论文基本接受某些 prefill 会 miss。更广义地看，MuxWise 仍然是 single-instance optimization。讨论部分虽然说明它可以与大规模 disaggregated fleet 互补，但也明确承认：当 SLO 很宽松、工作负载更像离线处理，或者 prefill instance 本身就被超长请求长期占满时，MuxWise 的优势会明显变小。最后，GreenContext 与 CUDA Graph 的结合还带来了大约 `6.2%` 的额外显存开销。

## 相关工作

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 通过 chunked prefills 让 prefill 与 decode 重叠执行，而 MuxWise 保持两阶段分离，只是在每块 GPU 内做空间复用。
- _Patel et al. (ISCA '24)_ — Splitwise 通过跨实例拆分 prefill 与 decode 来换取延迟隔离；MuxWise 则保持同址共存，以保留统一 KV-cache 池并在线重分配算力。
- _Zhong et al. (OSDI '24)_ — DistServe 同样追求 SLO 约束下的高 goodput，但它依赖跨实例 disaggregation，MuxWise 则在单实例内完成阶段共享。
- _Wu et al. (SOSP '24)_ — LoongServe 为长上下文场景提供动态 disaggregation，而 MuxWise 认为这种做法依旧会牺牲跨请求的 KV reuse。

## 我的笔记

<!-- 留空；由人工补充 -->
