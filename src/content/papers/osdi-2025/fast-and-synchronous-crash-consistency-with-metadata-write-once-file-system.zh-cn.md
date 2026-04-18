---
title: "Fast and Synchronous Crash Consistency with Metadata Write-Once File System"
oneline: "WOFS 把每次文件操作的元数据压成一个带校验的 package 一次写入，再从 package 重建文件系统对象，在保持同步崩溃一致性的同时逼近 PM 带宽上限。"
authors:
  - "Yanqi Pan"
  - "Wen Xia"
  - "Yifeng Zhang"
  - "Xiangyu Zou"
  - "Hao Huang"
  - "Zhenhua Li"
  - "Chentao Wu"
affiliations:
  - "Harbin Institute of Technology, Shenzhen"
  - "Tsinghua University"
  - "Shanghai Jiao Tong University"
conference: osdi-2025
code_url: "https://github.com/WOFS-for-PM/"
tags:
  - filesystems
  - crash-consistency
  - persistent-memory
  - storage
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

WOFS 的判断是，PM 文件系统不该为了让一次操作可崩溃恢复，就去分散更新一串 inode、dentry、log tail 之类的元数据对象。它把一次文件操作需要的元数据压成一个带 CRC32 校验的 package，只写一次，并通过一个翻译层把这些 package 重新解释成 inode、文件和目录抽象。Linux 原型 WOLVES 在 Optane PM 上把顺序写吞吐做到 2.20-2.24 GiB/s，相当于原始 PM 带宽的 97.3%-99.1%。

## 问题背景

这篇论文抓住的是 PM 文件系统里的一个结构性矛盾。持久内存让同步持久化重新变得便宜，因为文件系统只需要把数据刷到 PM 接口并执行 fence 即可，论文给出的持久缓冲到达时间大约是 50-300 ns。这意味着“系统调用返回即持久”的语义重新值得追求，因为应用不必再频繁依赖 `fsync`。但现有 PM 文件系统的崩溃一致性设计，大多还是继承了面向块设备时代的思路：journaling 会先额外写一份元数据备份，再原地更新真正的元数据；log-structured 方案要维护 log entry 和 tail，后面还要付 GC 的代价；soft update 虽然不写冗余副本，却要在多个元数据对象之间维护严格写序。

作者用 PMFS、SplitFS 和 NOVA 做了拆账，结果很有说服力。在六个工作负载上，它们分别把 22.9%-76.5%、63.8%-97.4% 和 11.3%-75.5% 的总 I/O 时间花在元数据上。根本原因有三层。第一，PM 的持久缓冲刷新粒度比这些零碎元数据大得多，随机小写会放大实际流量。第二，写序点会让后续 I/O 被前面的元数据写拖住，降低并行度。第三，像 NOVA 这样的 LFS 还会因为 tail 更新和 GC 增加更多元数据访问。结果是，在论文机器上的顺序写场景里，这些系统连大约 2.26 GiB/s 的 PM 写带宽一半都吃不满。

## 核心洞察

论文最重要的主张是：崩溃一致性的基本单位不应该是“传统元数据对象集合”，而应该是“一次文件操作”。WOFS 因此把一次操作需要的元数据打包成单个 package，在包头里放类型、时间戳、magic number 和 CRC32，然后把这个 package 一次持久化。纯元数据操作的关键路径就变成 `JM|JC`；涉及数据块的操作则是 `D -> JM|JC`，即先把数据写稳，再写引用这些数据的数据包。

这样做的价值在于，恢复逻辑不再依赖一长串分散元数据的写序，而是转向检查 package 是否完整，以及 package 之间的因果关系是否成立。若 package 不完整，校验和或指针检查会失败，它会被直接丢弃。若数据块已经写下去，但还没有任何有效 package 指向它们，那这些块就只是未引用空间，可以在恢复后重新分配。换句话说，WOFS 把“一致性来自谨慎编排多次元数据更新”改成了“一致性来自单条受保护的操作记录加上重建逻辑”。

## 设计

WOFS 定义了四类原子 package。`create` package 是 256 字节，保存 inode 静态属性、父 inode、被链接 inode、名字项以及父目录属性更新。`write`、`attr` 和 `unlink` package 都是 64 字节。复杂操作则用多个原子 package 组合而成，例如 rename 被表示为 create 加 unlink，并通过 forward pointer 把两个子 package 串起来，以便恢复时确认这个复合操作是否完整。

因为 package 取代了传统的磁盘元数据布局，系统需要额外一层 Package Translation Layer，也就是 PTL。PTL 会把 package 解析成若干内存节点：create 对应 C-node，attr 对应 A-node，write 对应 W-node。随后它再把这些节点重组成上层仍然熟悉的抽象：用 create 和 attr 组合 inode table，用 write package 构成每个文件的数据列表，用 create package 里的 name entry 构成目录内容。应用和 VFS 看到的仍然是正常文件系统对象，只是底层持久状态已经变成了 package。

WOFS 也刻意避免 log 布局。package 和数据块像 `malloc` 一样散布在 PM 上，通过因果失效关系来回收空间：后来的 unlink 会使旧的 create 失效，新的 attr package 会使旧 attr package 失效，truncate 或 overwrite 会使旧 write package 失效，而复合 package 只有在所有组成部分都失效后才能回收。为了让这种非日志布局仍然具备快速恢复能力，作者提出 coarse persistence。系统以 4 KiB 为单位分配 package group，并把 group 地址及时记录进 bitmap。崩溃恢复时，它只需要扫描 bitmap 和被标记的 package group，而不必把整块 PM 全扫一遍。

WOLVES 把这套设计落到了 Linux 5.1.0 上，代码超过 12,000 行 C。实现上它用了按核划分的分配器和 PTL 分片、基于动态数组的文件索引、重叠写时的 copy-on-write、顺序追加场景下的 huge allocation，以及按 256 字节 PM buffer 步长做 read ahead。数据写入仍然要先于 package，这一点没有被取消，但元数据写序基本被压缩到了每次操作一个同步点。

## 实验评估

实验平台是一台 16 核 Xeon Gold 5218、128 GiB DRAM、2x256 GiB Intel Optane PM 的服务器，比较对象包括 PMFS、NOVA、NOVA-RELAX、SplitFS、MadFS、EXT4-DAX 和 XFS-DAX。崩溃一致性验证也做得比较扎实：作者在指令粒度跟踪 PM 写入，在 fence 之间重排它们，对三类代表性工作负载各注入 1,000 个随机崩溃点，最后报告 WOLVES 总能恢复到崩溃前最新的一致状态。

原始 I/O 结果里最关键的是顺序写。4 KiB I/O 时，WOLVES 能稳定在 2.20-2.24 GiB/s，相当于原始 PM 带宽的 97.3%-99.1%。随机写无法从 huge allocation 中受益，但 WOLVES 仍然比基线高出 1.65x-9.44x，因为它几乎把元数据热路径上的冗余工作都砍掉了。tail latency 方面，它在内核态文件系统里表现最好；SplitFS 和 MadFS 只有在尾部不够极端时才看起来更快，一旦偶发内核元数据路径被触发，极端尾延迟就明显恶化。

更有说服力的是宏基准，因为它们同时覆盖 open、create、write、read、delete 等操作组合。WOLVES 在 Filebench 上总体领先；在与 MadFS 的单线程对比里，它在 Webserver、Fileserver、Webproxy 和 Varmail 上分别快 9.14x、14.4x、35.8x 和 61.4x。RocksDB 上，它在论文测试的 fill、append、update 工作负载中比其他 PM 文件系统快 1.20x-6.73x。恢复开销也不高：常见工作负载下只需要 2.61-3.99 秒；即便在一个 256 GiB、完全填满的最坏场景里，它也只需扫描约 10.9% 的空间，整体恢复时间约为 21.6 秒。

## 创新性与影响

相对于 _Dulloor et al. (EuroSys '14)_ 的 PMFS，WOFS 不是在 journal placement 或 commit 结构上做小修小补，而是直接替换掉“先写 journal、再更新真正元数据”这一整套模式，把每次操作压成一个 package。相对于 _Xu and Swanson (FAST '16)_ 的 NOVA，它并不是一个更高效的 PM log-structured file system，而是干脆拒绝日志式元数据布局，转而采用可立即重用失效空间的非日志布局。相对于 _Kadekodi et al. (SOSP '19)_ 的 SplitFS，它虽然复用了 transactional checksum 的思想，但真正新的部分是重新定义了“什么东西应该被打包并持久化”。相对于 _LeBlanc et al. (OSDI '24)_ 的 SquirrelFS，它进一步提出：哪怕同步 soft update 可以证明正确，只要它仍然围绕太多分散元数据对象组织写序，就会继续浪费 PM 带宽。

因此，这篇工作不是单点优化，而是给出了一个新的 PM 元数据组织模型：按操作聚合元数据，通过重建恢复文件系统抽象，把 PM 带宽花在真正的数据移动上，而不是元数据编排上。后续无论是 PM 文件系统、CXL 持久层文件系统，还是更广义的崩溃一致性研究，都很可能把它当作“重新设计元数据单位”这一方向的代表性工作。

## 局限性

WOFS 并没有消除数据写序。系统仍然要求数据先写稳，再写引用它的 package；讨论部分也明确解释了为什么作者没有继续走到 `D|JM|JC`：在快 PM 上做数据校验太贵，论文测得 CRC32 会带来约 40.1% 的写路径开销，xxHash 也还有 32.3%。所以它非常激进地解决了元数据开销问题，但没有解决“数据也完全无序写入且仍可验证”这一更难的问题。

第二个限制是收益带有工作负载条件。huge allocation 对顺序追加很有效，但对随机写无帮助；aging 和 fragmentation 会把顺序写降到 1.70-1.82 GiB/s，把随机写降到 1.31-1.44 GiB/s；线程数达到 9 以上后，底层 PM 硬件争用会让吞吐下滑，需要通过采样延迟和限带宽来缓解。恢复虽然快，但仍然依赖扫描 package group 并重建 PTL，而不是直接从 checkpoint 恢复。最后，WOLVES 即便在文件关闭后仍要保留几 MiB 的 PTL 元数据，开销不算大，但也不是零成本。

## 相关工作

- _Dulloor et al. (EuroSys '14)_ - PMFS 用 journaling 保证 PM 上的崩溃一致性，而 WOFS 把每次操作的元数据压成一个带校验的 package，并避免后续原地元数据更新阶段。
- _Xu and Swanson (FAST '16)_ - NOVA 依赖分离的 log entry 与 tail 更新，并最终承担 GC 代价；WOFS 则采用非日志 package 布局，并立即重用失效空间。
- _Kadekodi et al. (SOSP '19)_ - SplitFS 用 transactional checksum 加速 journaling，但仍维护传统元数据结构；WOFS 直接改变了持久化元数据的基本单位。
- _LeBlanc et al. (OSDI '24)_ - SquirrelFS 在 Rust 中验证同步 soft update，而 WOFS 的观点是：只要协议仍然建立在大量有序元数据写之上，PM 带宽就会继续被浪费。

## 我的笔记

<!-- 留空；由人工补充 -->
