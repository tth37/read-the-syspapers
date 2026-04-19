---
title: "Pre-Stores: Proactive Software-guided Movement of Data Down the Memory Hierarchy"
oneline: "Pre-Stores 把脏数据下推也做成软件提示：DirtBuster 依访问模式选择 clean、demote 或跳过 cache，提前摊平写放大和 fence 前的停顿。"
authors:
  - "Xiaoxiang Wu"
  - "Baptiste Lepers"
  - "Willy Zwaenepoel"
affiliations:
  - "University of Sydney, Sydney, Australia"
  - "Inria, Grenoble, France"
  - "University of Neuchâtel, Neuchâtel, Switzerland"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696097"
tags:
  - memory
  - persistent-memory
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pre-Stores 的出发点很简单：既然 prefetch 能让软件主动把数据往上拉，写路径也该允许软件把脏数据提前往下推。作者没有发明新硬件，而是复用现成 cache-control 指令，再用 DirtBuster 判断哪里该用 `clean`、`demote`，哪里干脆该跳过 cache。论文在异构内存平台上报告了 TensorFlow 最高 47% 吞吐提升、NAS 最高 40% 运行时间下降，以及 X9 最高 62% 的消息延迟下降。

## 问题背景

这篇论文瞄准的是一个越来越常见的现实：CPU cache 下方不再只有一种 DRAM。Optane PMEM 有更大的内部写粒度，CXL 类设备和 cache-coherent accelerator memory 还有更长的可见性链路。作者认为，传统 cache 在这种环境里会把写密集程序拖进两个坑里。第一个坑是 eviction 顺序和程序写入顺序脱节。Machine A 上 CPU 以 64 B cache line 回写，而 Optane PMEM 内部按 256 B 写；一旦 cache 用 pseudo-random 的方式把 line 逐步赶出去，本来顺序的写流就会被打散，单线程写放大达到 180%，两线程及以上接近 330%。

第二个坑出现在 weak memory 与高延迟 coherent memory 上。CPU 往往会把最近的写先留在私有 buffer 或更私有的 cache 层，等 fence 或 atomic instruction 逼它们对别的核可见时，再一次性往外推。Machine B 的 Arm 加 FPGA 路径上，这个「到 fence 才公开」很贵，因为读回 cache line、更新 coherence 状态都要经过高延迟链路。论文里的 microbenchmark 显示，只要把这件事提前异步触发，性能最高能提升 65%。读路径已经有 prefetch；作者要补上的，是写路径对应的软件抽象。

## 核心洞察

作者真正想说的是：脏数据往下搬运这件事，不该只靠硬件在最坏时机被动触发，而应该被软件当成显式优化来安排。pre-store 可以理解成写路径版 prefetch，它要求处理器在后台把数据推进到更公开的 cache 层，或者朝 memory 提前推进。`clean` 适合把将来的 writeback 变得更顺序；`demote` 适合把本来会卡在 fence 或 atomic 前面的可见性工作提前消化掉。

关键是不能凭直觉乱插。后面会不会 reread、会不会 rewritten、离下一个 fence 有多近，这些都会改变最佳动作。如果数据还要 reread，就该尽早回写但继续留在 cache；如果很快会 rewritten，就不该把它急着赶去 memory；如果后续根本不会再碰，那跳过 cache 反而更对。DirtBuster 的价值，就是把这件事变成一个针对 binary 和 library 的 profile-guided 决策问题，而不是让开发者肉眼猜热点。

## 设计

论文暴露的接口很简单：`prestore(location, size, op)`。其中 `clean` 会非阻塞地把脏 cache line 往 memory 回写，但不会把数据从 cache 里驱逐；`demote` 则把数据往更公开的层级下推，比如从私有 buffer 或 L1 推向更全局可见的 cache。x86 上作者用到 `clwb`、`cldemote`，Arm 上则依赖 `dc cvau` 这类 cache-maintenance 指令。若一块数据之后既不会 reread 也不会 rewritten，论文把 non-temporal store 视为第三种选择，也就是直接绕过 cache。

DirtBuster 分三步做判断。第一步用 `perf` 采样定位 write-intensive function 和调用链，开销不到 1%。第二步用 Intel PIN 记录这些区域里的所有 read、write 和带 fence 语义的指令，恢复 sequential-write context，并计算写入到下一个 fence 或 atomic 之间的距离。第三步再按 cache line 统计 re-read distance 与 re-write distance。决策规则也很清楚：会 rewritten 且要赶在 fence 前公开的数据，更适合 `demote`；会 reread 的数据适合 `clean`；既不会 reread 也不会 rewritten 的数据最适合 non-temporal store。代价同样明确，这套流程是离线且侵入式的，PIN 阶段最高会带来 25x slowdown，最后还得开发者手工改代码。

## 实验评估

实验刻意围绕两类病灶来做。Machine A 是 Xeon Gold 6230，加 128 GB DRAM 和 8 x 128 GB Optane PMEM，重点观察 64 B cache line 对 256 B PMEM 写粒度时的写放大。Machine B 是 Enzian：48 核 Arm ThunderX-1 加 cache-coherent FPGA，FPGA 分别被配置成 60 cycle、10 GB/s 的快设备和 200 cycle、1.5 GB/s 的慢设备，重点观察昂贵 coherent 路径下的可见性延迟。

TensorFlow 的例子最能说明 DirtBuster 有没有找对点。工具把热点锁定到一个 Eigen loop；只加一行 `clean`，训练吞吐最高提升 47%，写放大从 3.7x 降到 2.7x。NAS 里的 MG、FT、SP、UA 和 BT 按建议补丁后，运行时间最高下降 40%。YCSB-A 上收益更大，但也更能体现选择的重要性：当 DirtBuster 建议跳过 cache 时，CLHT 吞吐最高到基线的 2.9x，Masstree 最高到 2.5x；如果只做改动更小的一行 `clean`，CLHT 仍有最高 2.3x，Masstree 最高 1.9x。到了 Machine B，`clean` 的意义不再是改善顺序性，而是把可见性工作提前重叠掉：1 KB value 下 CLHT 提升 52%，Masstree 提升 25%。X9 则是 `demote` 更合适，因为消息结构会反复复用；结果发送延迟在快 FPGA 配置下降 62%，在慢 FPGA 配置下降 40%。

这些结果和论文主张基本对得上。作者没有把所有程序都硬塞进 pre-store 模型里：read-mostly 的 YCSB B-D 根本不补丁；在 Machine B 上，TensorFlow 和 NAS 没有对应病灶，因此 pre-store 也几乎不带来收益；对 DirtBuster 认可的位置，即便目标架构上不吃这套，额外开销也最多 0.3%。所以这更像一篇说服力很强的机制论文，而不是一次大而全的系统横评。

## 创新性与影响

这篇论文的新意不在于新增一条 ISA 指令，而在于重新定义现有 cache-control instruction 的用途。过去很多工作把 `clwb` 之类的指令当成持久化正确性工具；Pre-Stores 则把它们提升成异构内存写路径里的通用性能提示，再配上 DirtBuster 这样一条能落地的分析链路。这个 framing 不只服务于 Optane。只要 cache 下方的介质存在写粒度不匹配，或者让写入变成全局可见的代价特别高，这套思路就可能成立，尤其是面向 PMEM-like tier、coherent accelerator memory 和未来的 CXL-attached memory。

## 局限性

Pre-Stores 的适用面并不宽。工作负载必须足够写密集，而且这些写最好要么构成长顺序流，要么离 fence 和 atomic 足够近，才有机会把收益做出来。read-heavy workload 没收益，论文已经直接展示了这一点。更现实的问题是误用代价不小：一个反复重写同一 cache line 的 microbenchmark 因为多余 `clean` 直接慢了 75x，NAS FT 里手工插错 pre-store 也会有 3x slowdown。

落地边界同样明显。DirtBuster 是离线、侵入式、而且架构敏感的工具；最优补丁有时不是加一行 pre-store，而是要把代码改成架构相关的 non-temporal store。再加上评测只覆盖两类机器和一组选定的写密集应用，这篇论文证明的是这个想法确实有效，而不是它已经变成通用、自动、可移植的优化套路。

## 相关工作

- _Shin et al. (ISCA '17)_ - 用推测执行去掩盖 PMEM persist barrier 的延迟；Pre-Stores 则把同类指令当成更一般的写路径性能提示。
- _Wu et al. (PACT '20)_ - Ribbon 关注 persistent memory 上 cache-line flush 的效率；Pre-Stores 把目标扩展到写放大和 fence 前的可见性延迟。
- _Khan et al. (HPCA '14)_ - read/write cache partitioning 调整的是 cache 空间如何分配；Pre-Stores 调整的是脏数据何时被向下推进。
- _Lepers and Zwaenepoel (OSDI '23)_ - Johnny Cache 通过重排数据放置提升 tiered memory 里的顺序性；Pre-Stores 不改数据结构，而是在具体写入点插入提示。

## 我的笔记

<!-- 留空；由人工补充 -->
