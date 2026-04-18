---
title: "LithOS: An Operating System for Efficient Machine Learning on GPUs"
oneline: "LithOS 在 CUDA 驱动边界下方插入一层 GPU OS，通过 TPC 级调度、kernel atomization 和小幅 latency slip 换取更高利用率与更低能耗。"
authors:
  - "Patrick H. Coppock"
  - "Brian Zhang"
  - "Eliot H. Solomon"
  - "Vasilis Kypriotis"
  - "Leon Yang"
  - "Bikash Sharma"
  - "Dan Schatzberg"
  - "Todd C. Mowry"
  - "Dimitrios Skarlatos"
affiliations:
  - "Carnegie Mellon University"
  - "Meta"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764818"
tags:
  - scheduling
  - gpu
  - ml-systems
  - energy
category: gpu-and-accelerator-systems
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

LithOS 在 CUDA 之下插入一层接近操作系统的控制面，以 NVIDIA TPC 为资源粒度调度工作，并把长 kernel 透明切成更小的 atoms，让 latency-sensitive 与 best-effort 的 ML 任务能在同一块 GPU 上共享而不必依赖粗粒度分区。在 A100 上，它把 inference tail latency 相比 MPS 最多降低 13x，同时实现了平均约 26% 的 capacity savings 和平均约 26% 的 DVFS energy savings。

## 问题背景

这篇论文关心的不是单个 benchmark 的优化，而是 datacenter 里 GPU 长期利用不满的问题。作者基于 Meta 的生产分析发现，GPU device utilization 常在不到 25% 到高于 60% 之间波动，SM utilization 甚至可能低于 15%。小 batch、突发流量，以及模型规模和流行度差异，都让昂贵 GPU 在功耗和供给压力已经很高时仍留下大量闲置能力。

现有透明共享机制都在逼系统做糟糕的取舍。time slicing 和 TGS 这类 temporal 方案兼容性好，但并发不足；MPS 和 MIG 这类 spatial 方案允许重叠执行，却要么让 latency-sensitive 工作直接受干扰，要么因为 GPC 粒度过粗和重配置太慢而浪费容量。更麻烦的是，kernel 一旦进入驱动和硬件队列，软件几乎无法再重排、缩减资源或做细粒度省电控制。LithOS 因而主张，GPU 共享需要一个位于 framework 之下、vendor driver 之上的 OS 式控制点。

## 核心洞察

LithOS 最重要的判断是，透明 GPU OS 的正确调度单位是 TPC 和 atom，而不是整块 GPU 或整个 kernel。TPC 比 MIG 分区细得多，但又没有细到会破坏 compiler 和 SM 内部优化；atom 则是在运行时切出来的 thread block 子集，让系统即使没有真正的 hardware preemption，也能在长 kernel 中重新获得调度机会。

有了位于 CUDA Driver API 之下的 per-stream launch queue，LithOS 就能延后 dispatch，并把 TPC stealing、right-sizing 和 DVFS 放到同一个控制点上。论文真正的洞察因此不是单纯“调度更细”，而是“只要先把 kernel 拆成可调度 atoms，driver-level 的 OS 层就能统一处理共享、容量回收和省电控制”。

## 设计

LithOS 是一个用 Rust 写成的库，拦截 CUDA Driver API。每个 stream 都有自己的 launch queue，应用拿到 TPC quota，CPU 侧的 dispatcher 和 tracker 线程负责决定何时把工作送进硬件队列，以及何时回收完成工作的资源。TPC scheduler 可以把空闲 TPC 借给别的任务，但会配合在线 latency predictor、更低的硬件 stream priority 和 outstanding work 上限来约束 priority inversion。

真正的关键是 Kernel Atomizer。LithOS 修改 launch metadata，让执行先进入一个很小的 Prelude kernel。Prelude 检查当前 thread block 的全局 block index，只有落在指定区间时才跳回原始 kernel。通过重复发射同一个 kernel、但给不同且不重叠的 block index 区间，LithOS 就能在不改 source、PTX、compiler 或 framework 的前提下，把一个 kernel 切成多个 atoms。atom 大小由预测运行时间和约 250 到 500 微秒的目标 atom_duration 决定，因此系统能在 atom 边界重新分配 TPC 并减少 head-of-line blocking。

在这套控制面之上，LithOS 再叠加 right-sizing 和 DVFS。right-sizing 用 `l = m / t + b` 模型，根据 1 个 TPC 与 full-TPC 两个观测点加上 occupancy filter 来拟合 kernel 的扩展曲线，再在用户给定的 latency-slip 约束下选择最小 TPC 数。DVFS 则对一串 kernels 计算加权的频率敏感度，并选出仍满足同一 slip budget 的保守设备频率。两者都依赖同一个在线 predictor；它除了看 kernel function，还会利用 batch 内的 ordinal index 区分不同 layer 上复用的同一底层 kernel。

## 实验评估

原型主要在单机 A100 上评估，并与 NVIDIA 的 time slicing、MPS、priority、MIG，以及研究系统 TGS、REEF、Orion 对比。在 inference-only stacking 场景里，LithOS 是唯一一个同时做到 100% SLO attainment 和归一化 throughput 为 1.0 的系统。MPS 的 throughput 可达 1.11，但 SLO attainment 只有 45%；MIG 和 thread limits 通过把空闲能力锁死在分区内部来保护延迟。

tail latency 的结果进一步解释了这种差异。跨模型组合平均下来，LithOS 相比 MPS 最多改善 13x 的高优先级 tail latency，相比 Orion 约改善 4x，相比 TGS 也仍有约 1.2x 的优势。在 inference 加 training 的混部场景里，它把服务 tail latency 相比 MPS 降低 4.7x，相比最佳已有系统再降 1.18x，同时把 aggregate throughput 提升 1.35x。ablation 说明，TPC scheduling 能压制干扰，但真正把长 best-effort kernels 打碎、减少阻塞的是 Kernel Atomization。

效率结果同样有分量。把 latency slip 设为 1.1 时，right-sizing 最多节省 51% 的 GPU capacity，平均节省 26%，而平均 P99 增幅和 throughput 损失都只有约 4%。DVFS 则最多节省 46% 的 GPU energy，平均节省 26%，代价是平均约 7% 的 P99 增幅。这些结果基本支持论文的核心论点：透明、以 compute 为中心的 GPU OS 控制层，确实能同时提升利用率和能效。

## 创新性与影响

相对 TGS，LithOS 加入了真正的 TPC 粒度空间控制，而不只是主要依赖 temporal 共享。相对 REEF 和 Orion，它不依赖 framework 改造或重离线 profiling，而是在 driver 边界在线学习。论文真正的贡献因此是一套系统基座：atomization、TPC scheduling、right-sizing 和 DVFS 被统一成 OS 职责，而不是彼此割裂的 serving 技巧。

这个 framing 对系统研究者和硬件设计者都重要。LithOS 给出了一个具体的 GPU OS 雏形，同时也指出了今天硬件缺失的支持，例如显式 kernel-to-SM placement、更细的 preemption 和更快的 DVFS。

## 局限性

这个原型依赖 reverse-engineered 的 NVIDIA 内部细节，比如 QMD patching 和 TPC mapping，同时并发 context 仍建立在 MPS 之上。LithOS 也没有真正的 kernel preemption；atomization 只能在 atom 边界起作用，所以已经在跑的工作仍可能拖慢紧急请求。

实验大多集中在单机 A100，因此跨 GPU 代际的泛化更多是主张而不是充分验证。bandwidth isolation 基本不在系统范围内，作者也估计带宽争用重的组合上还可能再拿到 4% 到 13% 的收益。DVFS 是设备级且切换延迟约 50 ms，所以策略必须保守。最后，REEF 和 Orion 是按新软件栈重实现的，而不是直接运行原始 artifact，因此比较虽然认真，但并非完全 artifact-identical。

## 相关工作

- _Wu et al. (NSDI '23)_ — TGS 可以在容器间透明共享 GPU，但本质上仍以 temporal 共享为主，而 LithOS 把 temporal 控制与 TPC 粒度的 spatial scheduling 和 atomization 结合到一起。
- _Han et al. (OSDI '22)_ — REEF 为 DNN inference 提供微秒级 GPU preemption，而 LithOS 把目标进一步推广成面向未修改应用的 driver-level OS substrate。
- _Strati et al. (EuroSys '24)_ — Orion 依赖 interference-aware 的 GPU 共享、offline profiling 和应用侧配合；LithOS 则强调 framework 之下的透明性与在线学习。
- _Ng et al. (SOSP '23)_ — Paella 是面向低延迟模型服务的软件定义 GPU scheduler，而 LithOS 试图把问题扩展成同时负责硬件 right-sizing 与 power management 的 OS 式资源管理器。

## 我的笔记

<!-- 留空；由人工补充 -->
