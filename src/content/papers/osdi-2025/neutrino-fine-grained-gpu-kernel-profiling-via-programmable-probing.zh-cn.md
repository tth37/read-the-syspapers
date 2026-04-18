---
title: "NEUTRINO: Fine-grained GPU Kernel Profiling via Programmable Probing"
oneline: "NEUTRINO 在 GPU kernel 汇编层注入可编程 probe，以较低轻量探针开销恢复指令级时间线与内存访问轨迹，并覆盖多厂商软件栈。"
authors:
  - "Songlin Huang"
  - "Chenshu Wu"
affiliations:
  - "The University of Hong Kong"
conference: osdi-2025
code_url: "https://github.com/open-neutrino/neutrino"
tags:
  - gpu
  - observability
  - compilers
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

NEUTRINO 把 GPU kernel profiling 变成“可编程的汇编层探针”。它把小型 snippet 插到指令级 tracepoint 上，把结果写入结构化 map，再重建像 Densified Memory Access Timeline（DMAT）这样的 trace。轻量探针平均只有约 1.04x slowdown，却已经能看见 kernel-level profiler 常常掩盖的调度、同步和内存访问细节。

## 问题背景

现有 GPU profiling 工具普遍看不见细粒度 runtime 行为。硬件 profiler 依赖厂商 counter 和 PC sampling，所以更擅长总结整个 kernel，而不是解释到底是哪条指令、哪个 warp、哪个 block 导致了 slowdown。框架 profiler 站得更高，只会给出整段 kernel 的时间或吞吐，把内部执行过程当成黑盒。compiler instrumentation 和 binary instrumentation 工具虽然存在，但通常绑定某个 compiler 或某个厂商。这个缺口在现代 AI kernel 中尤其突出，因为真正决定性能的往往是 block scheduling、同步、memory coalescing 以及线程间重叠。

CPU 侧操作系统的成熟 tracing 技术也没法直接搬过来。GPU kernel 对 host OS 几乎是原子的，GPU 也没有传统 OS profiler 依赖的 timer interrupt 模型。于是论文要解决的问题很明确：做一个更像 GPU 版 eBPF 的接口，让用户能在运行时以指令粒度插入 probe，同时记录 timestamp 和 value，而不需要改源码。

## 核心洞察

论文的核心判断是：最合适的 probing substrate 不是 machine code，也不是更高层的 compiler IR，而是 GPU 汇编层。汇编足够低，能直接暴露 profiling 真正关心的 memory instruction、时钟寄存器等硬件相关操作；但它又足够通用，因为它正好是 AOT 的 CUDA 库和 JIT 的 Triton 这类系统共享的交汇层。因此，这一层既能覆盖手写 kernel，也能覆盖自动生成的 kernel。

第二个洞察是，可编程 probe 只有在“能协作但不破坏原程序”时才真正有价值。NEUTRINO 用一个虚拟化执行模型解决这个问题：probe 使用逻辑上独立的寄存器，保持原控制流，并通过结构化 map 持久化结果。这样同一套机制就能同时支持 value trace 和 time trace，同时尽量保持对真实执行过程的贴近。

## 设计

NEUTRINO 的 probe 模型由三部分组成：`snippet`、`tracepoint` 和 `structured map`。snippet 是插入的汇编片段；tracepoint 描述插入位置，可以是某条指令前后，也可以是 kernel 入口或出口；map 负责按 thread 或 warp 预分配存储，因此既能减少 metadata，又能避免 race。verifier 明确禁止三类危险行为：覆盖原寄存器、改变控制流、使用 shared memory。

实现上，系统有三个主要模块。hook driver 拦截用户态 CUDA/HIP driver API，跟踪加载的 binary 和启动的 kernel，分配 probe buffer，并替换为 instrumented kernel。probe engine 负责反汇编目标 kernel、匹配 tracepoint、填入地址和时钟等 helper operand、插入 snippet，然后重新汇编。最上层还有一个可选的 Python DSL，能编译成 PTX 或 GCN assembly。论文提出的 DMAT 就建立在这些 trace 之上，它在 page reference map 的基础上加入 physical time 和 access density 两个维度，因此既能看访问位置，也能看访问时序与并行强度。

## 实验评估

实验在 A100 和 RTX4090 上验证 correctness、overhead 和 usefulness。probed kernel 与原始 kernel 的输出一致；和 Nsight Compute 重叠的指标也能对齐。对于 DMAT，作者用已知访问模式的 microbenchmark 验证，得到零地址序列误差，以及低于 200 cycles 的平均时间误差，不到 loop 时间的 7%。这不是完美重建，但足以说明探针主要抓到的是目标事件，而不是纯粹扰动。

overhead 结果支持论文主张，但前提必须说清楚。轻量探针，例如 `block_sched`、`gmem_bytes`、`tensorop_count`，平均 slowdown 约 1.04x，额外寄存器约 3.78 个；重型 DMAT tracing 的平均 slowdown 则达到 7.12x。也就是说，NEUTRINO 对窄而精的 probe 确实轻量，但并不适合廉价地持续记录所有内存访问。最有说服力的是 debugging 场景：在 `torch.zeros` 例子中，`block_sched` 显示约 20% 的时间花在 block scheduling 上；把实现改成 memset 或 persistent kernel 后，延迟从 34,493 ns 降到 24,630 ns 或 24,891 ns，提升约 28%。FlashAttention-v2 的 case study 也很强，它揭示了 shared-block 配置中的同步诱发 tailing effect，尾部延迟最多增加 24.69%，而类似现象在 GEMM 中也能看到。

## 创新性与影响

这篇论文的主要贡献是一个新机制，而不只是一些新测量结果。NEUTRINO 把 runtime GPU profiling 变成汇编层上的可编程 substrate，并补齐了 verifier、持久化、DSL 和可视化。相比固定功能的 vendor profiler，用户可以把 probe 放到自己真正关心的位置；相比 compiler-specific instrumentation，它又能跨越 AOT 和 JIT 两类 GPU 软件栈。这让它对 kernel 开发者、ML systems 工程师和 compiler 研究者都有潜在价值。

## 局限性

汇编层 probing 不可能看到全部真相。它无法直接观察 cache miss 这类不可编程的硬件事件，因此某些问题仍然需要厂商 profiler 配合确认。verifier 也不完整，而且偏保守；当前 runtime 还是 process-local 的，并且会阻塞到 kernel 结束。更重要的是，论文虽然实现了 NVIDIA 和 AMD 支持，但主体实验几乎都在 NVIDIA 上完成，所以跨厂商可移植性的实验验证仍然不充分。再加上 DMAT 开销明显偏高，这套系统更适合按需深入诊断，而不是默认常驻。

## 相关工作

- _Villa et al. (MICRO '19)_ - NVBit 在 NVIDIA machine code 上做运行时 instrumentation，而 NEUTRINO 上移到 assembly 层，面向多厂商软件栈，并支持通过结构化持久化协作的 probes。
- _Braun and Froning (PMBS '19)_ - CUDAFlux 提供了面向 CUDA 应用的轻量级指令 profiling，而 NEUTRINO 追求的是通用、可编程的 tracing interface，而不是单一用途 profiler。
- _Skaletsky et al. (ISPASS '22)_ - GTPin 为 Intel GPU 提供灵活的 binary instrumentation，而 NEUTRINO 更强调在当前 CUDA/ROCm 生态共享的 assembly 层上做运行时 probing。
- _Diamos et al. (PACT '10)_ - Ocelot 证明了 PTX 可以作为有价值的系统接口，但它并不是一个面向生产 GPU kernel 的 eBPF 风格 runtime observability substrate。

## 我的笔记

<!-- 留空；由人工补充 -->
