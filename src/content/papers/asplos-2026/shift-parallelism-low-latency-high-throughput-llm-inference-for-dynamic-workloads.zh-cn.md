---
title: "Shift Parallelism: Low-Latency, High-Throughput LLM Inference for Dynamic Workloads"
oneline: "Shift Parallelism 利用 KV-cache 不变性在运行时切换 sequence parallelism 与 tensor parallelism，在低流量降延迟、在突发下保住吞吐。"
authors:
  - "Mert Hidayetoglu"
  - "Aurick Qiao"
  - "Michael Wyatt"
  - "Jeff Rasley"
  - "Yuxiong He"
  - "Samyam Rajbhandari"
affiliations:
  - "Snowflake, Menlo Park, California, USA"
  - "Snowflake, Bellevue, Washington, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790219"
code_url: "https://github.com/snowflakedb/ArcticInference"
tags:
  - llm-inference
  - gpu
  - scheduling
reading_status: read
star: true
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Shift Parallelism 把多 GPU 并行模式本身变成了 LLM serving 的运行时控制量。论文先把 Sequence Parallelism 扩展到推理场景，再保证它与 TP 之间的 KV-cache 语义不变，并按 batch size 在以 SP 为主的 base mode 与 full TP 的 shift mode 之间切换。这样同一套部署既能在低流量时保持低延迟，又能在突发流量下追回大量 TP 原本会丢掉的吞吐。

## 问题背景

论文抓住的是一个很多 serving 系统都会碰到、但往往被简化掉的现实：同一套 LLM 部署往往既要接交互式流量，也要接批处理式突发。coding agent、chatbot 这类请求通常一次只来几个，更看重 `TTFT` 和 `TPOT`；总结、后训练之类工作则会一批一批涌入，更关心总 tokens/s。真实流量会在这两种模式之间来回摆动，所以固定使用一种并行策略，必然会在某些时段浪费成本或牺牲延迟。

现有主流并行方式把这个权衡切得很别扭。Tensor Parallelism 在层内切分权重和计算，对 decode latency 尤其有利，但 repeated all-reduce 会明显拉低 combined throughput。Data Parallelism 则正好相反：总吞吐高，却完全不能加速单个请求。理论上你可以同时维护 TP fleet 和 DP fleet，再按请求类型路由，但那会复制容量、增加运维复杂度。更麻烦的是，论文指出 TP 和 DP 的 attention / KV-cache 布局并不兼容，所以也不能廉价地在线切换。

## 核心洞察

论文的核心洞察是：Ulysses 风格的 Sequence Parallelism，正好可以充当 TP 在推理场景下的“高吞吐搭档”。SP 避开了 TP 在 attention 上的 all-reduce 模式，因此在大 batch 下更利于 `TTFT` 和 throughput；与此同时，它又不像 DP 那样和 TP 的 KV cache 天生不兼容。只要实现时不仅保证 head 的分布一致，也把 head 的逻辑顺序固定住，SP 和 TP 就能共享同一种 KV-cache 语义。

这会把问题从“怎样在两种互不兼容的 serving 模式之间迁移”改写成“什么时候在两种兼容模式之间切换”。论文的答案很直接：大 batch 时保留 SP，或者混合 `(SP, TP)` 作为 base configuration；小 batch、尤其 decode 主导时切到 full TP。原因并不是 TP 在所有意义上都更低延迟，而是 SP 更擅长 prefill 和高吞吐，而 TP 在小 batch 场景下能避免 SP 因 padding 和负载不均带来的 `TPOT` 劣势。

## 设计

设计的第一部分，是把 SP 从训练版真正扩展成推理版。训练里的 SP 不够用，因为推理模型普遍带 `GQA`，而且 KV head 数可能少于 GPU 数，batch 规模也会持续波动。为此，作者让 SP 支持 `GQA`；当并行度超过可直接分配的 KV heads 时，通过 all-to-all 路径做 KV cache replication，而不是像 TP 那样靠重复计算解决；当 batch 很小时，再通过 padding 把 token 补到 SP 度数的整数倍，使各 GPU 的工作量平衡。这个 padding 很关键，因为它一方面保证 SP 在低流量下还能跑，另一方面也直接解释了为什么低流量 decode 阶段不适合继续用 SP：多出来的冗余 token 会把 `TPOT` 拉高。

第二部分才是 Shift Parallelism 的切换结构。base configuration 可以是 full SP，也可以是在 `SP x TP = P` 约束下的混合 `(SP, TP)`，用来兼顾模型是否装得下以及 KV cache 是否还有足够空间支持并发。shift configuration 则永远是跨同一组 GPU 的 full TP。运行时依据 batch-size threshold 做选择：batch 大就保留 base config，batch 小就切到 full TP。

真正难的是 generalized KV-cache invariance。对于混合 `(SP, TP)` 布局，SP 的 all-to-all 会把逻辑 attention head 顺序打散成交织顺序；如果 shift 到 full TP 时仍按朴素顺序解释这些 head，即便 tensor 形状对得上，cache 的语义也已经变了。论文通过一个 process-to-data mapping 解决这一点，让 shift config 加载 Q 权重和 QKV shard 时沿用 base config 的逻辑 head 顺序。也正因为这一步，系统才能做到“切换时不重写 KV cache”。

论文还很务实地比较了两种权重管理方式。on-the-fly slicing 没有额外存储成本，但在 Hopper 的 FP8 tensor core 上需要额外转置，性能不够好。最终实现采用双模型副本：base model 和 shift model 分开加载，但共享 attention 机制和 KV cache。额外权重开销是 `1/SP`；例如 `SP = 8` 时，只增加 `12.5%` 的权重内存。整个方案通过 ArcticInference plug-in 集成进 vLLM，并分别为两种模式做编译和 CUDA graph capture。

## 实验评估

这篇论文的实验范围和它的主张是匹配的：它关心的是单节点、多 GPU、动态流量下的 serving，而不是跨多节点的大规模分布式推理。主硬件平台是带 `NVSwitch` 的 `8xH200` 节点，软件底座是 vLLM 加 ArcticInference plug-in。主结果用的是 FP8 的 Llama-70B 和 Qwen-32B，工作负载则覆盖合成 burst trace、Azure LLM code trace、Mooncake conversation trace，以及受控的合成请求流；后面还加了两个 MoE 模型来验证 generalized SP 路径。

合成突发实验最能概括整篇论文。和 vLLM 里的 throughput-optimized DP、latency-optimized TP 相比，Shift Parallelism 同时拿到了接近 DP 的吞吐和明显更好的延迟：median `TTFT` 是 `148 ms`，DP 为 `1,355 ms`，TP 更达到 `3.93 s`；median `TPOT` 是 `51 ms`，基线在 `83-85 ms`；peak throughput 为 `69,147 tok/s`，已经很接近 DP 的 `75,535 tok/s`，明显好于 TP 的 `51,162 tok/s`。这组数字基本把论文想证明的点说清楚了：它不是要在高流量下超过 DP，而是要避免 TP 在 burst 来临时因为排队而崩掉。

真实 trace 也支持同样的结论。对 15 分钟 Azure code trace，论文报告它在整个重放过程中都取得最低的 `TTFT`、`TPOT` 和 completion-time 分布，优势在 burst 时最明显。对 Mooncake conversation trace，DP 和 TP 在单节点上都扛不住到达速率，KV cache 会被填满，等待时间持续增长；只有 SP 和 Shift Parallelism 能把 completion time 维持在有限范围内。这个结果很重要，因为它说明收益不只是更漂亮的 p50，而是系统确实更不容易进入排队失稳状态。

受控的 `4k` 输入、`250` 输出 benchmark 让数字更容易横向比较。Llama-70B 上，Shift Parallelism 给出 `102 ms` 的 `TTFT`、`10.1 ms` 的 `TPOT` 和 `37.4k tok/s` 的 combined throughput；TP 分别是 `159 ms`、`9.34 ms` 和 `24.7k tok/s`；DP 则是 `614 ms`、`22.5 ms` 和 `45.9k tok/s`。Qwen-32B 上，Shift 对应 `86.41 ms`、`9.48 ms`、`53.8k tok/s`；TP 是 `113 ms`、`8.68 ms`、`38.3k tok/s`；DP 是 `385 ms`、`18.8 ms`、`70.1k tok/s`。把 context length 扩到 `2k-128k` 后，作者总结的 headline 结果是：相对 DP 最多 `6.97x` 更快 response、相对 TP 最多 `1.56x` 更快 response、相对 DP 最多 `2.45x` 更快 generation、相对 TP 最多 `1.51x` 更高 peak throughput。arrival-rate sweep 也很有说服力：TP 和 DP 只在“每秒几请求”附近各有胜负，而 Shift Parallelism 在整段区间里都保持最低 completion time。

我认为这些实验对论文的中心论点支撑得比较充分，但边界也很清楚。首先，论文明确承认 DP 仍然占据持续高流量下的绝对峰值吞吐角落，因为 attention parallelization 总要付通信代价。其次，整套实验高度集中在单节点、`NVSwitch` 很强的环境里，所以它更能说明“单机内动态切换并行模式”有效，而不是已经解决了跨节点 serving fleet 的问题。

## 创新性与影响

和 _Agrawal et al. (OSDI '24)_ 相比，这篇论文不是在固定 serving substrate 上再做一个更聪明的 scheduler，而是直接把底层并行模式变成动态可切换对象。和 _Patel et al. (ISCA '24)_ 那种把 prefill / decode 拆到不同资源上的设计相比，Shift Parallelism 选择留在同一套部署里，通过保证 KV-cache 语义不变来避免阶段间 KV 迁移。真正的新意因此不是“把 SP 用到推理里”这一点本身，而是把 SP 重新定位为 TP 的高吞吐搭档，再把两者通过 KV-cache invariance 连接成一个可运行的系统。

这个思路对生产环境很有价值，因为真实 LLM fleet 的流量本来就会在交互式和批处理式之间来回摆动。对后续研究而言，它也提供了一个很好的方向：执行底座的并行模式不一定非得是编译期静态决定的，它完全可以成为 serving control plane 的一部分。

## 局限性

论文很坦诚地说明，Shift Parallelism 不是普适最优。持续高流量下，DP 仍然掌握绝对峰值吞吐，因为它完全绕开了 attention 通信。长上下文下的 serving 也依然会被 attention 成本主导，所以即便 Shift Parallelism 比 TP 更合适，整体 throughput 还是会随着 context 变长而明显下降。作者把 sparse attention 之类技术视为正交方向，并没有在本文里解决。

此外，这个方案背后也有明显的部署前提。切换阈值依赖 batch size，并且需要针对具体模型、硬件和量化配置做离线 profiling。实现上还要为 shift path 额外保留一份权重副本，虽然成本只有 `1/SP`，但毕竟不是零。再加上实验几乎都集中在带 `NVSwitch` 的单节点 `H200` 平台，论文并没有说明相同机制在多节点通信、expert parallelism 或更异构的 fleet 中还能否维持同样效果。

## 相关工作

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 通过 chunked prefill 改善 prefill / decode 重叠，而 Shift Parallelism 改变的是底层 GPU 并行模式，并且设计上就是要与 chunked-prefill 系统叠加。
- _Kwon et al. (SOSP '23)_ — PagedAttention 解决持续 serving 下 KV-cache 内存管理问题；Shift Parallelism 默认建立在这类 serving substrate 之上，关注点是多 GPU 执行策略。
- _Patel et al. (ISCA '24)_ — Splitwise 把 prefill 和 decode 拆到不同 worker；Shift Parallelism 则保留单节点部署，通过在 SP 和 TP 之间切换来贴合流量，而不在阶段之间搬运 KV 状态。
- _Qin et al. (FAST '25)_ — Mooncake 把 KV cache 看成一个可解耦的存储问题；Shift Parallelism 关注的则是节点内部如何在 GPU 间并行化推理，以缓解延迟与吞吐之间的冲突。

## 我的笔记

<!-- 留空；由人工补充 -->
