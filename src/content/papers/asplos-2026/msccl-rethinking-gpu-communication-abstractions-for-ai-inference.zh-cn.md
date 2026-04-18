---
title: "MSCCL++: Rethinking GPU Communication Abstractions for AI Inference"
oneline: "MSCCL++ 用贴近硬件的 channel 原语加 DSL 重构 GPU 通信栈，让 AI 推理拿到接近手写内核的性能而不必维护厂商绑定的自定义代码。"
authors:
  - "Changho Hwang"
  - "Peng Cheng"
  - "Roshan Dathathri"
  - "Abhinav Jangda"
  - "Saeed Maleki"
  - "Madan Musuvathi"
  - "Olli Saarikivi"
  - "Aashaka Shah"
  - "Ziyue Yang"
  - "Binyang Li"
  - "Caio Rocha"
  - "Qinghua Zhou"
  - "Mahdieh Ghazimirsaeed"
  - "Sreevatsa Anantharamu"
  - "Jithin Jose"
affiliations:
  - "Microsoft Research, Vancouver, BC, Canada"
  - "Microsoft Research, Redmond, WA, USA"
  - "Microsoft Research, Beijing, China"
  - "Microsoft Azure, Redmond, WA, USA"
  - "Microsoft Azure, Cambridge, MA, USA"
  - "Microsoft Azure, Minneapolis, MN, USA"
  - "Microsoft Azure, Austin, TX, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790188"
code_url: "https://github.com/microsoft/mscclpp"
tags:
  - gpu
  - networking
  - llm-inference
  - compilers
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

MSCCL++ 的核心主张是，GPU 通信库不该让用户在“维护一套手写、硬件绑定的自定义内核”和“接受通用 collective 的性能上限”之间二选一。它把三类贴近硬件的 channel 抽象、一个 DSL，以及一个可替换 NCCL 的 collective 库叠成一层层接口，并展示这套栈既能保住接近硬件上限的通信性能，也能加速真实的 LLM 推理。

## 问题背景

论文从一个 AI 系统里越来越常见的现实问题切入：通信已经成了首要瓶颈，尤其在 LLM inference 中，作者引用的真实工作负载里通信内核可占端到端时间的 `10%-40%`。但主流方案仍然是 NCCL 这类通用 collective 库。它们有意把许多底层细节藏在同步式 `send/recv` 原语后面，内部替用户选算法，对外却只暴露很窄的控制面。这对一般应用很方便，但也正因此，高性能用户不断绕开它们，转而写自己的通信内核。

之所以会出现这些自定义实现，有几个很具体的原因。不同工作负载关注的是 latency-bandwidth 曲线上的不同位置：decode 在意小消息延迟，prefill 和更像训练的场景则更关心吞吐。collective 又不只是搬运数据，往往还夹着 reduction 等计算，所以“纯传输最快”的实现，并不一定是与计算重叠后整体最优的实现。再加上 GPU interconnect 更新太快，生产团队常常希望在通用库尚未跟进之前，就先用上新的传输模式或 switch 特性。

这套现状的代价就是工程复杂度。团队一旦自己写通信路径，就要同时处理 GPU、CPU、NIC 的协同，处理弱内存模型下的数据一致性，还要理解 DMA、peer memory access、switch multicast 这类链路相关机制。于是，论文真正要解决的问题不只是“怎样让 AllReduce 更快”，而是“怎样在不给每个推理系统都背上一套脆弱、厂商绑定通信栈的前提下，仍然让专家用户能够吃到硬件特性的全部红利”。

## 核心洞察

论文最重要的主张是：只要抽象边界画对了，可移植性和性能并不冲突。MSCCL++ 因此不是从 AllReduce 这类 collective 往下调，而是从真实 interconnect 暴露出来的几种基础传输模式往上搭：port-mapped I/O、memory-mapped I/O、以及 switch-mapped I/O。如果把这些机制直接暴露出来，同时把同步语义说清楚、避免强制引入中间 buffer，那么更高层仍然可以做非常激进的定制。

由此得到的是一个分层设计。Primitive API 面向想要精确控制、也最在乎抽象开销的专家。DSL 保留这些 primitive 的 one-sided 和 asynchronous 属性，但让开发者能在 thread block、chunk、rank 这一层描述通信算法，而不用直接写原始 CUDA/HIP 细节。Collective API 则把这些算法包装成一个与 NCCL 兼容的接口，提供给只想“直接换库”的用户。最值得记住的命题是：同一套通信栈可以支持渐进式定制，普通用户直接拿 collective 库即可，只有真正需要最后一点性能的人才继续往下钻。

## 设计

Primitive API 围绕三种 channel 展开。`PortChannel` 负责 port-mapped 传输，比如节点内 DMA copy 或 RDMA send。它的 `put` 是 zero-copy、one-sided、asynchronous 的；`signal`、`wait`、`flush` 则明确规定了接收方何时可以读数据、发送方何时才能安全复用 buffer。由于当前一些 RDMA 或 DMA 传输仍需主机侧发起，每个 port channel 都维护一个 CPU thread 和请求队列。这是论文一个很关键的取舍：即便底层硬件路径还离不开 CPU，API 仍然向 GPU 端提供异步、可组合的语义。

`MemoryChannel` 面向 peer-memory access，并提供两种协议。`HB` 协议把同步摊到大 chunk 上，追求高带宽；`LL` 协议则把同步粒度压得更细，以换取更低延迟。`SwitchChannel` 则抽象出像 NVLink SHARP 这种 switch 直接做 multicast 或 reduction 的硬件能力，具体通过 multimem 指令实现。三类 channel 的共同不变量是：数据传输和同步被显式解耦，所以内核可以在等待远端数据时继续做本地计算，而不必卡在一个两端 rendezvous 式的同步点上。

再往上，DSL 给出所有 rank 与 thread block 的全局视图。用户在 Python 里用 channel、buffer 和 chunk slice 描述算法；MSCCL++ 把程序 lowering 成 execution plan，自动补入所需同步，并在依赖允许时把“本地 reduce + 远端 put”这类操作融合成一个动作。论文里那段 overlapped ring `ReduceScatter` 的例子很能说明问题：把每个 chunk 再切成两半后，一半可以在通信进行时同步做 reduction。最后，executor 在一个通用执行内核里解释这个 plan。collective 库则把这些机制进一步封装成 `1PA`、`2PA`、`2PR`、hierarchical 等算法，并通过一个兼容 NCCL 的 API 暴露出去。

## 实验评估

第一个问题是，这些抽象到底有没有把性能“封装没了”。Table 1 的结果说明基本没有。在论文的 H100 环境里，MSCCL++ 达到了与“best achievable”相同的 NVLink throughput（`397.5 GB/s`），NVLink latency 也几乎一样（`829 ns` 对 `822 ns`），InfiniBand throughput 同样打平（`48.94 GB/s`），只是 InfiniBand latency 略高（`4.89 us` 对 `3.76 us`）。对一个抽象层来说，这已经非常接近“性能守恒”。

其后的 collective 结果也很强。在 A100-40G 上，MSCCL++ 的 AllReduce 对小消息相对 NCCL 最多快 `4.2x`，相对 MSCCL 最多快 `3.1x`；大消息也最多快 `1.8x`。AllGather 上，小消息相对 NCCL 的提升最高达到 `5.4x`。H100 上 `SwitchChannel` 的作用尤其明显：它相对等价的 `MemoryChannel` 实现最多带来 `56%` 更高带宽，并把总体 AllReduce 提升拉到相对 NCCL 小消息最高 `2.8x`、大消息最高 `2.4x`。在 MI300x 上，这套抽象也能适应完全不同的拓扑，小消息相对 RCCL 最多快 `3.8x`，大消息最多快 `2.2x`。我觉得这部分最有说服力的地方在于，论文并没有宣称“一个算法到处赢”，而是证明“这套抽象让面向不同拓扑的算法更容易表达出来”。

真正关键的还是端到端 inference。把 vLLM 中 `Llama3-70B` 在 `8x A100-80G` 上的 NCCL 换成 MSCCL++ 后，decode latency 平均下降 `1.11x`，prefill 最多提升 `1.06x`。在 `16x H100` 的 SGLang 上，DeepSeek-V3 的 decode throughput 平均提升 `1.31x`。DeepEP 的结果在定性上也很重要：作者用 `PortChannel` 替换 NVIDIA 特定的 IBGDA 路径后，和 NVSHMEM 方案几乎没有可见性能差距，但代码更可移植。主要的保留意见是，很多 collective 结果来自离线挑选出的最佳配置，而不是在线自动调优；因此论文更直接证明了“这套抽象能表达出高性能内核”，而不是“它已经自动把最佳内核选出来了”。

## 创新性与影响

和 _Cowan et al. (ASPLOS '23)_ 相比，这篇论文的新意不只是“又一个 collective DSL”，而是把 DSL 建在 one-sided、asynchronous primitive 之上，而不是继续沿用 NCCL 的同步 send/recv 底座。和 NCCL、RCCL 相比，它贡献的也不是某一个更快的 AllReduce schedule，而是一整套让 DMA-copy、multimem、拓扑特化流水线这些底层能力仍然可见的通信栈。和 TensorRT-LLM、DeepEP 这类自定义推理通信内核相比，它的核心说服点则是：这些优化不应反复被塞进各个 serving 系统里，而应该沉淀为一个可复用的库。

因此，这篇论文大概率会被两类人引用。系统研究者会把它当作一个关于“加速器 I/O 的抽象边界应该放在哪里”的案例。构建 LLM serving 栈的工程团队会引用它，因为它展示了一条摆脱长期维护 bespoke communication kernel 的路径。RCCL 和 SGLang 已经采用 MSCCL++，也明显增强了这部分影响力论证。

## 局限性

论文本身也承认，可移植性不是自动得到的。MSCCL++ 仍然需要为不同硬件实现对应的 primitive，最佳 collective 内核也主要依赖按平台和消息大小做离线 profiling 选择，而不是复杂的在线 autotuning。DSL 也有可量化的额外开销：相对直接使用 Primitive API 的版本，它平均慢 `3%`，在某个角落场景里最多慢 `18%`。

此外，这套设计也受到底层硬件约束。`PortChannel` 目前在一些传输路径上仍依赖 CPU thread 发起请求，因此它并没有在硬件不支持时神奇地消除 host involvement。`SwitchChannel` 也需要类似 NVLink SHARP 这类专门硬件能力。最后，虽然标题写的是 “AI inference”，论文的大部分实证仍然是在验证“更快的 collective 如何转化成几种推理框架里的收益”。这足以验证通信层面的中心论点，但并不意味着 MSCCL++ 本身已经解决了 admission control、batching、multi-model routing 这类更广义的 serving 问题。

## 相关工作

- _Cowan et al. (ASPLOS '23)_ — MSCCLang 在 NCCL/RCCL 风格的 primitive 之上合成 collective，而 MSCCL++ 进一步把 primitive 本身换成了可见 one-sided asynchronous 语义的新底座。
- _Cai et al. (PPoPP '21)_ — SCCL 能生成高效 collective schedule，但仍然默认传统 collective primitive；MSCCL++ 的观点是，这类合成方法也需要更丰富的底层通信接口。
- _Shah et al. (NSDI '23)_ — TACCL 强调拓扑感知的 collective synthesis，而 MSCCL++ 更关注把 transfer mode 与 synchronization semantics 暴露出来，好让这些算法真正发挥出来。
- _Hwang et al. (NSDI '23)_ — ARK 也把分布式 ML 控制更多推向 GPU 侧，但它是一个端到端单体系统；MSCCL++ 则把可复用的通信抽象单独抽成一个库栈。

## 我的笔记

<!-- 留空；由人工补充 -->
