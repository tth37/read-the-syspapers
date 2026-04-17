---
title: "Cheddar: A Swift Fully Homomorphic Encryption Library Designed for GPU Architectures"
oneline: "Cheddar 用 25-30 prime 的 32-bit RNS、GPU 定制模运算和大范围 kernel fusion 重做 CKKS，使 FHE 在单卡 GPU 上快得多。"
authors:
  - "Wonseok Choi"
  - "Jongmin Kim"
  - "Jung Ho Ahn"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762223"
tags:
  - security
  - gpu
  - compilers
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Cheddar 是一个面向 GPU 的 CKKS 全同态加密库，它没有沿用传统 FHE 库围绕 64-bit RNS 组织实现的路径，而是从 32-bit prime、数据布局和执行序列一起重做。论文的核心结论是：只做更快的单个 kernel 远远不够，只有把 25-30 prime 的 32-bit RNS、低层模运算优化以及大范围 kernel fusion 组合起来，才能把 GPU 上 FHE 的算力开销和内存流量同时压下去，最终在代表性 workload 上取得 `2.18-4.45x` 的端到端提升。

## 问题背景

论文讨论的是 FHE 落地时一个很现实的障碍。全同态加密允许云端直接在密文上计算，因此理论上可以同时得到外包计算和强隐私保护；但在 CKKS 这样的近似同态方案里，真正的执行路径充满了大模数多项式运算、basis conversion、rescaling、automorphism 和 bootstrapping，这些步骤让实际性能比明文计算慢出几个数量级。

GPU 看起来非常适合做这件事，因为 CKKS 的 RNS limb 和多项式系数层面都有大量并行性。但作者认为，之前的 GPU 实现仍然被两个问题卡住。第一，主流 FHE 软件体系默认使用 64-bit RNS prime，而 GPU 的整数 datapath 本质上是 32-bit；这意味着 64-bit 整数运算要靠 32-bit 指令去模拟，计算代价会很高。第二，就算改成 32-bit RNS，已有方案也不理想：有的会因为 terminal primes 的变化而需要为不同 level 准备很多 evaluation key，导致内存容量压力大；有的虽然避免了 key 膨胀，却引入不利于 GPU 并行的数据表示和控制流。

更麻烦的是带宽瓶颈。随着 BConv 和 NTT 这类重计算 kernel 被优化后，automorphism 与 element-wise 操作会逐渐变成主要瓶颈，而这些操作本身算术强度低、几乎完全受 DRAM 流量限制。传统 CKKS 执行序列还会在多个 kernel 之间来回搬运中间结果，并反复做 Montgomery form 的进入与退出。所以这篇论文真正要回答的问题不是“怎样把一个 kernel 写快”，而是“怎样把整个 CKKS 库的表示方式和执行顺序改造成真正适合 GPU 的样子”。

## 核心洞察

论文最重要的洞察是，GPU 友好的 FHE 不是单点优化问题，而是表示、布局和执行序列的协同设计问题。32-bit RNS 只有在三个条件同时成立时才真正有价值：它必须跨 level 保持 evaluation key 兼容，必须让不同 level 的多项式仍能连续存放在显存里，还不能把额外的特例逻辑塞进每个 kernel，破坏 GPU 的并行效率。同样，更快的模乘也只有在同时减少中间结果搬运时才会转化成真正的端到端收益。

Cheddar 的做法是把“32-bit 执行”当成一个全栈重构目标。25-30 prime system 用固定的 `Pr~25` 和 `Pr~30` prime 循环来实现 rational rescaling，使 CKKS 的 scale 可以稳定在 `2^40` 附近，同时保住单个 top-level evaluation key 的兼容性；inverted-terminal layout 则保证 level 变化后 limb 仍能连续放在内存中。建立在这个表示之上，Cheddar 再用 signed Montgomery reduction、按 GPU 架构调优的 BConv/NTT kernel，以及跨多个操作阶段的 fusion，把原本会消耗带宽的 Montgomery conversion 和临时结果写回尽量消掉。六个月后读者真正该记住的命题是：Cheddar 的提升不是“32-bit 更快”这么简单，而是“只有让 RNS 结构本身变得适合被 GPU 调度，32-bit 的优势才能完全兑现”。

## 设计

第一部分设计是新的 RNS 构造。对于非 bootstrapping level，Cheddar 采用一个固定的 rational-rescaling 周期：先丢掉三个 `Pr~30` 并加入两个 `Pr~25`，下一层再重复一次，然后再丢掉四个 `Pr~25` 并加回两个 `Pr~30`。这样可以把 scale 维持在 `2^40` 左右，同时把 terminal primes 限制在一个很小的固定集合里。和 BitPacker 这类按 level 贪心挑 prime 的做法不同，这种固定顺序让 top-level 准备好的 evaluation key 在较低 level 上仍可以通过截断继续使用，而不会因为 prime 集合变化而失配。

第二部分是数据布局。rational rescaling 的一个常见麻烦是，同一个逻辑 prime 在不同 level 里可能落在不同的物理位置上，导致索引计算、内存分配和跨 level 操作都变复杂。Cheddar 的 inverted-terminal layout 把 terminal `Pr~25` limb 按逆序放在前面，再把 `Pr~30` limb 放在后面。由于 prime 的加入和移除遵循上面固定的 cycle，不同 level 仍然能维持连续且对齐的显存布局，尤其简化了 rescaling 和 ModDown 之类跨 level 计算。

第三部分是低层 kernel。Cheddar 选择 signed Montgomery reduction，是因为在近期 GPU 上它比 Barrett reduction 和传统 Montgomery reduction 需要更少指令，而且每个 prime 只需一个预计算常数。BConv matrix multiplication 则利用 lazy reduction，把许多 modular reduction 延后执行，在不溢出 64-bit signed accumulator 的前提下减少大量额外计算。对于 NTT，作者扩展了已有的 on-the-fly twiddle generation，不再只是为某个阶段最后一级生成 twiddle，而是让整个 phase 都能动态生成，从而显著减少 twiddle 从内存加载的流量。所有这些 kernel 都被做成高度参数化的版本，再通过架构相关的 fine-tuner 为不同 GPU 寻找最佳配置。

第四部分是操作序列优化。顺序 fusion 会把常数乘法提前折叠进相邻的 INTT 和 BConv kernel，从而显式消掉进入或离开 Montgomery form 的成本，并进一步优化 rescaling 与 ModDown。论文还会把某些步骤拆分并重排，以暴露新的 fusion 机会。并行 fusion 则针对大量累加和 automorphism 序列，把原本需要多次读写中间结果的流程改成一次性在寄存器里合并，尤其适合 bootstrapping 与 encrypted DNN 中常见的 linear transform 模式。

实现层面，Cheddar 不是一个只跑 microbenchmark 的研究原型。论文把它描述为一个完整库：既有高层编程接口，也有 bootstrapping 和 DNN 模块、GPU memory-pool allocator，以及按架构自动调 kernel 参数的 fine-tuner。主库规模超过 `11,000` 行 C++/CUDA 代码。

## 实验评估

默认实验参数使用 `128-bit` 安全级别、`N = 2^16`、`PQ < 2^1776`、默认 `Delta = 2^40`，以及 `dnum = 4`。评测 workload 包括 full-slot bootstrapping、同态 logistic regression 训练、ResNet-20 在 CIFAR-10 上的加密推理，以及 sorting network。这个组合是合理的，因为它既覆盖密码学核心机制，也覆盖论文真正想证明的端到端应用场景。

最关键的对比是和先前 GPU 系统在同一硬件上的比较。在同一张 `A100 80GB` 上，Cheddar 把 WarpDrive 的 bootstrapping 延迟从 `121.0 ms` 降到 `40.0 ms`，即 `3.03x`；把 HELR 的单次迭代从 `113.0 ms` 降到 `51.9 ms`，即 `2.18x`；把 ResNet 推理从 `5.88 s` 降到 `1.32 s`，即 `4.45x`。论文更广义地报告，相比代表性的 GPU 实现，Cheddar 的 workload 提升范围达到 `2.18-19.6x`。在更新的 `RTX 5090` 上，bootstrapping 进一步降到 `22.1 ms`，HELR 为 `25.9 ms/it`，ResNet 推理为 `0.72 s`。

实验还有一个优点，是它把宏观性能提升和具体机制联系得比较清楚。使用 25-30 prime system 的 rational rescaling 后，相比手工调优的 double-rescaling 配置，effective level 最多增加五层，因此 workload 中 bootstrapping 的触发频率下降，整体再获得 `1.07-1.41x` 的收益。基本机制对比也说明，哪怕先把 prime-system 的优势拿掉，Cheddar 在 HMult、HRot 和 rescaling 上仍然能比开源 GPU 库快大约 `1.5-1.8x`。ablation study 同样很有说服力：只做 BConv/NTT 的 kernel 优化，整机 workload 提升只有 `5-7%`；顺序 fusion 额外带来 `18-22%`；并行 fusion 再带来 `12-23%`。这和论文主张是对得上的，即成熟的 GPU FHE 栈里，真正卡住性能的往往是数据搬运，而不只是整数乘法吞吐。

我认为这组实验对“单机 GPU 上的 CKKS 库应该怎样设计”这个中心论点支撑得比较强。不过它的外推边界也很明确：一些 workload 在小显存 GPU 上会直接 OoM，论文也没有讨论多 GPU、异构 CPU/GPU 或云端分布式部署。因此它证明的是“单卡可以做得非常好”，而不是“系统级部署问题已经解决”。

## 创新性与影响

和 _Samardzic and Sanchez (ASPLOS '24)_ 相比，Cheddar 的新意不只是“也用了 rational rescaling”，而是把它做成固定的 25-30 prime 调度，从而同时解决 evaluation-key 兼容性和 GPU 执行友好性。和 _Jung et al. (TCHES '21)_ 相比，它的贡献也不止于更快的 bootstrapping，而是把 fusion 和数据流优化扩展到了整个 CKKS 库的多个层次。和 _Fan et al. (HPCA '25)_ 相比，Cheddar 最核心的差异在于它把 RNS 结构、数据布局与执行序列一起重做，而不是只追求更快的数学 kernel。

因此，这篇论文对两类读者都很重要。对系统研究者来说，它说明 FHE 的性能瓶颈已经不是单个密码学算子，而是整个库级别的数据流组织。对做隐私保护机器学习、加密分析和实际 FHE 工程的团队来说，它则给出了一个很具体的结论：只要表示层和执行层设计得对，单张现代 GPU 已经能把不少 CKKS workload 推到可用区间。

## 局限性

Cheddar 仍然是一个高度专门化的实现。论文聚焦的是 CKKS，而不是更广泛的 FHE 方案；软件栈也明显围绕 NVIDIA GPU 组织，虽然文中拿它和 AMD MI100 上的定制加速器做了比较。与此同时，库对显存容量的要求并不低，因为 evaluation key、临时多项式和中间结果都很大，所以部分 workload 在 `16-24 GB` 设备上会直接失败。

它的最好结果还依赖仔细的参数选择和架构特定调优。更小的 scale 确实能带来额外性能收益，但论文同时展示，把 `Delta` 压到 `2^30` 会让 HELR 和 ResNet 的功能性明显失效，因此速度提升不是免费午餐。更广义地说，论文基本只研究单查询、单节点执行，没有分析这些优化在多租户调度、分布式 bootstrapping 或网络服务环境里的行为。

## 相关工作

- _Samardzic and Sanchez (ASPLOS '24)_ — BitPacker 说明 rational rescaling 可以带来更高算术效率，而 Cheddar 进一步把它改造成不会引起 evaluation-key 膨胀、也更适合 GPU 控制流的形式。
- _Jung et al. (TCHES '21)_ — 100x Faster Bootstrapping 率先强调 memory-centric bottleneck 并做了早期 fusion，Cheddar 则把这类优化推广到更多 CKKS 机制和更完整的库层实现。
- _Fan et al. (HPCA '25)_ — WarpDrive 同样在 GPU FHE 上做了强力优化，但 Cheddar 通过联合设计 RNS 构造、数据布局和 fusion 策略，报告了更好的端到端 workload 时间。
- _Kim et al. (ISCA '23)_ — SHARP 代表的是面向实用 FHE 的定制加速器路线，而 Cheddar 试图说明，仅靠商品 GPU 加上合适的软件和表示设计，也能追回其中很大一部分性能。

## 我的笔记

<!-- 留空；由人工补充 -->
