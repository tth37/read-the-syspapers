---
title: "ClubHeap: A High-Speed and Scalable Priority Queue for Programmable Packet Scheduling"
oneline: "ClubHeap 用簇化堆节点和全流水 PIFO 操作，把 replace 吞吐推进到每周期一次，同时保持队列深度、优先级范围和逻辑分区上的可扩展性。"
authors:
  - "Zhikang Chen"
  - "Haoyu Song"
  - "Zhiyu Zhang"
  - "Yang Xu"
  - "Bin Liu"
affiliations:
  - "Tsinghua University"
  - "Futurewei Technologies"
  - "Fudan University"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
code_url: "https://github.com/ClubHeap/ClubHeap"
tags:
  - networking
  - smartnic
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ClubHeap 是一种面向 PIFO packet scheduler 的 clustered binary heap。它通过“每个节点存多个有序元素”以及“把子簇最小值上提到父节点”这两个设计，消除了此前 heap-based PIFO 无法做到每周期一次 replace 的长依赖链；FPGA 原型达到约 200 Mpps，并同时支持大容量队列、宽优先级范围和多个 logical PIFO。

## 问题背景

可编程交换机和 SmartNIC 需要一种足够通用的队列抽象，来承载 WFQ、HPFQ、LSTF 等不同的 packet scheduling 算法。PIFO 之所以重要，是因为它允许元素按 rank 插入任意位置，但只从队首弹出，因此可以作为许多可编程调度器的统一基础。问题在于，真正可用的 PIFO queue 不只是“功能正确”，还必须同时满足三件事：吞吐高、能扩展到很多元素和很宽的优先级空间、还能把一个物理队列块分成多个 logical PIFO，供层次化调度树复用。

现有实现各自在这三点上都有短板。基于 shift register 或 systolic array 的线性结构，在小规模下可以很快，但它们需要并行比较大量元素，队列一大，硬件开销和时序都会迅速恶化。像 BBQ 这样的 bucket-based 设计能把元素容量做大，但它为每个优先级维护专门状态，因此一旦 rank 范围变宽、或者需要很多 logical PIFO，资源消耗就会失控。heap-based 设计理论上更均衡，却卡在 inter-operational data dependency 上：前一次 pop 之后，下一次 pop 取决于更深层哪个元素被提升到根，这迫使实现增加跨层 bypass 和更宽的组合比较逻辑，最终让 cycles-per-replace 始终高于理论下限 1。

## 核心洞察

这篇论文最关键的想法是：不要对“单个节点”做 heap ordering，而是对“簇”做 ordering。ClubHeap 让每个二叉树节点存放最多 `K` 个有序元素，而不是 1 个，并把 heap invariant 定义在整个 cluster 上。更重要的是，对于非根节点，其 cluster 中的最小元素并不保存在本节点，而是上提存放在父节点中。

这个变化正好切断了普通 heap 的长依赖链。一次 pop 之后，下一次候选最小值已经出现在当前层，因为父节点手里已经握有两个子簇的最小值。于是，连续操作不需要等“深层赢家”一路冒泡回根节点，而只是在一个 cluster 内消费不同元素。只要 `K >= 2`，ClubHeap 就能把操作按层流水化，并把通信限制在相邻层之间，从而在不牺牲 heap 可扩展性的前提下，把 CPR 推到 1。

## 设计

ClubHeap 本质上是一个 clustered binary heap。每个节点保存一个最多含 `K` 个元素的有序数组；空槽被视为 `+infinity`。它的 heap 条件写作 `E(x) <= E(y)`，含义是父 cluster 中任一元素都不大于子 cluster 中任一元素。由此带来一个很有用的推论：元素会自然集中在上层，因为只要某个节点还没装满，它的子节点就必须为空。这种“上层聚集”性质对 logical partitioning 很关键，因为多个 logical PIFO 可以共享深层存储，而不必给每个队列预留一棵完整二叉树。

三种基本操作都沿用了 heap 的直觉，但被重写成适合 cluster 的版本。Push 在根节点有空位时直接插入；若根已满，则把根 cluster 中 rank 最大的元素向下逐层驱逐。每个节点还存一个 subtree-size difference field，用于把新元素送往元素更少的子树，保证插入平衡。Pop 则移除根最小值，再把两个子簇最小值中较小的那个提升上来。Replace 是 scheduler 中最常见的操作，因为一个 flow 被调度后常常会带着新 rank 立刻重新入队；论文把它做成专门优化的 pop-push 组合。

真正让 ClubHeap 成立的是流水线架构。每一层上的每个操作依次经过 READ、CMP、WRITE 三个阶段，而且分布在不同周期里执行。不同操作可以在这三个阶段重叠，因此系统每个周期都能接收一个新操作。为此，作者把 sibling node 成对存储，使一次 memory access 就能读出下一层可能访问的两个候选节点。每个非叶子节点保存四类信息：本地有序 cluster、两个子簇的最小值、记录左右子树元素数差异的字段，以及在动态分配层中指向子节点存储位置的指针。

内存组织采用混合策略。浅层使用 static allocation，因为完整二叉树在这里成本还可接受；深层则使用带 free list 的 dynamic allocation，因为 ClubHeap 的节点聚集上界说明：在多 logical PIFO 共享时，真正被占用的节点数量可能远小于完整树。论文实现使用 919 行 Chisel，并把 `K`、容量 `N`、优先级范围 `P` 和 logical PIFO 数量 `M` 都做成参数。

## 实验评估

作者在 Xilinx Alveo U280 FPGA 上实现了 ClubHeap，并与 BMW-Tree 中的 RPU-BMW 和 BBQ 在同一 FPGA toolflow 下比较。最核心的结果是吞吐：ClubHeap 是第一种达到 CPR=1 的可扩展 heap-based PIFO queue，因此在与 BMW-Tree 接近的时钟频率下，它能提供大约 3 倍吞吐。对于最多 `2^17` 个元素的配置，FPGA 频率大约在 190 到 207 MHz 之间，折算成约 200 Mpps，足以支撑最坏情况下的 100 GbE line rate。

与 BBQ 的对比体现了论文为什么一直强调“可扩展性”而不是单个工作点。队列较小时，ClubHeap 与 BBQ 的吞吐接近；当规模增长到 `N = 2^17` 时，ClubHeap 在 `K=2` 和 `K=16` 下分别比 BBQ 快 63% 和 72%，同时还少用 33% 到 39% 的 BRAM。原因是 BBQ 的 bucket 表示法在状态增大后会越来越受内存访问延迟支配。

优先级范围实验也很有说服力。当 priority precision 从 `2^16` 增加到 `2^20` 时，ClubHeap 的时钟频率下降不到 3%；在 `P = 2^20` 时，其吞吐达到 BBQ 的 3.28 倍。更高的 `P` 下，BBQ 会因为 BRAM 耗尽而无法在目标 FPGA 上综合，而 ClubHeap 还能继续扩展到 `P = 2^32`，且频率只下降 5.5%。在 logical partitioning 方面，原型支持最多 `2^8` 个 logical PIFO；当 `M` 增长到 `2^8` 时，`K=2` 的设计频率只下降 16.7%，`K=16` 甚至没有频率下降。论文还给出 45nm ASIC 综合结果：在相同的 single-PIFO 规格下，ClubHeap 的面积只占 BBQ 的 17.7% 到 22.6%。

整体上，这套评估足以支撑论文的中心论点。作者把 PQ block 单独拎出来，选了合适的基线，并展示了 ClubHeap 是唯一一个能在吞吐、元素规模、优先级宽度和 logical partitioning 上同时保持竞争力的设计。

## 创新性与影响

相对 _Sivaraman et al. (SIGCOMM '16)_，这篇论文的创新不是提出新的 scheduling abstraction，而是为 PIFO 找到了一个新的实现点。相对 _Yao et al. (SIGCOMM '23)_，它的核心贡献是 clustered-heap 结构：通过消除 inter-operational dependency，把 replace 吞吐推进到理论下限每周期一次，同时还保留 logical partitioning。相对 _Atre et al. (NSDI '24)_，ClubHeap 放弃了 bucket 结构的简单性，换来在优先级精度和多队列共享上的显著可扩展性。

这使得它对实现可编程 traffic manager 的研究者和设备厂商都很重要。如果 PIFO 真要落地到交换机或 SmartNIC，底层数据结构既要快，也要足够省面积，才能被重复实例化很多次。ClubHeap 提供的是一个新的机制，而不是简单的 benchmark 改进，因此后续关于 programmable scheduling hardware、virtualized PIFO block、交换机和 NIC traffic manager 的工作，很可能都会引用它。

## 局限性

ClubHeap 改进的是 PIFO 的实现，而不是消除 PIFO 本身的边界。论文明确指出，它不能直接支持 PIEO、CIPO 之类扩展抽象，只能作为这些设计中的 PIFO 组件使用。同样，带有 dynamic rank 的算法仍然超出 plain PIFO 的表达能力。

评估也主要聚焦在 queue block，而不是完整 traffic manager。原型展示了综合结果、时序和模拟吞吐，但没有把 ClubHeap 真正集成进完整交换机 ASIC 或 SmartNIC scheduler，并讨论真实 control plane 集成成本。而且，虽然约 200 Mpps 已足以覆盖最坏情况下的 100 GbE，论文自己也指出高 radix 交换机仍需要一个由多个 PIFO queue 组成的 mesh，而不是单个实例。最后，参数 `K` 代表一个真实的工程权衡：更大的 cluster 能通过减少层数来提高频率，但也会增加 LUT、FF 和 BRAM 消耗。

## 相关工作

- _Sivaraman et al. (SIGCOMM '16)_ — PIFO 提出了可编程 packet scheduling 的抽象，而 ClubHeap 解决的是如何把这个抽象更高效地落到硬件上。
- _Bhagwan and Lin (INFOCOM '00)_ — `P-Heap` 展示了早期基于 heap 的 packet scheduling 方向，而 ClubHeap 用 clustered node 和面向 PIFO replace 的流水线重新推进了这条路线。
- _Yao et al. (SIGCOMM '23)_ — `BMW-Tree` 是可扩展的 heap-based PIFO queue，但它仍需要 CPR=3，且不像 ClubHeap 那样支持 logical partitioning。
- _Atre et al. (NSDI '24)_ — `BBQ` 是很强的 bucket-based integer priority queue，但它的资源成本会随着 priority range 和 logical partitioning 增长，而这正是 ClubHeap 拉开差距的地方。

## 我的笔记

<!-- 留空；由人工补充 -->
