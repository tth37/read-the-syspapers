---
title: "FlexGuard: Fast Mutual Exclusion Independent of Subscription"
oneline: "FlexGuard 用 eBPF 观察调度器，只在持锁临界区被抢占时让等待者阻塞，从而保住 spinlock 的低延迟并避免 oversubscription 崩溃。"
authors:
  - "Victor Laforet"
  - "Sanidhya Kashyap"
  - "Călin Iorgulescu"
  - "Julia Lawall"
  - "Jean-Pierre Lozi"
affiliations:
  - "Inria"
  - "EPFL"
  - "Oracle Labs"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764852"
code_url: "https://gitlab.inria.fr/flexguard"
tags:
  - scheduling
  - kernel
  - ebpf
category: datacenter-scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

FlexGuard 把一个用户态锁算法和一个基于 eBPF 的抢占监视器绑在一起：只要调度器把已经处在锁关键路径上的线程抢占走，它就立刻让等待线程停止自旋并转入阻塞。结果是，它在线程数没有超过硬件上下文时能接近高性能 spinlock，而在 oversubscription 时又能避开传统 spinlock 的灾难性性能崩溃。

## 问题背景

这篇论文针对的是多核软件里一个很经典、但一直没被彻底解决的矛盾。纯 spinlock 的优势在于 handover 很快，因为下一个持锁者往往已经在运行；但一旦竞争线程数超过可用 hardware contexts，自旋线程就可能把真正持锁的线程抢占掉。此时机器持续消耗 CPU，却没有推进 critical path，延迟会成数量级爆炸。纯 blocking lock 不会这样，因为等待者会睡眠；但每次有竞争的 handover 都要付出内核唤醒和 context switch 的成本，所以在非 oversubscribed 场景下又明显更慢。

工业界常用的折中方案是 spin-then-park，POSIX lock 和很多研究锁都属于这一类。问题在于，这类设计都必须猜一个“什么时候该停止自旋”的阈值。已有工作会看时间戳是否过期、周期性统计线程数、维护 sleep-slot buffer，或者按 timeslice 做调参。作者认为这些方法的抽象层级不对：调度器本来就知道 critical path 是否真的被打断了，从用户态靠启发式间接推断，注定会在“自旋过多”和“阻塞过早”之间反复失手。

## 核心洞察

论文的核心主张是，锁的等待策略应该响应“真实发生的 critical-section preemption”，而不是响应它的代理信号。通过把 eBPF 挂到 `sched_switch` 上，系统可以在每次 context switch 时检查：被换出的线程是否当前持有某把锁，或者是否正处在 `lock()` / `unlock()` 中那段逻辑上已经属于 critical section 的窄窗口里。只要检测到这种情况，就把一个 system-wide 的计数器加一；当该线程重新运行后，再把计数器减回去。只要这个计数器大于零，锁就应当转入 blocking mode；回到零时，再恢复 busy-waiting。

这个信号之所以关键，有两个原因。第一，它直接处理了 lock-holder preemption，不再需要猜 timeout。第二，它还能处理 queue lock 特有的 next-waiter preemption：如果本该接到下一次 handover 的线程自己也被抢占了，那么继续坚持严格的自旋队列推进只会让所有人卡住。FlexGuard 在这种时候临时放弃自旋式队列 handover，让线程走更简单的阻塞路径。换句话说，scheduler 不再是一个黑盒，而是变成了锁算法的显式输入。

## 设计

FlexGuard 由两部分组成。第一部分是 Preemption Monitor，它是挂在 `sched_switch` 上的 eBPF handler。在线程本地，锁代码维护一个 `cs_counter`：获取锁后递增，释放锁前递减。为了覆盖 `lock()` 和 `unlock()` 内那几个“虽然 `cs_counter` 还没更新，但线程事实上已经持锁”的窗口，作者还在锁实现里加入了 assembly label，并在被抢占时读取保存下来的寄存器值。如果发现被换出的线程落在这些区间内，monitor 就把它标记为“在 critical section 中被抢占”，并递增全局 `num_preempted_cs`；线程恢复运行后再递减。

第二部分是锁算法本身。它把一个简单的 single-word lock 和一条 MCS 队列组合起来。在 busy-waiting mode 下，线程先走一个类似 TATAS 的 fast path；如果有竞争，就进入 MCS 风格的 slow path，让只有队首线程在共享锁字上自旋，其他线程在自己的 queue node 上等待，从而保留 queue lock 的低 cache-coherence 成本。一旦 `num_preempted_cs` 变成正数，算法就切到 blocking mode：线程退出或绕过 MCS 队列，把共享状态标成 `LOCKED_WITH_BLOCKED_WAITERS`，然后通过 `futex_wait()` 睡眠。释放锁时，只在确实存在阻塞等待者时才执行 `futex_wake()`，因此 Futex 开销不会污染无竞争快路径。

这里有两个关键不变量。第一，不管当前等待模式是自旋还是阻塞，互斥性都统一归约为“谁拥有 single-variable lock”。第二，活性来自这样的结构：线程只有在锁状态明确表示“存在 blocked waiters”时才会睡下，而每次释放只要看到这个状态就会发出 `futex_wake()`。作者还特别强调，全局抢占计数器必须是 system-wide，而不能是 per-lock：因为一把锁的等待者完全可能去抢占另一把锁的持有者，释放 CPU 资源也应该按系统整体来做。

## 实验评估

实验覆盖了两个 microbenchmark 和五个真实应用，运行在两台 Linux 6.9 服务器上：一台是 104 hardware contexts 的 Intel 机器，另一台是 512 hardware contexts 的 AMD 机器。共享内存访问 microbenchmark 给出了论文最核心的结果：相对 pure blocking lock，FlexGuard 在 Intel 和 AMD 上分别把 critical-section latency 最多降低了 92% 和 100%，同时又避免了 MCS 在 oversubscription 下出现的数量级性能崩溃。hash-table microbenchmark 则说明，这种性质并不只出现在单锁场景里；在多锁、高线程数下，FlexGuard 仍然能保持稳定，而传统 spinlock 会急剧退化。

应用评估也不是只围着一个有利 workload 打转。在 PiBench 的内存优化 B+-tree index 上，FlexGuard 在非 oversubscription 和 oversubscription 下平均分别达到 POSIX 的 4.2 倍和 3.4 倍吞吐。在 Dedup 上，它分别平均领先 POSIX 24.7% 和 38.3%；这里一个重要原因是它只需要“每线程一个 queue node”，而不是“每线程每锁一个 queue node”。在 LevelDB 上，`readrandom` 平均提升 67% 和 25%，`fillrandom` 平均提升 14% 和 11%。Raytrace 的增益较小，但仍有大约 4% 和 21% 的平均提升。最明显的反例是 Intel 上带并发干扰的 Streamcluster：FlexGuard 最多会比 POSIX 差 82%，因为额外的 runnable spinner 会拖慢 barrier 完成；作者也明确把 barrier 适配列为后续工作。

论文还做了几组解释性分析来支撑中心论点。Hackbench 显示，在一种 context-switch 极其频繁的最坏情形下，Preemption Monitor 给 scheduler 带来的额外开销不到 1%。公平性也不错：在一个最容易频繁切换模式的场景中，FlexGuard 的 fairness factor 仍低于 0.58，和 MCS 接近。runnable-thread 分析则进一步解释了它为什么有效：MCS 会让所有竞争者都保持 runnable，pure blocking 往往又只剩下一个 runnable 持锁者，而 FlexGuard 维持的是“足够快 handover、但又不至于把机器全部耗在自旋上”的中间状态。

## 创新性与影响

这篇论文的创新点不是“又造了一把 hybrid lock”这么简单。FlexGuard 真正改变的是 hybrid synchronization 的控制信号：它不再依赖启发式，而是直接使用 scheduler 反馈。正因为如此，它才能在“自旋是安全的”时候表现得像优秀 spinlock，在“自旋会拖死 critical path”时又精确切回 blocking。相较于 Shuffle lock 或 Malthusian 这类设计，真正新的地方并不是 MCS 加单字锁的结构本身，而是 eBPF 让用户态在不改内核的前提下获得了和锁 handover 直接相关的抢占信息。

这对锁设计者和系统实现者都有意义。论文说明，现代内核已经暴露出足够的可观测性，使得用户态同步原语可以实时感知 scheduler 状态并调整行为。作者也指出，这个思路不应只停留在 mutex：reader-writer lock、condition variable、barrier，甚至更复杂的 delegation lock 和 NUMA-aware lock，都可能复用同样的模式。从贡献类型上看，它是一个新机制，而且具备明确的工程落地方向。

## 局限性

FlexGuard 并不适用于所有环境。它的 monitor 依赖锁实现显式暴露关键程序点，例如用 inline assembly label 标出 `lock()` / `unlock()` 内部区间，并依赖可预测的寄存器使用方式。论文里的实现只覆盖 Linux 和 x86。移植到其他体系结构或操作系统看起来可行，但显然需要额外工程工作，而不是“天然就能跑”。它还要求底层提供 Futex 类原语以及 eBPF scheduler tracepoint。

实验本身也暴露出 workload 边界。FlexGuard 的洞察是“当自旋阻塞了锁进展时，自旋有害”，但 barrier-heavy 程序仍可能因为额外 runnable 线程而受损。Intel 上的 Streamcluster 就清楚展示了这一点。更广泛地说，论文最强的结果都来自 lock handover 真正主导性能的 workload；对于锁只是次要瓶颈的混合型应用，论文提供的信息就少一些。另一个侧面是，timeslice extension 版本有时还能进一步提升性能，这也说明 FlexGuard 本身并没有消除所有 scheduler 引起的损失模式。

## 相关工作

- _He et al. (HiPC '05)_ - MCS-TP 通过陈旧时间戳去推断 lock-holder preemption，而 FlexGuard 直接通过 `sched_switch` 检测被抢占的 critical section。
- _Dice (EuroSys '17)_ - Malthusian lock 依赖启发式 spin-then-park 和 passive list 来减少 runnable waiter；FlexGuard 则是在确认 critical path 已经停住时才阻塞。
- _Kashyap et al. (SOSP '19)_ - Shuffle lock 通过 MCS 加简单锁来降低 cache contention，FlexGuard 借用了这类结构，但把 heuristic parking 换成了 scheduler-driven 的模式切换。
- _Patel et al. (EuroSys '20)_ - u-SCL 通过固定 lock slice 与 scheduler 协作，而 FlexGuard 直接对真实抢占做反应，并在无抢占时保持普通锁 handover 的低延迟。

## 我的笔记

<!-- 留空；由人工补充 -->
