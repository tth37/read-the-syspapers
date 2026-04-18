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
doi_url: "https://doi.org/10.1145/3779212.3790219"
code_url: "https://github.com/snowflakedb/ArcticInference"
tags:
  - llm-inference
  - gpu
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Shift Parallelism 解决的是一个很实际的 serving 矛盾：tensor parallelism 能把单请求延迟压低，但高流量下吞吐差；data parallelism 吞吐高，却救不了单请求时延。论文把 Sequence Parallelism 适配到推理场景，进一步让它与 TP 共享同一套 KV-cache 语义，于是系统可以按照 batch size 在以 SP 为主的 base mode 和 full TP 的 shift mode 之间切换。最终效果是在低流量下保住 TTFT 和 TPOT，在突发流量下又不再像纯 TP 那样明显掉吞吐。

## 问题背景

作者认为，真实 LLM 推理流量天然就是动态的。像 coding agent、chatbot 这类交互式请求，通常并发不高，但非常在意 TTFT 和 TPOT；而批处理式任务则会成批涌入，更关心总 tokens/s。单个生产集群往往会同时面对这两类负载，而且它们会随时间来回切换。

现有多 GPU 并行方案把系统逼进了二选一。Tensor Parallelism 在层内切分权重和计算，能加速单个请求，但要反复付出 all-reduce 通信代价，因此是典型的“低延迟、低吞吐”路线。Data Parallelism 正相反：模型副本跨请求并行，总吞吐高，但无法加速单个请求。运维上当然可以把 TP 和 DP 分成两个 fleet，但这样会重复部署容量，也增加路由与管理复杂度。更关键的是，论文指出 TP 和 DP 的 attention / KV-cache 布局并不一致，因此几乎不能廉价地在线切换。

## 核心洞察

论文最重要的洞察是，Ulysses 风格的 Sequence Parallelism 恰好具备推理时动态切换所需要的结构性质。它和 DP 一样，在大 batch 下能提供很好的吞吐，因为避免了 TP 在 attention 上的高成本 all-reduce；但它又不像 DP 那样和 TP 的 KV-cache 完全不兼容。只要实现时不仅保证 head 的分布一致，也保证 head 的顺序一致，SP 和 TP 就可以共用同一种 cache 解释方式。

这样一来，流量自适应就可以变成简单的运行时策略。batch 大时，使用 SP 或混合 `(SP, TP)` 配置，以较低 TTFT 和较高吞吐处理高流量；batch 小时，尤其是 decode 主导、SP 容易负载不均的低流量阶段，就切到 full TP 来压低 TPOT。真正关键的命题不是“负载变化时切换并行模式”本身，而是“只在两种 KV-cache 足够不变的并行模式之间切换”，这样切换才不会变成一次昂贵的数据搬运。

## 设计

设计分成两层。第一层是把 SP 真正扩展成可用于推理的通用实现。训练里的 SP 直接搬过来不够，因为推理模型普遍使用 grouped-query attention，很多模型的 KV head 数可能少于 GPU 数，而且推理 batch 规模会不断波动。为此，作者给 SP 加了 GQA 支持；当 KV head 不够时，用 all-to-all 中的复制机制扩展 KV cache；在小 batch 情况下，则通过 padding 把 token 补到 SP 度数的整数倍，让序列切分保持负载均衡。这个 padding 也解释了为什么 SP 不适合低流量 decode：多出来的冗余 token 会拉长 TPOT。

第二层才是 Shift Parallelism 本身。系统定义两个运行模式：base configuration 是 pure SP，或者在模型装不进单卡时使用 mixed `(SP, TP)`；shift configuration 则总是跨整节点的 full TP。运行时只需比较当前 batch size 和一个阈值：超过阈值就运行 base config，低于阈值就切到 shift config。

这里最难的部分是 KV-cache invariance。对于任意混合 `(SP, TP)` 布局，SP 的 all-to-all 之后，attention head 的全局顺序会发生交织；如果 full TP 仍按朴素顺序解释这些 head，cache 语义就不一致了。论文通过一个通用的 process-to-data mapping 解决这个问题，让 shift config 在加载 QKV shard 时遵循与 base config 相同的逻辑 head 顺序。也正是这一步，把“可以切换”从一句概念论断变成了可落地的系统实现。

论文还讨论了两种权重管理方式。on-the-fly slicing 没有额外内存开销，但在 Hopper FP8 tensor core 上需要额外转置，性能不理想。最终实现选择保留两个模型副本：一个用于 base mode，一个用于 shift mode，它们共享 attention 机制和 KV cache。论文给出的额外权重内存开销是 `1/SP`；例如 `SP = 8` 时，shift model 额外只增加 `12.5%` 权重内存。整个方案通过 ArcticInference plug-in 集成到 vLLM 中，并分别为两种模式做编译和 CUDA graph capture。

## 实验评估

实验对论文所瞄准的目标场景来说是比较完整的：单节点、多 GPU、流量动态变化的 LLM serving。主测试平台是带 NVSwitch 的 `8xH200` 节点。核心 dense-model 结果基于 FP8 的 Llama-70B 和 Qwen-32B，工作负载包括一个合成的 bursty trace、Azure LLM code trace、Mooncake conversation trace，以及参数化的合成请求。

合成突发实验把论文的系统主张讲得很清楚。和 vLLM 上的吞吐优化 DP 配置、延迟优化 TP 配置相比，Shift Parallelism 同时拿到了最好的中位数延迟和接近 DP 的吞吐：median TTFT 只有 `148 ms`，而 DP 是 `1,355 ms`，TP 更高达 `3.93 s`；median TPOT 是 `51 ms`，基线在 `83-85 ms`；peak throughput 达到 `69,147 tok/s`，明显更接近 DP 的 `75,535 tok/s`，而不是 TP 的 `51,162 tok/s`。在 Azure code trace 上，论文也显示它在 burst 到来时能持续维持更低的 TTFT、TPOT 和 completion time，而 TP 在这些时刻的排队增长尤其明显。

参数化 benchmark 用 `4k` 输入、`250` 输出 token，把结论讲得更干净。以 Llama-70B 为例，Shift Parallelism 的 TTFT 是 `102 ms`，而 TP 是 `159 ms`、DP 是 `614 ms`；同时 combined throughput 从 TP 的 `24.7k tok/s` 提升到 `37.4k tok/s`。把输入长度从 `2k` 扩展到 `128k` 后，作者总结的 headline 结果是：相对 DP 最多 `6.97x` 更快的 response，相对 TP 最多 `1.56x` 更快的 response，相对 DP 最多 `2.45x` 更快的 generation，相对 TP 最多 `1.51x` 更高的 peak throughput。arrival-rate sweep 也很有说服力：DP 和 TP 在某个每秒几请求的临界点会发生优劣反转，而 Shift Parallelism 在整个区间里都保持最低 completion time。

我认为这些实验对论文的核心主张支撑得比较充分，但边界也很明确。它并没有在持续高流量下打败 DP 的绝对峰值吞吐，Table 3 里作者自己也明确承认了这一点。它真正赢的地方是：在保留接近 TP 的低延迟特性的同时，显著收回 TP 在吞吐上的损失。这个论点更贴近生产现实，而实验也基本证实了它。

## 创新性与影响

和 _Agrawal et al. (OSDI '24)_ 相比，这篇论文关注的不是 chunked-prefill 调度，而是更底层的多 GPU 并行模式本身如何选择与切换。和 _Patel et al. (ISCA '24)_ 把 prefill / decode 拆到不同资源上的思路相比，Shift Parallelism 选择留在同一套部署里，通过保持 cache 布局一致来避免阶段间 KV 迁移。它最有新意的点，因此不是单独发明 SP，而是把 SP 重新定位成 TP 的“高吞吐伴侣”，再把两者通过 KV-cache invariance 串成一个可运行的推理系统。

这对构建共享 LLM fleet 的工程团队很有意义，因为真实流量本来就会在交互式和批处理式之间来回摆动。对后续研究来说，它也提供了一个很有价值的角度：调度器不一定只能在固定执行底座之上做选择，底座本身的并行模式也可以成为运行时控制变量。

## 局限性

论文也很坦诚地说明，Shift Parallelism 不是全局最优。持续高流量下，DP 仍然掌握最高吞吐的那个角落，因为它彻底避开了 attention 通信。长上下文下的吞吐仍然强烈受 attention 代价限制，而作者把这部分明确留给 sparse-attention 一类技术去解决。实现上，它还继承了 vLLM 在小模型上的不小开销，所以一些剩余性能差距并不能完全归因于并行模式选择。最后，MoE 结果虽然初步乐观，但 expert parallelism 与更广泛的 sparse-model 设计空间都被留作未来工作。

## 相关工作

- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 通过 chunked prefill 改善 prefill / decode 重叠，而 Shift Parallelism 改变的是底层 GPU 并行模式，并且设计上就是要与 chunked-prefill 系统叠加。
- _Kwon et al. (SOSP '23)_ — PagedAttention 解决持续 serving 下 KV-cache 内存管理问题；Shift Parallelism 默认建立在这类 serving substrate 之上，关注点是多 GPU 执行策略。
- _Patel et al. (ISCA '24)_ — Splitwise 把 prefill 和 decode 拆到不同 worker；Shift Parallelism 则保留单节点部署，通过在 SP 和 TP 之间切换来贴合流量，而不在阶段之间搬运 KV 状态。
- _Qin et al. (FAST '25)_ — Mooncake 把 KV cache 看成一个可解耦的存储问题；Shift Parallelism 关注的则是节点内部如何在 GPU 间并行化推理，以缓解延迟与吞吐之间的冲突。

## 我的笔记

<!-- 留空；由人工补充 -->
