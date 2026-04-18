---
title: "PIPM: Partial and Incremental Page Migration for Multi-host CXL Disaggregated Shared Memory"
oneline: "PIPM 在多主机 CXL 共享内存里只迁移热点 cache line，并把数据移动嵌入一致性流量中，避免整页迁移把其他主机拖慢。"
authors:
  - "Gangqi Huang"
  - "Heiner Litz"
  - "Yuanchao Xu"
affiliations:
  - "Computer Science Engineering, University of California, Santa Cruz, Santa Cruz, California, USA"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790203"
tags:
  - memory
  - disaggregation
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PIPM 的核心观点是：在多主机 CXL 共享内存里，整页迁移本身就是错的抽象。它只迁移页面里真正偏向某个主机的热点 cache line，把数据移动嵌入普通的一致性事件里，而不是显式复制整页，并且扩展一致性协议，让迁移到本地 DRAM 的数据还能被高效访问。论文在模拟器里报告，相比原生 multi-host CXL-DSM，PIPM 最多带来 `2.54x`、平均 `1.86x` 的性能提升。

## 问题背景

这篇论文要解决的是 CXL 3.x 的一个结构性矛盾。multi-host CXL-DSM 让多台主机可以以 cache-coherent 的方式共享一个大的远端内存池，这对数据库、图分析和 AI 系统都很有吸引力；但在 LLC miss 之后，远端 CXL 内存访问依然明显慢于本地 DRAM。对单主机场景来说，最自然的办法是 page migration：把热点页迁到本地，把冷页留在共享池里。

问题在于，多主机共享时，这个思路会反过来伤害系统整体。某一页对主机 A 很热，不代表它对其他主机不重要。一旦把整页迁到 A 的本地 DRAM，其他主机访问该页时就不再是普通的、可缓存的 CXL 访问，而会变成需要额外 hop、额外往返、还带地址重映射成本的 non-cacheable inter-host access。论文把这件事概括成 “local gain, global pain”。而且，迁移控制面本身也变重了：统一物理地址变了，就要做跨主机协调、页表更新、TLB shootdown，外加 CXL RPC，不再是单机里相对局部的一次内核操作。

作者先用实验把这两个问题量化出来。在四主机设置下，面向单主机 tiered memory 设计的 Nomad 和 Memtis，平均会产生 `34%` 和 `29%` 的 harmful migration。更短的迁移间隔确实更容易捕捉多主机访问模式，但当间隔缩到 `1 ms` 时，管理开销和数据搬运开销反而压过收益，性能还会低于不迁移的基线。换句话说，真正的问题不是“再做一个更准的热点页分类器”，而是“别让共享内存优化变成额外的一致性负担和控制路径负担”。

## 核心洞察

论文最重要的洞察是：multi-host CXL-DSM 需要同时使用两种粒度。迁移决策仍然应该在 page 级做，因为共享关系、归属关系和跨主机竞争通常是页级现象；但真正的数据搬运不应该还是整页，而应该退到 cache-line 粒度，并且只在正常内存流量本来就会触碰这些数据时顺手完成。

PIPM 因而把“决定谁更该拥有这页”和“实际把数据搬过去”拆开。它先用一个 majority-vote 策略跟踪：某台主机对某页的访问是否已经比其余所有主机加起来还多到值得迁移。可一旦达到阈值，PIPM 并不会立刻复制整页、改页表、刷 TLB，而只是把这页标记成 partially migrated，并分配一个本地 backing page。随后，页面中的各个 cache block 才会随着正常的 fill、eviction 和 writeback，逐步漂移到这台主机的 DRAM；如果之后别的主机又变成主要访问者，这些 line 还可以逐步漂回 CXL 内存。

这个设计之所以成立，是因为它正好贴合了多主机共享的真实形态。很多页并不是“完全私有”或“完全共享”，而是同一页内部有些 line 对某台主机高度局部，有些 line 很少访问，还有些 line 被多台主机交替访问。论文真正的新意，就是把这种页内混合访问模式当成一等对象来管理。

## 设计

PIPM 的硬件支持由三部分组成：迁移策略、重映射表和新的 coherence 设计。迁移策略使用类似 Boyer-Moore 的 majority vote。位于 CXL 侧的 Global Remapping Table 为每个共享页记录 current host ID、candidate host ID 和一个小的 global counter。当某个主机对该页的访问次数比其他主机合计多出预设阈值时，系统就启动 partial migration。位于每个主机本地的 Local Remapping Table 则记录承载这些迁移 line 的本地 PFN，以及在共享增强时用来撤销迁移的 local counter。关键点是，启动或撤销 partial migration 只需要更新这些表，并不触发页表重写或 TLB shootdown。

真正的数据搬运是 incremental 的。PIPM 把迁移嵌进一致性事件，而不是发起显式整页拷贝。若本地主机是某个 line 最近的访问者，那么一次本地 writeback 就可以顺手把这个 line 从 CXL 内存迁进本地 DRAM；若之后另一台主机来读写该 line，一致性路径又可以把最新数据逐步送回 CXL 侧。这样，系统直接复用原本就存在的内存流量作为运输机制，避免了以往短周期 page migration 最致命的 bulk transfer 开销。

为了让 partial migration 仍然保持一致性，论文扩展了默认的 CXL-DSM MESI 风格协议。它在本地目录里加入 `ME` 状态，又借助已有 invalid 状态加 1-bit in-memory marker 编码出 `I'` 状态，并在本地 DRAM 与 CXL memory 两边都维护对应的内存位。这样一来，主机可以先在本地判断某个 partially migrated line 的最新副本是否在自己的 DRAM 中，而不必每次都先去询问 CXL device directory。结果就是：本地访问迁移 line 的路径显著变短，而跨主机访问在需要时仍会通过 owning host 保持一致性。作者还用 Murphi 对该协议做了死锁、SWMR 和顺序一致性的模型验证。

按论文给出的估算，空间开销不大：本地 remapping-table entry 约 `4 B`，全局 entry 约 `2 B`，每台主机需要 `1 MB` local remapping cache，CXL 设备侧需要 `16 KB` global remapping cache。作者将其描述为大约占 RSS 的 `0.1%` 和 CXL-DSM 总容量的 `0.05%`。

## 实验评估

实验基于 cycle-level 模拟器，系统配置为四台主机、每台主机一个 single-socket CPU、`128 GB` CXL-DSM，以及每台主机 `32 GB` 本地 DRAM。工作负载覆盖 GAPBS 图分析、PARSEC、XSBench，以及 Silo 上的 TPC-C 和 YCSB。对比对象包括不做迁移的 Native CXL-DSM、Nomad、Memtis、HeMem，以及两个消融基线：`OS-skew` 保留 PIPM 的迁移策略但仍用传统 OS 页迁移；`HW-static` 保留增量 line 迁移机制，但采用类似 Flat Mode 的静态映射。

主结果很强，而且比较完整。PIPM 相对 Native CXL-DSM 平均达到 `1.86x` 性能，最高 `2.54x`，并且在论文给出的所有工作负载上都优于其他方案。收益最大的是图类工作负载，例如 SSSP 和 PageRank，这些程序的线程会反复访问具有明显局部性的区域，性能提升大约在 `142%-151%`。数据库类负载提升更温和，但也有约 `36%-53%`。两个消融实验同样重要：`OS-skew` 相对 Native 只提升 `31.5%`，`HW-static` 只提升 `15.7%`，这说明 PIPM 不是单靠“更好的策略”或“更细的机制”之一就能成立，而是两者必须协同。

更底层的指标也支持这条叙事。PIPM 把平均本地内存命中率提升到 `56.1%`，而 Nomad、Memtis 和 HeMem 分别只有 `26.5%`、`31.0%` 和 `28.1%`。它还把 inter-host memory access stall 压到平均总执行时间的 `1.5%`，相比之下，几个基于单机场景假设的基线大约都在 `16%-19%`。与此同时，本地 DRAM 占用并没有失控：页级映射足迹平均只占总内存的 `7.3%`，真正迁移的 cache line 约占 `5.5%`，远小于静态划出 `25%` 本地分区的做法。灵敏度实验还显示，CXL 延迟越高，PIPM 的相对价值越大；而适度大小的 remapping cache 已经能保住绝大部分收益。总体而言，这组实验对论文核心主张的支撑是充分的，不过证据全部来自模拟，而非真实 CXL 3.x 硬件。

## 创新性与影响

相对于 _Xiang et al. (OSDI '24)_ 的 Nomad 和 _Lee et al. (SOSP '23)_ 的 Memtis，PIPM 的创新点并不是在相同的软件 page migration 框架里把热点预测做得更准，而是把抽象本身换掉了：迁移在决策上仍是 page-aware 的，但执行上变成 cache-line 粒度，并且与 cache coherence 协同设计。相对于 Flat-Mode 风格的硬件 tiering，它的关键推进则在于映射是动态且 multi-host-aware 的，而不是一段 CXL 空间和一段本地空间之间的固定交换关系。

因此，这篇论文对把 CXL 当作“真正共享内存”而不只是远端 NUMA 池来看待的架构研究者和系统研究者都很重要。它说明在多主机共享、且保持一致性的前提下，正确的管理单位既不是原封不动的整页，也不是简单的 DRAM cache line，而是带有页级归属判断、但按行逐步移动的数据。这会让它很可能被后续的 CXL 内存管理、coherence 机制以及共享数据库系统论文持续引用。

## 局限性

最大的局限是部署现实性。PIPM 的全部结果来自详细模拟器，论文没有给出真实 multi-host CXL 3.x 机器上的硬件原型或内核实现。它还要求相当多的硬件改动：remapping table、remapping cache、额外的 in-memory state bit，以及 host 端和 CXL memory node 端的一致性协议扩展。对架构论文来说这可以接受，但也意味着落地门槛并不低。

实验范围也比这个想法的野心要窄一些。系统模型固定为四台主机、每台单 socket CPU，并且默认所有共享 heap 数据初始都放在 CXL 内存里，代码、线程栈和内核数据则视为私有本地数据。这些假设便于分析，但也让人难以直接判断：在更大的 fabric、角色更异构的主机组合、或者已经有应用层 placement 策略的系统里，PIPM 还会表现得多稳。最后，majority-vote 阈值虽然在一个不大的范围内表现稳定，但它本质上仍是阈值驱动策略，而不是对所有共享模式都给出最优性的设计。

## 相关工作

- _Xiang et al. (OSDI '24)_ — Nomad 面向 CXL tiering 做事务式整页迁移，但它默认“整页搬走”本身大体合理；PIPM 证明这个前提在 multi-host shared memory 里会失效。
- _Lee et al. (SOSP '23)_ — Memtis 改进了 tiered memory 里的热点分类与页大小选择，而 PIPM 的重点是多主机共享下的 coherence-aware partial migration。
- _Vuppalapati and Agarwal (SOSP '24)_ — Colloid 主要围绕访问延迟做 tiered-memory placement，而 PIPM 的中心问题是 coherence side effect 与 inter-host non-cacheable access。
- _Chou et al. (MICRO '16)_ — CANDY 研究的是 multi-node system 中的 coherent DRAM cache；PIPM 则面向 CXL-disaggregated shared memory，并显式加入迁移控制与重映射元数据。

## 我的笔记

<!-- 留空；由人工补充 -->
