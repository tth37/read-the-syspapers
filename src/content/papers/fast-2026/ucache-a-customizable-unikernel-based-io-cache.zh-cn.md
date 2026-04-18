---
title: "uCache: A Customizable Unikernel-based IO Cache"
oneline: "uCache 把 `mmap` 式 IO 缓存变成可由应用定制的 unikernel 服务，用共享 VMA、策略回调和可插拔后端把简单性与接近 `SPDK` 的性能放到一起。"
authors:
  - "Ilya Meignan--Masson"
  - "Masanori Misono"
  - "Viktor Leis"
  - "Pramod Bhatotia"
affiliations:
  - "Technical University of Munich"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/TUM-DSE/uCache"
tags:
  - caching
  - kernel
  - virtualization
  - storage
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`uCache` 是一个面向 unikernel 的 OS 级 IO 缓存，保留了 `mmap` 的内存访问表面，同时把缓冲区大小、后端和替换策略重新交给应用决定。它让应用与 OS 共享 VMA 级缓存元数据，在同一地址空间执行策略回调，并通过 `uVFS`/`uStore` 把缓存和存储访问拆开。对缺页且必须淘汰的极端负载，原型相对 `mmap` 可达到最高 `55x` 吞吐提升，而其 NVMe 后端平均只比 `SPDK` 慢 `3.5%`。

## 问题背景

现代云应用既要面对本地 NVMe，也越来越多地要面对非文件系统后端。通过 `mmap` 使用内核页缓存固然简单，但在快设备上，它的通用实现会直接暴露出来：page fault 昂贵、内存管理路径里的共享结构会争用、异步 IO 很别扭、TLB shootdown 也会拖累扩展性。同时，POSIX 只给出 `madvise` 这类弱提示，难以表达事务保护页、按工作负载定制的预取，或者 `8 KiB`、`16 KiB` 这类应用逻辑缓冲区。

另一端是自己写 userspace cache，用显式 `pin`/`unpin` 之类的接口掌控替换和后端选择。那样确实灵活，但复杂度会重新回到每个应用里，而且常常要绕开标准文件系统。论文要解决的正是这个现实困境：今天开发者通常只能在“简单”和“高性能且灵活”之间二选一。

## 核心洞察

论文的核心判断是：真正造成这种折中的，是 OS 和应用之间的隔离，而不是内存映射本身。在 unikernel 里，缓存可以把内部控制点直接暴露给应用。因此，`uCache` 把每个映射区域建模成共享 VMA，对外携带缓冲区大小、后端选择、resident-set 类型和策略 hook。OS 仍然负责透明地处理缺页，但淘汰、预取和安全约束的规则可以直接来自应用逻辑，而不是受限于通用 POSIX 提示。

## 设计

`uCache` 作为库实现于 `OSv` 中。它的主接口仍然像 `mmap`，但每个映射都会变成唯一一个共享 VMA，而这个 VMA 内由固定大小的 `Buffer` 组成，粒度由应用决定，不受硬件页大小限制。API 还暴露 `evict`、`prefetch`、`writeback`、`msync`、`ensureCached` 等显式原语，因此需要时可以绕开纯 page-fault 驱动的控制方式。

可定制性来自分层的策略 hook：全局 hook 决定是否需要淘汰、该从哪些 VMA 里选对象；VMA hook 决定要淘汰或预取哪些 `Buffer`；Buffer hook 如 `isEvictable()` 决定单个对象能否被换出；此外还有可选 bookkeeping hook。因为这些回调和应用被编译进同一个 unikernel 镜像，它们可以直接读取应用状态。论文用这套机制让数据库里的已锁页不可淘汰，也复用了 DuckDB 的 Parquet 预取知识。

底层缓存管理器使用乐观无锁页表操作。插入时，线程先分配物理内存，再用 `CAS` 争夺目标 PTE，读入数据后才把映射标成 present；失败者只需等待。淘汰时，系统先清 present bit、发起全局 TLB invalidation，再用 `CAS` 把物理地址从页表中摘除；如果期间有别的核心访问该页，就中止淘汰。这套机制同样可扩展到多页 `Buffer`，因此 `uCache` 能支持 `8 KiB`、`16 KiB` 这类应用粒度，而不只是 `4 KiB` 页。

存储访问则由 `uVFS` 和 `uStore` 抽象。`uVFS` 把 VFS 扩展成可对接文件、块或对象后端的统一接口，应用也可以自己提供 `uStore`。原型中的 NVMe `uStore` 借鉴了 kernel-bypass 的零拷贝和每核队列对设计，同时通过轻量 `MiniFS` 层保留文件系统兼容性，把文件偏移翻译成 LBA 后再走快速数据路径。

## 实验评估

实验运行在虚拟机环境中：AMD `EPYC 9654P`、`768 GiB` 内存、直通的 Kioxia `CM-7` NVMe SSD。对 `1 TiB` 文件配 `100 GiB` 缓存的微基准，`uCache` 在最终都要缺页并淘汰的场景下，相对 `mmap` 最高提升 `55x`，而且在 `64` 线程下依然接近线性扩展。NVMe 后端平均只比 `SPDK` 慢 `3.5%`，相对 `libaio` 平均提升 `50%`，在更大的异步 batch 下最高达到 `150%`。作为 `mmap` 替代，随机查找吞吐提升了 `46x` 到 `78x`。

应用移植结果也有说服力。把 `vmcache` 移植到 `uCache` 后，TPC-C 吞吐约为 `118k` 事务每秒，只比专门化 `exmap` 版本低 `3%`，但明显好于 `madvise` 版本。对 DuckDB + Parquet，`uCache` 版本在 TPC-H 上平均提升 `1.98x`，其中 Q4 为 `4.89x`、Q6 为 `6.59x`。这些结果基本支撑了“缓存管理不再主导成本”的主张，但证据确实几乎都来自本地 NVMe。

## 创新性与影响

`uCache` 的新意在于把应用可见的缓存抽象、基于页表的无锁缓存操作，以及可插拔存储层合进同一个设计里。它位于 `Tricache` 式 userspace 控制与 eBPF 式 Linux 定制之间，并提出一个更强的观点：当 OS 已经为单个云应用专门化后，缓存策略本身就应该成为应用设计的一部分。

## 局限性

这个设计依赖 unikernel，原型又绑定在 `OSv` 上，因此它不是普通 Linux 进程可直接采用的页缓存增强。论文也提到缺少 `fork` 带来的可移植性问题。原型里的 `ext4` 路径会把文件偏移到 LBA 的映射整体缓存到内存里，不支持 sparse file，也不支持文件打开期间的结构性变化。崩溃一致性仍然主要由应用负责，而 object store 灵活性的主张也明显多于实证。

## 相关工作

- _Feng et al. (OSDI '22)_ — `TriCache` 把缓存控制保留在用户态，并借助编译器隐藏 `pin`/`unpin` 逻辑；`uCache` 则试图在 OS 级内存映射缓存内部恢复类似控制能力。
- _Papagiannis et al. (EuroSys '21)_ — `Aquila` 通过虚拟化专门化 memory-mapped IO，同时继续依赖 Linux；`uCache` 则转向 unikernel，并把缓存策略暴露为应用可见接口。
- _Cao et al. (USENIX ATC '24)_ — `FetchBPF` 用 eBPF 定制 Linux 预取，而 `uCache` 由于回调能直接访问完整应用状态，因此提供了更广的缓存策略控制面。
- _Zussman et al. (SOSP '25)_ — `cache_ext` 让 Linux 页缓存可通过 eBPF 定制，而 `uCache` 主张更深的 OS-应用联合设计以及对非文件系统后端的灵活支持。

## 我的笔记

<!-- empty; left for the human reader -->
