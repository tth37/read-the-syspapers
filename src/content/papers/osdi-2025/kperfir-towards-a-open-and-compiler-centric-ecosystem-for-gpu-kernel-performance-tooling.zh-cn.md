---
title: "KPerfIR: Towards an Open and Compiler-centric Ecosystem for GPU Kernel Performance Tooling on Modern AI Workloads"
oneline: "KPerfIR 把 GPU kernel profiling 变成 Triton 编译流程里的 IR pass，让工具保留循环与 region 语义，从而解释重叠瓶颈并指导 FA3 优化。"
authors:
  - "Yue Guan"
  - "Yuanwei Fang"
  - "Keren Zhou"
  - "Corbin Robeck"
  - "Manman Ren"
  - "Zhongkai Yu"
  - "Yufei Ding"
  - "Adnan Aziz"
affiliations:
  - "University of California, San Diego"
  - "Meta"
  - "George Mason University"
  - "OpenAI"
conference: osdi-2025
code_url: "https://github.com/triton-lang/triton/tree/main/third_party/proton/dialect"
tags:
  - gpu
  - compilers
  - observability
category: ml-compilers-and-gpu-kernels
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

KPerfIR 把 GPU profiling 从外部事后分析工具，变成编译器内部的一等机制。它在 Triton 的多层 IR 中加入 profiling 操作，再把这些操作下沉为后端相关的计数器读取、缓冲区写入和运行时解码逻辑，由此构建可复用的性能工具。论文用一个 region-based timing tool 证明，这套方法不仅能看懂复杂的 intra-kernel overlap，还足以指导 FlashAttention-3 的真实优化。

## 问题背景

这篇论文要解决的，不是“GPU 上没有 profiler”，而是“现有 profiler 和现代 AI compiler 说的不是同一种语言”。像 Triton 这样的 AI compiler，已经把 software pipelining、warp specialization、Tensor Core、TMA 之类的结构显式编码在 TTIR 和 TTGIR 中。可主流 profiling 工具看到的往往只是 kernel 和一堆聚合后的硬件计数器。它们能告诉开发者某个 kernel 利用率不高、某类 stall 很多，却很难回答更关键的问题：到底是哪个 loop stage 卡住了，哪个 warp role 在关键路径上，或者某个 compiler pass 应该把哪条 barrier 或哪段 region 往前挪。

这种脱节在现代 AI kernel 中尤其严重，因为性能越来越依赖细粒度重叠。论文反复用 FlashAttention-3 举例：不同 warp group 负责 K/V 加载、GEMM 和 softmax，期间还有异步 barrier 和 producer-consumer 协同。传统 profiler 缺少 IR 语义，无法把时间线稳定地映射回循环迭代、warp 角色和高层 region，也就难以产出对 kernel 作者和 compiler pass 真正可操作的结论。对于自动优化来说问题更明显：如果 profiling 数据是编译器外部的副产物，那么 autotuner 或 optimization pass 只能通过额外旁路，把某个性能数字再硬拼回具体变换。

## 核心洞察

论文的核心主张是，性能工具应该生活在编译器的 IR 生态里，而不是站在外面旁观。KPerfIR 把 profiling region 表达成显式 IR marker，再沿着 Triton 的多层 lowering 流水线，把这些 marker 变成具体的计数器读取、记录存储和运行时回传逻辑。因为 profiling 起点是 IR 而不是二进制，它能在很长一段编译链路里保留循环、region、warp-group 角色以及跨后端的程序结构语义。

这样一来，profiler 的角色就变了。它不再是功能固定的外部工具，而是一个“可编程的 compiler pass”。用户可以手工定义想看的 region，编译器也可以自动插桩；同一套抽象还能同时服务 Nvidia 和 AMD 后端。论文认为，这种 compiler-centric 设计同时带来三件事：更丰富的语义化测量、更自然的 profile-guided compiler optimization，以及更好的工具复用性。

## 设计

KPerfIR 的实现是一套插在 Triton 内部的多层 profiling 栈。最高层的 KPerfIR dialect 提供 `RecordOp`，只表达“这里是某个命名 region 的开始或结束”，并不提前绑定具体指标或存储策略。随后 lowering pass 会把它转成 KPerfGPUIR 中更接近 GPU 的操作，例如 `ReadCounterOp`、`StoreCounterOp`、`InitOp`、`FinalizeOp`，以及本地、shared、global、stack 等不同层级的分配操作。具体生成什么，由 pass 选项控制，例如 metric type、profiling granularity、buffer strategy 和 buffer placement。也就是说，同一个高层接口可以支撑多种 profiling 工具。

之所以要分层，是因为 MLIR 层和 LLVM 层各有长处也各有缺点。只在 MLIR 层插桩，能够看到循环、region 和数据对象，但离底层执行还远，容易受到后续 codegen 和调度影响。只在 LLVM 层处理，则会更接近真实指令，却容易失去和原始程序结构的关联。KPerfIR 采用两层结合的办法：在 TTIR/TTGIR 上插入语义 marker，下沉成 GPU profiling op，再继续下沉到 LLVM IR 和目标后端代码。运行时会给 kernel signature 补一个 profiling memory 参数，把记录拷回 host，再通过命令行 API 和 Python API 让用户或 compiler pass 动态 patch / unpatch 插桩逻辑。

论文重点展示的是一个用于分析 intra-kernel overlap 的 region-based timing tool。每个 region 会写入紧凑的 8-byte start/end record，存到按 warp-group 划分的 shared-memory buffer 中。由于真实高性能 kernel 剩余的 shared memory 很有限，工具采用 circular buffer，只保留 trace 尾部。最关键的细节是 trace replay：如果对异步指令直接做朴素计时，profiling 本身会扭曲 barrier wait time。为此，KPerfIR 在异步 launch 和 wait 附近放置多个 marker，再在后处理中减掉 bookkeeping 开销，从而还原更可信的执行区间。

## 实验评估

实验平台包括 Nvidia H100-HBM3 和 AMD MI300X，软件栈是 Triton 3.0.0 与 LLVM 19.1。总体上，这个工具足够轻量，能进入真实优化流程：摘要给出的平均 profiling overhead 是 8.2%，相对误差约 2%；详细实验中，大多数 kernel 的端到端 latency overhead 都低于 10%，最差也低于 15%。在指令级别，一条 profiling record 在 H100 上大约增加 33 cycles，在 MI300 上大约增加 60 cycles。作者还把“按插入指令数推导的理论 slowdown”和真实 slowdown 对比，发现额外的 optimization degradation 控制在约 2% 以内，说明 IR 级插桩没有严重破坏编译器优化。

内存开销也被设计得比较克制。region profiler 先把记录存进 shared memory，等 kernel 结束时再一次性拷回，而不是频繁写 global memory。即使在最吃存储的 benchmark 中，工具仍然留下了 10.9 KB 的空余 shared memory，并能为 4 个 profiled region 保留 16 次迭代的 trace 数据。这一点很重要，因为论文关注的本来就是资源已经很紧张的高性能 AI kernel。

最有说服力的结果来自 FlashAttention-3 案例研究。KPerfIR 在 Triton 的 warp-specialized FA3 kernel 中找到了关键路径：V-load 阶段会被一个 arrival barrier 卡住，导致 overlap 窗口被拉长。基于这条时间线，作者把 barrier 提前，并在 prologue 里增加预加载，让 GEMM 和加载更充分地重叠。最终优化后的 Triton-FA3 在他们的 benchmark 中，相比 vanilla Triton FA3 提升 24.1%，相比对比的最佳手写 FA3 也快 7.6%。论文还进一步利用 profiled stage latency 构建了 software pipelining 和 warp specialization 的重叠模型，说明这套基础设施不仅能画 trace，也能直接驱动 compiler decision。

## 创新性与影响

KPerfIR 的创新点不只是“又一个 GPU profiler”，而是把 profiling 变成可复用的 compiler substrate。现有工具要么是懂硬件却不懂编译器语义的 vendor profiler，要么是绑死在单一 DSL 或单一后端上的定制工具。KPerfIR 的贡献在于，它定义了一套 profiling dialect、lowering pipeline 和 runtime contract，让性能工具和编译优化共享同一层抽象。

这种设计会影响几类人。对 kernel 开发者来说，它提供了带 region 和 iteration 语义的时间线，适合定位 overlap 问题。对 compiler 工程师来说，它让 optimization pass 能直接消费 runtime feedback。再加上它建立在 Triton 与 MLIR 风格的多层 IR 之上，论文把它定位成开放 profiling 生态的起点，而不是只为 FA3 服务的一次性工具。

## 局限性

论文明确承认，KPerfIR 无法暴露 vendor profiler 拥有的全部底层指标。有些性能计数器只通过厂商私有接口开放，因此 compiler-centric profiler 在硬件可见性上仍然不如 Nsight Compute 或 ROCm 的内部工具。另一点是，插桩不可能完全“零扰动”。尤其在 AMD 平台上，更多调度细节暴露给软件，profiling 指令更可能影响 instruction scheduling，所以 KPerfIR 提供的是缓解手段和调节旋钮，而不是完全消除失真。

它的适用范围也还有限。当前系统深度集成在 Triton 中，展示对象主要是 AI kernel，而不是任意 MLIR compiler 或通用 GPU 软件。circular buffer 的策略也意味着长 trace 只保留最近的一段尾部。论文虽然讨论了分布式 workload 和非 AI 场景的潜力，但那些都还是未来方向，不是已经完整验证的结果。

## 相关工作

- _Tillet et al. (MAPL '19)_ - Triton 提供了 KPerfIR 所依赖的多层 GPU compiler substrate，而 KPerfIR 在其上补上 profiling dialect 和 lowering pass。
- _Lattner et al. (CGO '21)_ - MLIR 证明了多层 IR 组合式设计的可行性；KPerfIR 则把这种思想扩展到动态 profiling 语义，而不只是不变的编译表示。
- _Villa et al. (MICRO '19)_ - NVBit 在运行时对 Nvidia 二进制做 instrumentation，而 KPerfIR 在 compiler IR 上插桩，因此能保留循环、region 和跨后端可移植性信息。
- _Shah et al. (NeurIPS '24)_ - FlashAttention-3 展示了 warp specialization 与异步执行带来的复杂 kernel 行为，而 KPerfIR 提供的是分析并改进这类行为的工具基础设施。

## 我的笔记

<!-- 留空；由人工补充 -->
