---
title: "LAIKA: Machine Learning-Assisted In-Kernel APU Acceleration"
oneline: "LAIKA 把内核态 ML 从 PCIe dGPU 转向 APU iGPU，用三域共享内存和常驻内核去掉拷贝链路，显著降低延迟与功耗。"
authors:
  - "Haoming Zhuo"
  - "Dingding Li"
  - "Ronghua Lin"
  - "Yong Tang"
affiliations:
  - "School of Computer Science, South China Normal University, Guangzhou, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790181"
tags:
  - kernel
  - ml-systems
  - gpu
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

LAIKA 的核心判断是，内核态 ML 的瓶颈通常不在算力，而在数据搬运。它因此放弃通过 PCIe 把请求送到 dGPU，改用 APU 上的 iGPU，并结合三域共享内存、轻量级 HIP 代理和常驻 GPU kernel，把一次推理的控制与数据开销压到足够低；论文报告其相对 LAKE 风格的 dGPU 方案可将推理延迟最多降低 `9.7x`，同时显著减少系统功耗。

## 问题背景

这篇论文切入的是“learned OS policy”里一个很实际但常被略写的问题。调度、文件系统预取、I/O 管理等内核子系统，确实可以从 ML 决策里获益；但如果直接在 CPU 上做推理，代价并不小。SIMD/AVX 会带来更高的上下文切换成本，可能触发频率下降，而且在 Linux 内核里还会牵涉到 preemption 与 FPU 状态管理等稳定性问题。把模型放回用户态控制循环虽然更安全，却又会引入 syscall、上下文切换和数据搬运，尤其不适合每个事件都要快速决策的热路径。

最接近的前作 LAKE 试图借助 NVIDIA dGPU 解决这一点：内核通过用户态代理把请求转给 CUDA 运行时，再由 dGPU 执行推理。LAIKA 的关键实证发现是，这条链路的主要成本并不是 GPU 计算，而是来回传数据。在论文给出的 MLLB 分析中，kernel 到 user 的拷贝、跨 PCIe 的传输以及返回路径合起来占了端到端延迟的 `93%` 以上，真正的 dGPU kernel 只占总时间的 `7%`。这意味着 dGPU 只有在较大 batch 下才值得启动，通常要超过 `256`；而许多内核决策天生就是小批量，甚至是“一次事件一次推理”。所以真正的问题不是“怎样让内核能调用 GPU”，而是“怎样在不付出巨大往返 I/O 税的前提下，加速这些小批量、低延迟的内核推理”。

## 核心洞察

论文最重要的观点是：对这类工作负载来说，统一内存比峰值 FLOPs 更重要。APU 上的 iGPU 在原始算力上不如笔记本或桌面 dGPU，但它和 CPU 共享 DRAM，因此可以天然绕开 LAKE 那条最贵的三段式拷贝链。如果系统能把同一块内存同时暴露给内核、用户态和 iGPU，那么 dGPU 路径里最致命的成本就消失了。

不过，光有共享内存还不够，控制路径也必须重写。LAIKA 把系统拆成零拷贝的数据平面和轻量级的控制平面。由于 HIP 仍是用户态运行时，论文保留了一个很小的代理进程，但这个代理主要负责转发命令，而不是搬运 feature 数据。对最小的请求，LAIKA 进一步用常驻 GPU kernel 避免反复 launch。于是，iGPU 的胜利并不是“算得更快”，而是把“现在立刻做一个很小的推理”这件事做到了足够便宜，能进入内核热路径。

## 设计

LAIKA 主要由四个部分组成。`AProxy` 负责跨越特权边界。内核代码不能直接安全地调用 HIP，因此框架把请求发给一个最小化的用户态进程，由它翻译成标准的 AMD HIP runtime 调用。这里的目标不是绕过 ROCm，而是在不改 vendor driver 的前提下复用现有软件栈。

`AShm` 是整篇论文最核心的机制。系统在启动时通过 `dma_alloc_coherent` 预留一块物理连续内存，再把这块区域注册给 HIP，使同一批物理页同时映射到内核、用户态与 iGPU。feature 和结果都放在这个共享池里，于是数据交换从“复制字节”变成了“共享地址可见性”。

执行层则提供两种 iGPU 模式。Per-Launch 路径里，内核 dispatcher 把请求送到 `AProxy`，后者发起一次常规 GPU kernel launch；这个 kernel 直接在 `AShm` 中读取输入并写回结果。论文说这条控制路径的固定开销大约是 `10 us`，对不那么小的 batch 来说可以摊薄。对真正的低延迟场景，LAIKA 则使用 `APK`，也就是 APU Persistent Kernel。它常驻在 iGPU 上，持续轮询 `AShm` 里的任务队列，原地处理请求，并直接在共享内存中更新完成状态，从而消除了重复的 API remoting 与 kernel launch 开销。

由于没有一个后端在所有区间都最好，LAIKA 还加入了一个内核态 dispatcher 和轻量级 cost model。它会同时估计三条路径的延迟：CPU 本地执行、persistent-kernel iGPU 执行、以及 per-launch iGPU 执行。超小任务留在 CPU；小到中等 batch 走 `APK`；一旦 batch 大到 persistent kernel 内部同步代价开始主导，就切回 Per-Launch 路径。

## 实验评估

实验平台是 AMD Ryzen 7 8845HS APU 加 Radeon 780M iGPU，并拿 LAKE 在两张 NVIDIA dGPU 上作对比：RTX 4060 Laptop GPU 与 RTX 4090 desktop GPU。工作负载的选择也很贴题，覆盖了 LinnOS 风格的 I/O latency prediction、MLLB load balancing、KML 风格的 filesystem prefetching，以及 AES-GCM filesystem encryption，用来说明这套底座并不只适用于神经网络推理。

最直接的证据来自低 batch 延迟实验。对 MLLB，LAIKA 始终比优化过的 dGPU 基线快 `3x-5x`，并把“GPU 加速开始划算”的阈值从 `128` 降到 `32`。对 filesystem prefetching，论文报告 LAIKA 在 iGPU sweet spot 内相对 dGPU 最多可将延迟降低 `9.67x`。对 I/O latency prediction，结论更细腻一些：在基础模型上 LAIKA 占优，但当作者把网络深度提高到 `8.8x` 和 `16.5x` MACs 时，这个优势会明显缩小。这个结果很重要，因为它一方面支撑了论文主张，另一方面也准确暴露了边界条件：只要工作负载从 I/O 受限变成计算受限，dGPU 的原始吞吐又会重新变得关键。

系统级实验进一步强化了这个论点。在主机侧 DRAM contention 下，所有路径都会变慢，但 persistent-kernel iGPU 路径退化最轻；即使在 `100%` contention 下，LAIKA 在小 batch 时仍比 dGPU 快 `3.5x`（`7 us` 对 `26 us`），大 batch 时也仍快 `2.9x`（`26 us` 对 `83 us`）。功耗结果也很醒目。在周期性推理实验里，iGPU 的总系统功耗只有 dGPU 基线的 `28.9%-39.5%`，而真正可归因于推理本身的功耗仅为 dGPU 的 `6.8%-27.3%`。整体来看，这组实验很好地支持了论文的中心论点：对支配内核控制路径的小批量和中等批量请求，LAIKA 的确更合适；但它也同样清楚地表明，LAIKA 并不是所有场景下都能替代更强的离散 GPU。

## 创新性与影响

相对于 _Fingler et al. (ASPLOS '23)_，LAIKA 的新意并不只是“把 CUDA 换成 HIP”。真正关键的变化，是把内核态 ML 加速从远端内存的 dGPU 架构转向统一内存的 APU 架构，再围绕这个硬件选择重建软件栈，包括三域零拷贝共享与 persistent-kernel 快路径。相对于 _Chen et al. (APSys '20)_ 和 _Hao et al. (OSDI '20)_ 这类证明 learned kernel policy 有价值的工作，LAIKA 回答的是另一个此前没被彻底解决的问题：什么样的硬件与软件底座，才能让这些策略真的落进微秒级决策路径里。

因此，这篇论文对两类读者都很有价值。对研究 learned OS policy 的系统研究者来说，它提供了一个具体的部署答案；对内核和平台工程师来说，它则说明 APU 不只是“缩水版 GPU”，而是低延迟内核辅助计算的另一种设计点。

## 局限性

论文本身已经暴露出几个重要限制。第一，LAIKA 的优势强烈依赖工作负载特征：模型更深、batch 更大时，dGPU 会逐步占优，所以它最适合的仍是小批量、低延迟推理。第二，dispatcher 依赖针对特定 APU 和模型离线 profile 出来的阈值，这会带来可移植性和重新调参成本。第三，原型本质上是 AMD 专属的，因为它建立在 ROCm/HIP 以及 AMD 软件栈相对开放的现实上；论文讨论部分也明确指出，Intel 和 Apple 平台目前还没有同样成熟的内核集成条件。

此外还有一些评审式担忧。CPU 与 iGPU 共用 DRAM 通道，所以 memory contention 并不会消失，只是在论文测试里对 LAIKA 的影响比其他路径小。更重要的是，当前信任模型默认 `AProxy` 是可信的。作者承认，如果代理被攻破，就可能伪造推理结果或制造拒绝服务，因此更严格的校验、清洗以及 fail-safe 机制都被留到了未来工作。

## 相关工作

- _Fingler et al. (ASPLOS '23)_ — LAKE 证明了通过 API remoting 在 NVIDIA dGPU 上做内核态 ML 加速是可行的；LAIKA 保留这个思想，但通过统一内存 APU 去掉了 PCIe 拷贝链。
- _Chen et al. (APSys '20)_ — MLLB 展示了 learned load balancing 可以优于 Linux 的启发式调度；LAIKA 借这类工作负载说明，如今真正的瓶颈已经变成部署与执行开销。
- _Hao et al. (OSDI '20)_ — LinnOS 证明逐 I/O 的延迟预测有系统价值，而 LAIKA 贡献的是一条更低延迟的内核内执行底座，用来承载这类模型。
- _Akgun et al. (HotStorage '21)_ — KML 把内核内神经网络预测用于 filesystem readahead；LAIKA 与其关系是互补的，因为它加速的是推理执行路径，而不是提出新的 readahead 策略。

## 我的笔记

<!-- 留空；由人工补充 -->
