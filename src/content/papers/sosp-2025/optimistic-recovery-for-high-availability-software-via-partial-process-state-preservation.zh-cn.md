---
title: "Optimistic Recovery for High-Availability Software via Partial Process State Preservation"
oneline: "Phoenix 让服务从 main 重新启动时只复用选中的长生命周期状态，并用 unsafe region 与可选交叉校验避免故障后把所有状态都重建一遍。"
authors:
  - "Yuzhuo Jing"
  - "Yuqi Mai"
  - "Angting Cai"
  - "Yi Chen"
  - "Wanning He"
  - "Xiaoyang Qian"
  - "Peter M. Chen"
  - "Peng Huang"
affiliations:
  - "University of Michigan"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764858"
code_url: "https://github.com/OrderLab/phoenix"
tags:
  - fault-tolerance
  - kernel
  - pl-systems
category: verification-and-reliability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Phoenix 瞄准的是 full restart 和 full-state checkpoint 之间长期缺失的中间地带。它让进程从 `main` 重新开始执行，但保留选中的长生命周期内存状态，再配合 unsafe region 检查和可选的后台 cross-check，使这条快速路径尽量与应用原本的恢复语义保持一致。

## 问题背景

高可用软件需要“又快又对”的恢复，但现有方案通常只能二选一。普通进程重启的优点是干脆，所有运行时状态都会被丢弃，因此最容易避开已经污染内存的 bug；缺点同样明显，新进程必须把所有状态重新构造一遍，包括重新读数据、重放日志、恢复索引和重新预热缓存。论文用 Redis 的例子把这个问题量化了：一次 15 秒的 hang 触发重启后，仅从 6 GB 的 RDB 文件恢复就需要 53.5 秒，而系统再花 361.7 秒才能回到原先 90% 的吞吐。

另一条路是 checkpoint 或 full-state restore。它们减少了重建状态的时间，但也把同一个软件错误可能留下的坏状态一起保存了下来；如果恢复点更早，又会丢掉最近的更新。更细粒度的方案，比如 microreboot 或 Orleans，可以缩小恢复范围，但代价是要求应用被重新拆成独立可重启的组件，这对现有大型服务通常太重。于是，这篇论文真正要解决的问题是：能不能只留下那些最贵、最稳定、最值得复用的长生命周期状态，同时把更容易出错的瞬时执行上下文统统丢掉。

## 核心洞察

Phoenix 的核心主张是，很多真实故障并不会破坏应用最重要的长期状态，哪怕这些状态恰恰主导了恢复成本。作者分析了 Redis、MySQL、Hadoop、MongoDB、Ceph 和 ElasticSearch 的 64 个真实故障，发现其中 35 个只影响 temporary state，另外 21 个虽然触发崩溃或 hang，但没有损坏 global state，真正破坏长期状态的只有 8 个。换句话说，bug 和 bytes 的分布并不对称：复杂的控制逻辑、请求级对象和局部变量更容易出错，而真正占大头的大型数据结构，往往由相对简单、已经被充分验证的代码维护。

这就让“保留一部分、丢弃一部分”的第三种设计点有了现实基础。Phoenix 的做法不是 preserve-all，也不是 preserve-none，而是只保留那几个语义上关键、恢复时最昂贵的数据结构，把其余状态丢弃，然后像普通重启一样从头执行。真正关键的是，这件事不可能靠纯通用机制自动完成。系统必须借助开发者对应用语义的理解，既知道什么值得保留，也知道故障是否恰好发生在修改这些状态的中途。因此，Phoenix 把正确性定义成“与应用默认恢复路径等价”，而不是试图凭空构造一个更强的恢复语义。

## 设计

Phoenix 是一个跨 kernel、runtime、libc 和 compiler 的协同方案。API 层面，开发者用 `phx_init` 注册 restart handler，在崩溃或 watchdog 触发时调用 `phx_restart`，再在 `main` 中通过 `phx_is_recovery_mode` 判断当前是否为 Phoenix 恢复模式，并把 preserved object 重新接到新创建的执行环境上。核心 kernel 机制是 `preserve_exec`，它可以看作 `exec` 的一个变体：新进程仍得到新的可执行映像和新的栈，但被选中的页面会以原来的虚拟地址直接装入新地址空间。这样一来，Phoenix 不需要做 pointer swizzling，恢复后的程序可以直接继续使用这些保留下来的复杂数据结构。

为了覆盖不同类型的状态，Phoenix 提供了三类保存方式。第一类是 heap preservation：它改造 glibc `malloc`，跟踪 arena、`mmap` 和 `brk` 分配出的页面，并在重启时把相关页面搬运到新进程。第二类是 static variable preservation：作者引入 `.phx.data` 和 `.phx.bss` 两个 ELF section，开发者只需要用注解把变量放进去，而不必手写一堆全局导出和复制样板代码。第三类是自定义地址区间保存，留给更特殊的内存布局。由于 heap 跟踪有意采用 over-approximation，重启后可能保留了已经不可达的对象，Phoenix 因此又加了 mark-and-sweep 清理机制，并要求对 lock 等同步对象重新初始化，对 reference count 重新计算。

保证正确性的关键机制是 unsafe region。开发者需要标出“真正会修改可保留状态”的最小代码区间；如果进程在这个区间里崩溃，Phoenix 就直接放弃快速路径，退回应用默认恢复。为了减少手工标注，论文还实现了一个基于 LLVM 的静态分析器，按 transaction 粒度去逼近“第一次修改”和“最后一次修改”的边界。对希望获得更强保证的用户，Phoenix 还支持后台 cross-check：主进程先用 preserved state 迅速恢复并继续服务，同时后台进程运行默认恢复路径，拿得到的 reference state 和 Phoenix 的初始状态做比较；如果不一致，再 hot-switch 到经过验证的后台进程。对于 XGBoost、VPIC 这类长计算任务，论文还提供了 `phx_stage`，用显式的 stage hook 做 progress recovery，而不是把整个长时间计算区间都视为 unsafe。

## 实验评估

先看机制本身的成本。microbenchmark 显示，保留状态低于 4 MB 时，Phoenix 的重启时延大约是 1.20 ms；保留 32 MB 时为 1.56 ms；即使保留 32 GB 内存，也只需要 220.6 ms。更有说服力的是六个真实系统上的端到端结果：Redis、LevelDB、Varnish、Squid、XGBoost 和 VPIC。把 Phoenix 接入这些系统的平均修改量只有 260.2 行代码，占代码库 0.52%，说明它并不是只能服务于论文原型的“一次性移植”。

在 17 个成功复现的真实 bug 上，Phoenix 基本都落在可用性与正确性的更优折中点。对 Redis，它既保留了 vanilla restart 几乎立刻重启的特征，又把恢复到故障前可用性的时间压到约 2 秒，而 built-in RDB recovery 需要约 6 分钟，完全不做持久化时的尾部恢复更会拖到 25 分钟。对 LevelDB，Phoenix 直接保留内存中的 skiplist，绕过日志重放，在保持与默认恢复相同逻辑进度的同时，把 downtime 相比 built-in recovery 缩短 130 倍，相比 CRIU 缩短 14 倍。对 Varnish 和 Squid，核心收益来自 cache 还在，因此 hit rate 几乎能立刻恢复。对计算型工作负载，收益则体现为 progress reuse：Phoenix 让 XGBoost 的有效不可用时间相比 built-in checkpoint 下降 19.8 倍，让 VPIC 下降 76.4 倍。

fault injection 的结果进一步说明，这不是单靠“乐观”堆出来的数字。论文总共做了 8,400 次注入实验，其中 Phoenix 成功恢复 7,190 次，成功率为 85.6%。unsafe region 预先把 732 个风险较高的案例导向默认恢复，另有 478 个案例在快速重启后很快再次失败并回退，而不是长期带着坏状态继续运行。对于 Redis、Varnish、Squid 和 LevelDB，在开启 unsafe region 的配置下，论文没有观察到比 vanilla 系统更多的额外数据损坏。运行期开销平均只有 2.7%，远低于 CRIU 的 22.5%；同时 Phoenix 平均可以安全复用 88.4% 的进程内存。

## 创新性与影响

相对于 CRIU 和传统 checkpoint，Phoenix 的新意不只是“恢复更快”，而是改变了恢复模型本身：它不是从老执行继续跑，也不是把内存整体滚回某个时刻，而是重新启动执行流，同时局部挽救语义上值得保留的状态。相对于 microreboot 一类工作，它不要求应用先被重构成 crash-only 组件。相对于 whole-system persistence，它针对的是 software fault，而不是断电等硬件事件，并且把“保留什么”交给应用语义决定，而不是默认整块内存都应该留下。

因此，这篇论文的价值不只是把几个已有技巧拼在一起。它提供了一套面向高可用软件的实用方法论：当恢复的主要成本来自大型内存数据结构的重建时，kernel/runtime/compiler 的联合支持可以显著降低引入 application-aware recovery 的门槛。最直接的受益者会是 cache、database，以及那些已经有一条“安全但很慢”的默认恢复路径、同时又清楚知道哪些状态最值得保留的长时间运行服务。

## 局限性

Phoenix 的正确性上界受默认恢复路径约束。如果坏状态已经被持久化到磁盘，或者故障本质上是一个不修代码就会一直存在的逻辑错误，Phoenix 并不能把它“恢复掉”。论文对这一点讲得很直白：它所谓的正确，是和默认恢复结果等价，而不是比默认恢复更强。

这套系统也确实需要开发者投入额外工作。开发者必须判断哪些状态可保留、确保 preserved object 不会指向被丢弃的内存、标注或验证修改边界，并且常常还要补上 cleanup 与对象重初始化逻辑。LLVM 工具能减轻负担，但它是保守近似，不能完整建模文件写入等 external effect，对大量使用 STL 的复杂 C++ 代码也不够理想。最后，Phoenix 只保留 memory state：socket、file 和 thread 仍要靠正常启动逻辑重建，所以如果应用本身几乎没有昂贵的长期内存状态，或者故障经常发生在漫长的修改窗口内，它的收益就会明显下降。

## 相关工作

- _Candea et al. (OSDI '04)_ - Microreboot 通过重启组件来缩小恢复范围，而 Phoenix 保留单体进程模型，在 fresh restart 时只挽救选中的内存状态。
- _Qin et al. (SOSP '05)_ - Rx 依赖 checkpoint 回滚并在修改后的环境中重执行，而 Phoenix 只复用被挑中的长期状态，其余运行时上下文全部丢弃。
- _Narayanan and Hodson (ASPLOS '12)_ - Whole-system persistence 会在故障后保留整机内存，但 Phoenix 认为 software fault 的关键恰恰在于必须有选择地丢弃一部分状态。
- _Russinovich et al. (EuroSys '21)_ - VM-PHU 为主机更新保留 VM 状态，而 Phoenix 工作在应用数据结构粒度，并且围绕软件崩溃恢复而不是维护窗口来设计。

## 我的笔记

<!-- 留空；由人工补充 -->
