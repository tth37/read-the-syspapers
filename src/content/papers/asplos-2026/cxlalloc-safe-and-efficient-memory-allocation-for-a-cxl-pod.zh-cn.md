---
title: "Cxlalloc: Safe and Efficient Memory Allocation for a CXL Pod"
oneline: "cxlalloc 按一致性域拆分分配器元数据，用跨进程映射协调和可恢复的 CAS/mCAS 协议，让共享 CXL pod 上的动态分配既安全又高效。"
authors:
  - "Newton Ni"
  - "Yan Sun"
  - "Zhiting Zhu"
  - "Emmett Witchel"
affiliations:
  - "The University of Texas at Austin, Austin, Texas, USA"
  - "University of Illinois Urbana-Champaign, Champaign, Illinois, USA"
  - "NVIDIA, Santa Clara, California, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790149"
code_url: "https://github.com/nwtnni/cxlalloc"
tags:
  - memory
  - disaggregation
  - fault-tolerance
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

cxlalloc 是一个面向共享 CXL pod 的用户态内存分配器。它按一致性域拆分元数据，自己协调跨进程映射，并用极小的就地恢复状态保证 allocator 操作可重做。结果是：常规负载下性能接近 mimalloc，而在跨主机一致性受限甚至缺失时仍然可以正确运行。

## 问题背景

论文讨论的是一个普通 allocator 几乎没被设计过的环境：一个小型 CXL pod，8-16 台主机以 cache-line 粒度共享同一块 CXL 内存。在这里，allocator 必须同时解决三个问题。

第一，跨主机硬件缓存一致性可能只有一小段，甚至完全没有，因此 allocator 元数据不能默认处处都能用 `CAS`。第二，内存是在多个进程之间共享的，所以 allocator 必须维护 pointer consistency：同一指针在不同进程里都指向同一物理内存，而且新建映射应当立刻可被别的进程解引用。第三，partial failure 是常态，一个线程或进程崩溃时，其他进程还要继续运行，因此锁和阻塞式恢复都不合适。

作者认为现有方案各自只覆盖一部分需求。mimalloc 这类快速易失性 allocator 没有跨进程共享和恢复能力；持久内存 allocator 有恢复，但通常假设 total failure 和安静的恢复窗口；已有 CXL 内存管理系统则常常依赖固定 heap、只支持小对象，或者把太多元数据放进必须 HWcc 的区域。

## 核心洞察

论文的关键观点是：在 CXL pod 上，coherence、mapping visibility 和 crash recovery 不能被当作普通 heap 之上的补丁，而必须反过来决定 allocator 的布局与协议。

因此 cxlalloc 只把真正需要跨主机原子同步的极少数元数据放进 HWcc 区域，其余元数据留在 SWcc 区域；它预留虚拟地址空间，让各进程在相同 offset 上安装映射；它用 `SIGSEGV` handler 按需补齐映射；它还把恢复状态压缩到每线程 8 字节，只记录足够重做中断操作的信息。若没有 HWcc，同样这条窄原子接口也可以用近内存 `mCAS` 实现。

## 设计

cxlalloc 有三个 heap：small（`8B-1KiB`）、large（`1KiB-512KiB`）和 huge（`512KiB+`）。small 和 large 都用 slab allocation。每个 slab 有 owner 线程、一个记录 size class 和 free bitset 的 SWcc 描述符，以及一个只保存 remote-free counter 的极小 HWcc 描述符。

这种布局把快路径和共享路径分开了。local allocation / free 基本停留在 thread-local 结构里；remote free 不会直接修改别人的位图，而只是对共享计数器做一次 `CAS` 或 `mCAS`。为了让这些远端释放最终可回收，cxlalloc 还引入 `detached` 和 `disowned` 两种 slab 状态：出现过 remote free 的 slab 会被迫继续走 remote-free 路径，直到整个 slab 能被安全地偷回复用，从而避免每个对象都携带 HWcc 元数据。

SWcc 协议的规则是：ownership 变化时必须 flush 和 fence，其余 owner-local 访问可以留在 cache 中。设计上还保证了“缓存里的 owner 过期也只是更保守，不会出错”。

跨进程 pointer consistency 则通过“预留虚拟地址空间 + 延迟建图”实现。small heap 在每个进程的固定 offset 上单调扩展；huge allocation 用 reservation array 分配区间，再用类似 hazard pointers 的 hazard offset 协议判断何时能安全回收 mapping。恢复方面，cxlalloc 使用 lock-free 共享结构、detectable `CAS` 和每线程 8 字节状态，让重启线程能幂等地补完被打断的 allocator 操作。

## 实验评估

实验直接检验了性能、HWcc 内存占用和恢复开销。作者在一台 80 核 Intel Ice Lake 机器上，用 YCSB 与 Twitter memcached trace 比较 cxlalloc、mimalloc、Boost.Interprocess、Lightning allocator、ralloc 和 cxl-shm。跨所有 workload 与线程数，cxlalloc 的平均吞吐达到 mimalloc 的 `93.9%`，ralloc 为 `90.9%`。这很重要，因为 mimalloc 只是性能上限，并不能解决 CXL pod 的共享与恢复问题。

元数据拆分也确实显著降低了 HWcc 需求。宏基准里，cxlalloc 平均只消耗总内存的 `0.02%` 作为 HWcc 内存，相当于 ralloc 的 `7.1%`。恢复快路径的额外成本也很低：去掉恢复状态与 detectable `CAS` 的 nonrecoverable 版本整体只快 `0.3%`。而在 Memento 实验里，ralloc 必须在“阻塞恢复 GC”和“接受内存泄漏”之间二选一，cxlalloc 则没有这两种代价。

论文还在真实 CXL 硬件上评估了 no-HWcc 路径，平台是 Intel Agilex 7 Type-2 设备加 FPGA `mCAS` 原型。该平台的 CXL 读延迟是 `357ns`，本地 DRAM 是 `112ns`；带宽分别是 `19.9 GB/s` 和 `114 GB/s`。即便底层介质已经慢很多，`cxlalloc-mcas` 在 `threadtest` 上仍达到 `cxlalloc-hwcc` 吞吐的 `80%`。但在 remote-free 很重的 `xmalloc-small` 上，它会掉到 HWcc 版本的 `1%`，因为每次 remote free 都要付一次 `mCAS`。这说明论文的主张成立，但 no-HWcc 设计也有非常明确的失速区间。

## 创新性与影响

相较于 _Leijen et al. (ISMM '19)_，cxlalloc 把以 owner 为中心的快速 slab 分配扩展到了跨进程、跨主机环境。相较于 _Cai et al. (ISMM '20)_，它保留了 recoverability，却不再假设 total failure 和阻塞式恢复。相较于 _Zhang et al. (SOSP '23)_，它避免了每个分配都带 reference count 和固定 heap 的代价。因此，这篇论文贡献的是一套完整的共享 CXL allocator 设计，而不只是某个更快的同步技巧。

## 局限性

这个设计假设 CXL 设备足够可靠，能够跨进程崩溃甚至 OS 重启保留状态；它也假设线程会被 pin 到固定核心上，让缓存状态保持可控。若平台没有 HWcc，依赖 uncachable device-biased 区域的 `mCAS` 会在 remote-free 密集型负载下迅速成为瓶颈，`xmalloc-small` 已经清楚展示了这一点。

另外，small heap 只增不减，huge allocation 依赖 `SIGSEGV` 驱动的 lazy mapping 与 `MAP_FIXED` 预留，remote-free 协议也仍然存在病理性碎片场景。论文认为这些情况少见，但它们确实限制了部署范围。

## 相关工作

- _Leijen et al. (ISMM '19)_ — mimalloc 提供了以 owner 为中心的快速 slab discipline，而 cxlalloc 在此基础上补上了跨进程指针一致性、CXL 一致性受限和 crash recovery。
- _Cai et al. (ISMM '20)_ — ralloc 是面向持久内存的可恢复 allocator；cxlalloc 则面向易失但共享的 CXL 内存，并要求在部分进程存活时继续访问，而不是等待阻塞式恢复阶段。
- _Zhang et al. (SOSP '23)_ — cxl-shm 同样关注 CXL 共享内存中的 partial failure，但它依赖每个分配上的 reference count、固定大小 heap 和缺失 huge allocation 支持，这正是 cxlalloc 试图避免的成本。
- _Zhu et al. (DIMES '24)_ — Lupin 说明了为什么 partial failure 是 CXL pod 的核心系统问题，而 cxlalloc 提供了让这类系统真正可实现的 allocator 底座。

## 我的笔记

<!-- 留空；由人工补充 -->
