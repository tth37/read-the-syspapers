---
title: "Scalable Address Spaces using Concurrent Interval Skiplist"
oneline: "论文用 concurrent interval skiplist、per-core arena 与混合全局/局部锁重做地址空间管理，让 `mmap()` 和 `munmap()` 不再被 `mmap_lock` 串行化。"
authors:
  - "Tae Woo Kim"
  - "Youngjin Kwon"
  - "Jeehoon Kang"
affiliations:
  - "KAIST"
  - "KAIST / FuriosaAI"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764807"
code_url: "https://github.com/kaist-cp/interval-vm.git"
tags:
  - kernel
  - memory
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文认为，现代内核地址空间里最核心的瓶颈已经不再是 page fault 查表，而是 `mmap()` 分配和 `munmap()`/`mprotect()` 修改仍被粗粒度锁串行化。作者提出的解法是 concurrent interval skiplist：把区间映射和区间加锁合到同一个数据结构里，再配合 hybrid global/local locking、per-core arena 与可扩展计数器重做 Linux 6.8 的地址空间路径。最终，这套设计把 `mmap()` 微基准吞吐提升到最高 `13.1x`，并在 Apache、LevelDB、Metis 与 Psearchy 上都取得了明确收益。

## 问题背景

论文从一个老问题切入，但强调它在今天变得更严重了。内核通常用一个粗粒度读写锁保护整个进程地址空间，例如 Linux 的 `mmap_lock`。这种做法允许很多 Fault 并行执行，却会把现代多核软件最常见的两类操作串行化：一类是给 allocator arena 或 file-backed region 建立新映射，另一类是在工作结束后修改或回收映射。作者在双路 48 核机器上测得，Linux 6.8 下 Apache 最多约有 `90%` 的时间、Metis 有 `60%`、Psearchy 有 `41%`、LevelDB 有 `40%` 都耗在等待 `mmap_lock` 上。

问题不只是“一把大锁太粗”。地址空间操作真正需要同步的范围取决于当前映射状态，而不是用户传入的区间本身。一次 `munmap()` 可能还要锁住相邻 gap，才能安全释放已经空掉的 page table；一次修改也可能跨越多个不与 VMA 边界对齐的映射。与此同时，Fault 路径又必须保持 RCU-safe，才能继续无锁遍历；`fork()`、`exit()` 这类 whole-space 操作仍然需要全局协调；而 `mmap()` 自己的 first-fit 分配策略也会让所有线程从同一位置开始争抢。论文的判断是，只有把这些问题一起解决，地址空间才会真正扩展。

## 核心洞察

作者最重要的主张是：地址空间元数据和地址空间锁不应该是两个分离的机制，而应该共同存在于同一个 interval data structure 里。若系统先遍历地址空间决定“该锁哪里”，再单独去加锁，那么在两步之间并发更新就可能让原先判断失效，最终要么反复重试，要么退回粗粒度全局锁。只有当 interval map 自己就支持“找到与目标区间相关的节点并把它们锁住”这一原语时，内核才有机会在不丢正确性的前提下并行执行非重叠操作。

这条观察还带出另一层更广义的结论：拿掉粗粒度锁以后，先前被它遮住的其他瓶颈会全部浮现。因此，论文并没有把 concurrent interval skiplist 当成孤立数据结构来卖，而是把它和另外三件事绑定在一起：用于 whole-address-space 操作的 hybrid global/local lock、用于可扩展 `mmap()` 放置的 per-core arena 布局，以及既可扩展又能严格守住资源上限的 adaptive per-core counter。真正的新设计是这一整套配合关系，而不是单个结构。

## 设计

concurrent interval skiplist 对 interval map 提供 `Query`、`Lock`、`Unlock` 和 `Swap` 等原语。它在最底层像一个 concurrent linked list，但上层加入 skip link，以维持对数级搜索复杂度。关键机制是 node-granular interval locking：系统锁住的并不只是与目标区间直接重叠的节点，还包括 predecessor 节点以及相关 gap，因为这些位置决定了另一个线程能否在更新过程中插入、切分或重新填充该区域。更新则采用 read-copy-update 方式提交：先离线构造新节点，再原子改写 predecessor 指针指向新节点，最后才把旧节点标记为失效。这样 `Query` 仍能保持 lock-free traversal，而多节点区间替换又能作为一个原子操作出现。

建立在这个结构之上的 Linux 设计采用两级锁。每个 core 持有一个可工作在 global-read、global-write、local-read、local-write 四种模式下的锁。局部操作只获取当前运行 core 的锁，再配合 skiplist 内部的 interval lock；全局操作则获取所有 per-core lock，这比给大地址空间中的每个 mapping 分别上锁便宜得多。Fault 处理也分级进行：先尝试完全不加地址空间锁；若需要分配 page table 或更新 VMA 元数据，则退到 local-read 加 interval lock；只有在少数未适配的 file-backed 场景里，才回退到 global-read。Modify 路径同理，默认走 local-write 加 interval lock，只有必要时才退到 global-write。

为了让 `mmap()` 真正扩展，论文又补了两项设计。第一，把一部分虚拟地址空间切成 64 GiB 的 per-core arena，这样并发分配不会都去争抢同一个“第一个可用空洞”。第二，用 separator node 和分层高度组织 skiplist：高层主要负责在 arena 之间路由，低层主要在同一 arena 内遍历，从而减少跨 arena 插入时的相互干扰。每个 arena 还维护一个 hint，通常指向上一次成功分配的位置；执行 `munmap()` 后，hint 会向后移动，以便优先复用刚刚释放的区域。最后，资源计数采用 adaptive per-core counter：平时先在本地缓冲，只有当全局计数离上限太近时，才切换为直接更新全局计数，从而同时兼顾扩展性与严格限额。

## 实验评估

论文的评估比较扎实，因为它既测了数据结构本身，也测了完整 Linux 实现，并且工作负载正是先前被 `mmap_lock` 拖慢的那些。单看用户态数据结构，interval skiplist 在纯查找上确实不如 maple tree：Query latency 高 `35%`，峰值 Query throughput 只有后者的 `0.77x`。这个代价是有原因的，maple tree 作为高分支因子 B-tree，读遍历时访问节点更少、cacheline 利用也更好。但论文要解决的瓶颈已经不是纯查找，而是更新扩展性。恰好在这些操作上，skiplist 的收益非常明显：`Alloc` 峰值吞吐提高 `22.9x`，`Map` 提高 `5.28x`，而单线程 `Map` latency 还降低了 `49%`。

放到内核里看，LMbench 显示了一些作者没有回避的代价：`fork+exit` latency 增加 `21.6%`，page fault latency 增加 `3.2%`，`mmap+fault+munmap` 增加 `3.22%`。真正重要的是多线程结果。地址空间微基准里，`mmap()` 吞吐最高提升 `13.1x`，而 alloc-fault-modify 串联操作提升 `10.4x`。宏基准同样吻合这个结论：Apache 在单进程配置下提升 `4.53x`，默认多进程配置下提升 `3.19x`；LevelDB 提升 `4.49x`；Metis 提升 `1.47x`；Psearchy 提升 `1.27x`。论文还专门把 Fault、Alloc、Modify 三条路径分别关掉做拆分实验，结果显示只要禁用其中任何一项，并行扩展性都会明显变差，这很好地支撑了作者的中心论点：不能只修一条路径，必须整套一起修。

## 创新性与影响

和已有地址空间工作相比，这篇论文的新意不只是“把锁拆细”。它同时解决了此前工作往往只覆盖一部分的三件事：动态区间加锁、RCU-safe 的多区间更新，以及与 production kernel 真实地址空间语义的兼容。RCUVM 展示了 Fault 可以如何与更新并行，但它既没有并行化 Alloc 和 Modify，也只支持 anonymous memory。RadixVM 虽然能并行非重叠操作，却依赖 page-granular metadata、和 RCU 配合较差，而且论文认为它的地址分配策略在真实内核里并不实用。

因此，这篇论文不只是一个 Linux patch，而更像是一种适用于 interval-heavy kernel subsystem 的设计模板：把同步原语嵌进 interval map 本身，再额外为 whole-structure operation 和 allocation placement 提供显式支持。直接受众当然是 kernel VM 研究者和 Linux MM 开发者，但作者关于“类似问题也会出现在 file system、device-memory interval map 等其他内核子系统里”的判断是成立的，这让它的影响面明显超出了地址空间管理本身。

## 局限性

这套设计并非没有代价。与 maple tree 相比，它的查找更慢，这会直接反映成 page fault 和 `fork()` 的小幅开销增长。因此，论文真正证明的是一个更窄但更扎实的命题：当瓶颈主要来自更新扩展性时，这种设计更好；如果工作负载主要是单线程查找，它未必占优。类似地，Linux 实现里仍有 fallback path。file-backed memory 目前只对作者确认过的文件系统开放，也就是 `ramfs`、`tmpfs` 和 `ext4`；一些较少见的操作仍会退回 global locking。

另外还有一些工程上的假设值得记住。per-core arena 通过消耗虚拟地址空间来换取并行分配，论文强调即便 128 个 arena 在 x86-64 的 256 TiB 地址空间里也不到 `4%`，但这终究带有架构前提。评估在吞吐上已经很充分，不过对额外元数据和锁带来的内存成本、长期碎片化行为，以及 private arena 耗尽后大量线程回退到 shared region 时的最坏公平性，讨论得相对少一些。换句话说，它作为系统机制已经相当有说服力，但还不是所有平台与工作负载上的最终答案。

## 相关工作

- _Clements et al. (ASPLOS '12)_ - RCUVM 让 Fault 可以与更新并行，而这篇 SOSP 论文进一步瞄准了 production kernel 中更难的 `mmap()`/`munmap()` 更新扩展问题。
- _Clements et al. (EuroSys '13)_ - RadixVM 同样并行化非重叠地址空间操作，但它依赖 page-granular radix-tree metadata；本文认为这种做法在真实内核里会带来过高开销，也不利于 RCU。
- _Kogan et al. (EuroSys '20)_ - 可扩展 range lock 解决了部分动态区间加锁问题，而 concurrent interval skiplist 则把加锁与区间更新本身合并进一个结构里，并把全局回退从常态变成少数情况。
- _Boyd-Wickizer et al. (OSDI '10)_ - 那篇 Linux scalability 研究把 `mmap_lock` 指认为 many-core 时代的重要瓶颈；本文可以看作是在不改应用的前提下，正面移除这一瓶颈的后续尝试。

## 我的笔记

<!-- 留空；由人工补充 -->
