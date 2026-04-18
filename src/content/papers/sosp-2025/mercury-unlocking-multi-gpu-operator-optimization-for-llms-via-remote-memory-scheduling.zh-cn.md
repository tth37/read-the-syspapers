---
title: "Mercury: Unlocking Multi-GPU Operator Optimization for LLMs via Remote Memory Scheduling"
oneline: "Mercury 把 remote GPU memory 当成可调度的存储层，再搜索 shift、shard 与 collective 组合，自动生成更快的多 GPU LLM 算子。"
authors:
  - "Yue Guan"
  - "Xinwei Qiang"
  - "Zaifeng Pan"
  - "Daniels Johnson"
  - "Yuanwei Fang"
  - "Keren Zhou"
  - "Yuke Wang"
  - "Wanlu Li"
  - "Yufei Ding"
  - "Adnan Aziz"
affiliations:
  - "University of California, San Diego"
  - "Meta"
  - "George Mason University"
  - "OpenAI"
  - "Rice University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764798"
code_url: "https://github.com/ChandlerGuan/mercury_artifact"
tags:
  - gpu
  - compilers
  - memory
  - llm-training
  - llm-inference
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mercury 是一个面向 LLM attention 与 GEMM 的多 GPU 算子编译器。它把 remote GPU memory 视为可以显式调度的存储层，而不是通信的副产物，再在统一的 CommIR 中同时搜索 shift、shard、replicate 与 collective 方案，因此既能复现 RingAttention、Ulysses、USP 这类人工设计，也能找到更好的组合。

## 问题背景

论文首先指出，LLM 的关键算子已经很难由单卡独立承载。长上下文 attention 会消耗数百 GB 内存，文中引用的数据是 Llama-3 70B 的 KV cache 就需要 282 GB，远超一张 H100 的 80 GB HBM。多 GPU 不再只是性能优化，而是训练和推理大模型的基本前提。

麻烦在于，当前最好的多 GPU 算子实现大多是手工写出来的，并且强依赖具体配置。模型的 head 数、上下文长度、GPU 数量、节点内外带宽结构，都会改变最佳设计。过去两年里，仅 attention 和 linear 两类算子就出现了二十多篇手调方案，足以说明这个空间既重要又难以人工穷举。

现有编译器之所以跟不上，关键是它们默认“local-memory-centric”的执行模型。也就是说，编译器先假定每张 GPU 必须把需要的数据都准备到本地 HBM，之后才开始计算；跨设备通信主要负责交换中间结果，而不是把远端显存当成输入数据的共享来源。这个假设自然导向同步执行、共享输入复制和更高的本地显存占用，也让编译器很难探索更激进的计算通信重叠。于是像 RingAttention 这类异步 shift 方案虽然有效，却只能以 ad hoc 形式存在，很难进入通用编译框架。

## 核心洞察

Mercury 的核心命题是：remote GPU memory 应该被看作 memory hierarchy 的一层，而不是外部传输通道。一旦编译器能把别的 GPU 显存当成可调度存储，它就可以有意识地错开不同 worker 访问共享数据的时间，让更多数据停留在聚合后的远端显存池中，只在需要时传到本地，从而在存储、通信和局部性之间做统一权衡。

这个视角变化的价值在于，它把以往割裂的几个问题放到同一个表示里。一个 loop schedule 不仅决定“谁算哪一部分”，还同时决定 buffer 是该 shard 还是 replicate、访问是同步还是 shift，以及这些访问在 lowering 后该变成 point-to-point 还是 collective。论文真正强调的不是某个单独技巧，而是只有当 compute、memory 和 communication 在同一个 IR 中共同出现时，编译器才有可能既覆盖已有专家方案，又找到人手难以直接构造的新方案。

## 设计

Mercury 的核心表示叫 CommIR。它保留 loop-based IR 的传统计算变换，如 `tile`、`join`、`reorder`、`patch`，同时加入四个通信相关原语：`parallelize`、`shift`、`shard` 和 `replicate`。`parallelize` 把某个循环映射到硬件 mesh 的某一层，并配套一个默认放置规则：被该循环索引到的 buffer 默认按该轴切分，其他 buffer 默认复制。`shift` 则把本地循环按并行循环做偏移，把同步访问改写成错时访问，从而引入显式的 remote-memory access。多层 `shift` 可以同时编码节点内和节点间的不同通信层级。`shard` 与 `replicate` 负责明确标注 buffer 布局，之后 lowering 会根据访问模式和规约语义自动推导出 `AllGather`、`Broadcast`、`AllReduce`、`ReduceScatter`，或者在无法匹配 collective 时退回到点对点发送接收。

整体流程是 DSL 到 CommIR 到搜索再到 lowering。用户先用类 Python DSL 描述算子，Mercury 解析为 CommIR；随后先生成 computation schedule，再生成 communication schedule；本地计算部分主要 lower 到 TorchInductor，并可通过 `patch` 用 FlashAttention 之类高性能内核替换局部子图。搜索阶段会先静态检查每个候选方案的每卡显存占用，超出容量的直接裁掉，其余候选再在真实硬件上 profile。论文报告其评测中每个算子的自动搜索大约需要 10 分钟。除此之外，Mercury 还在 operator DAG 上做 graph-level search，把算子本身的执行时间和算子之间的 resharding 代价一起优化，而不是每个 operator 各自选局部最优。

## 实验评估

实验平台覆盖 H100、A100 和 L4，节点内使用 NVLink 或 PCIe，节点间通过 RoCE 互联。实现基于 CUDA 12.6、NCCL 2.26.2 和 PyTorch 2.8 中的 TorchInductor。工作负载选择与 Llama-3 规格匹配的 attention 与 GEMM，包括 MHA、GQA、AllGather-GEMM 和 GEMM-ReduceScatter，batch size 为 1 到 16，序列长度从 4K 扩展到 2M。基线也比较扎实：RingAttention、DeepSpeed-Ulysses、USP、AsyncTP、cuBLAS collective 实现，以及 TorchInductor 自带的多 GPU 模板。

最重要的结果是稳定性和普适性。论文报告的每一个 operator benchmark 里，Mercury 都是最快的。对 attention 而言，它在 H100 的 MHA、batch size 16 上可达到 4x speedup；在 MHA 和 GQA 上都超过 Ulysses 与 USP，尤其是在 head 结构或拓扑结构不适合固定模板时优势更明显。对 GEMM 而言，虽然设计空间更规则、提升幅度更小，但 Mercury 仍然在 A100 的 AllGather-GEMM、batch size 16 上实现了最高 1.9x speedup，主要原因是它能把 collective 拆成更细粒度的重叠调度。

论文还专门验证了“拓扑自适应搜索”是否真的重要。在不同的 4 GPU、8 GPU、16 GPU 布局上，Mercury 平均带来 2.91x speedup，而且在 2x4、4x2 这类层次混合拓扑上优势最强，因为人工写死的单一模式很难同时兼顾节点内外带宽差异。长上下文实验也支持论文的核心论点：随着序列长度提升到 2M token，Mercury 仍然保持领先，并且是唯一还能生成可行计划的方法，其他基线在 2M 时都会 OOM。模型层面上，论文对 Llama-3 的一个 Transformer layer 做 graph-aware 优化，与最佳 3D parallel 基线相比可取得最高 1.62x 的性能提升，收益不仅来自单算子更快，也来自 resharding 开销更低。整体来看，实验确实说明 remote-memory-aware schedule 在高内存压力和复杂拓扑下最有价值。

## 创新性与影响

Mercury 的新意不只是“把 autotuning 做得更大”。它提供了一种新的多 GPU 算子编译抽象，让异步 remote-memory access、collective synthesis 和本地张量调度进入同一个搜索空间。因此，这篇论文更像是在补一层系统基础设施，而不是再加几个模板。对分布式 LLM runtime 或训练系统的研究者来说，它传达的现实启发是：下一阶段的性能提升，很可能来自编译器对混合 memory-and-communication schedule 的系统支持，而不只是继续手写某一种特殊拓扑下的 attention kernel。

## 局限性

这篇论文的搜索是硬件在环的经验式搜索，因此编译开销并不低。对论文中的工作负载来说，单算子 10 分钟还可以接受，但作者也明确承认，更复杂的算子和更大的 mesh 会继续抬高搜索成本。当前系统也主要针对静态算子；ragged tensor、MoE routing，以及更深度融合的 compute-communication kernel 都被留到了未来工作。

此外，Mercury 采用自己的 DSL，并主要通过 TorchInductor 和少量 patch 过的高性能内核完成 lowering，因此要迁移到其他编译器栈，还需要额外工程工作。最后，模型层评测只覆盖了一个 Transformer layer，而不是完整端到端训练或 serving 流程；这足以展示 resharding 优化的意义，但仍留下了一些完整系统层面的问题。

## 相关工作

- _Liu et al. (ICLR '24)_ - RingAttention 用 shift 设计支撑长上下文 attention，但它固定采用统一逻辑 ring，而不是像 Mercury 那样搜索面向层次拓扑的多级 shift。
- _Jangda et al. (ASPLOS '22)_ - CoCoNet 试图打破计算与通信的抽象边界，但它的搜索空间仍以同步 collective 为主，没有把异步 remote-memory schedule 当成一等公民。
- _Zheng et al. (OSDI '22)_ - Alpa 自动化了 inter-operator 与 intra-operator parallelism，但它主要依赖模板化分解；Mercury 则进一步在算子内部搜索更底层的调度和 remote-memory 放置策略。
- _Chen et al. (ASPLOS '24)_ - Centauri 聚焦于大模型训练中的通信计算重叠，而 Mercury 的贡献是一个更通用的 loop IR，可同时综合 collective 与 point-to-point 的 attention、GEMM 调度。

## 我的笔记

<!-- 留空；由人工补充 -->
