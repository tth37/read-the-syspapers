---
title: "CXLMC: Model Checking CXL Shared Memory Programs"
oneline: "CXLMC 把约束细化式模型检测扩展到 x86-CXL 共享内存，可系统性探索单机崩溃与缓存回写缺失导致的数据丢失。"
authors:
  - "Simon Guo"
  - "Conan Truong"
  - "Brian Demsky"
affiliations:
  - "University of California, Irvine"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790150"
code_url: "https://github.com/uciplrg/cxlmc-evaluation.git"
tags:
  - disaggregation
  - memory
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CXLMC 是一个面向 x86-CXL 共享内存程序的崩溃一致性模型检测器。它的核心做法是把 Jaaru 一类的 cache-line constraint refinement 搬到 CXL 的部分失效场景里：单台机器可以在其他机器继续运行时崩溃，而且远端读取本身还可能触发共享内存回写。论文在改造后的 RECIPE 和 CXL-SHM 基准上找到了 24 个 bug，同时把大多数检查成本压在秒级，最慢案例也控制在一分钟以内。

## 问题背景

CXL 共享内存让“跨多台机器共享一片一致性 DRAM”看起来像是可编程的共享堆，这对共享索引、分配器、对象存储和协调数据结构都很有吸引力。但它底下的失效模型比普通共享内存难处理得多。若某个计算节点在脏 cache line 写回前崩溃，最新的 store 可能只存在于该节点缓存中，于是这些写入会直接丢失。一个节点出错，就可能把整个集群共用的数据结构打坏。

这和持久内存看似相近，论文却强调现有 PM 工具并不够用。PM 典型地假设整机失效，而 CXL 的关键情形是部分失效：一台机器死掉，其他机器继续运行，甚至可能一边运行一边执行恢复逻辑。CXL 还改变了可见性规则，因为远端 load 可能迫使 cache line 写回，这意味着“读取”也会缩小哪些写入已经持久化的可能空间。若直接暴力枚举所有崩溃后缓存状态，状态空间会爆炸，尤其因为任意时刻都可能有任意子集的机器失效。于是，这个问题既比传统 crash testing 更分布式，也更依赖底层内存语义。

## 核心洞察

论文最重要的观点是：无需显式枚举每个崩溃后 cache 内容，只要追踪“最近一次写回可能发生在什么时间区间内”，就能惰性地探索 CXL 崩溃状态。对每个 cache line，CXLMC 维护一个 write-back 时间约束；flush 给出下界，而崩溃后的 load 会根据读到的值继续收紧这个区间。

真正关键的是，这个约束必须按机器区分，而不是像 PM 那样按全局执行阶段区分。因为 CXL 的失败是逐机发生的，某台机器失效时丢的是它自己的缓存，而不是全系统一起掉电。CXLMC 还把远端读取视为语义上会“改变状态空间”的事件：远端读取可能触发 cache coherence 回写，所以 read 不是被动观察，而是主动改变哪些崩溃后状态仍然可行。正是这一步，让原本适用于 persistent memory 的 constraint refinement 真正适配了 CXL。

## 设计

CXLMC 的工作流是先用 LLVM pass 改写 C/C++ 程序，把内存访问、fence 和 flush 都替换成进入模型检测器的调用，然后在运行时模拟 x86-TSO 与 CXL 共享内存。每台 CXL 机器对应一个独立进程，各自保留本地地址空间；共享内存区域则映射到所有 fork 出来的进程中。单个进程内部还能再调度多个线程，系统也会拦截相关 `pthread` 操作，并在上下文切换时保留线程本地存储。

内存模型模拟紧贴论文的 x86 目标语义。每个线程都有 store buffer 和独立的 flush buffer，用来实现 `store`、`clflush`、`clflushopt`、`sfence`、`mfence` 的排序规则。所有全局可见的 store 都以“值、序号、来源机器”三元组记录下来。对每条 cache line，检测器维护“最近一次写回可能发生的时间区间”。普通 `clflush` 会直接推进下界；`clflushopt` 则被拆成入队和稍后提交两个阶段，以保留它更弱的重排语义。

算法核心是 read-from 集合构造与 failure exploration。`BuildMayReadFrom` 会先在当前 failed-machine 集合下枚举候选 store；如果某台失败机器的 cache-line 约束意味着更早的 store 仍然可能影响本次读取，它就把该机器递归纳入考虑。某个 load 一旦解析到具体 store，`DoRead` 就会据此收紧对应的 cache-line 区间，让后续读取保持一致。外层的 `Explore` 则在“提交缓冲中的操作”和“执行程序下一步”之间交替前进；当某个 flush 跨过一个仍属于存活机器的 store 时，CXLMC 会分叉出“该机器在此刻失效”的执行。这本质上是在做一种面向崩溃可观察差异的 DPOR，而不是提前把所有缓存状态都展开。

实现层面的工作也不只是把伪代码写出来而已。因为目标程序本身是多进程的，CXLMC 需要在多个 fork 之间做确定性调度、在用户线程切换时保存 TLS，并提供 failure-aware 的 mutex 语义，让从 PM 基准改来的代码可以在持锁进程崩溃后自动释放锁。这些工程细节决定了它不是一个停留在算法草图上的工具。

## 实验评估

实验用了两类基准。第一类是 6 个改造后的 RECIPE 持久内存索引；`P-HOT` 因 LLVM 无法编译被排除。第二类是来自 CXL-SHM 的 2 个 benchmark。作者还解释了为何需要改造 RECIPE，例如给锁记录进程拥有者，以便在部分失效后释放锁。这个评测集合更像“面向 bug 暴露的工作负载”而不是成熟应用套件，但对验证工具是否有用是合适的。

最重要的结果当然是找 bug。CXLMC 在 RECIPE 派生基准中报告了 22 个 bug，在 CXL-SHM 中又找到 2 个。论文特别指出，它不只是抓到“缺 flush”这种老问题，还挖出了更有代表性的错误：`FAST_FAIR` 的 padding 错误、`P-ART` 中计数字段非原子更新和 N16 flush 错误、`P-MassTree` 里只会在部分失效模型下出现的恢复漏洞，以及 CXL-SHM 中未实现的 free 路径和除零错误。作者还说明他们采用的是“发现 bug、修复、再重跑直到不再报错”的迭代流程，这很符合模型检测器的实际使用方式。

性能部分规模不大，但信息量足够。对固定的 RECIPE 配置，使用 2 个进程、每进程 2 个线程、共 10 个 key，CXLMC 在无 GPF 模式下探索 `20` 到 `4128` 个执行，总耗时 `0.03s` 到 `42.96s`；在 GPF 模式下则是 `15` 到 `4119` 个执行，最长 `44.6s`。这些数字支持了论文一个比较克制的主张：惰性约束细化确实把状态爆炸压到了可以交互使用的程度。不过评估的边界也很明显，没有可对比的 CXL 检查工具，性能输入很小，而且真实的 CXL 3.x 硬件还没有普遍可用。

## 创新性与影响

相对 _Gorjiara et al. (ASPLOS '21)_，CXLMC 的新意在于把 cache-line constraint refinement 从“整机崩溃的 persistent memory”推进到“逐机崩溃且远端读取会触发写回的 CXL”场景。相对分布式系统里的 fault injection 工作，它的关键变化是把共享内存缓存状态而不是消息轨迹当成搜索对象。相对大量 CXL 系统论文，它补上的是一个它们往往默认存在、却很少真正实现的正确性调试工具。

因此，这篇论文的影响面不会是“所有 CXL 论文都会引用”，但在一个很具体的子方向里会很重要。凡是打算在 CXL 共享内存上构建 allocator、索引或者协调数据结构的工作，都很可能把它视为该领域正确性工具的起点。后续关于 CXL 编程模型、部分失效容错运行时、以及更强语义验证工具的论文，也都有理由从这里接上去。

## 局限性

CXLMC 为了可扩展性刻意收窄了范围。它只针对 x86-TSO，假设单个共享内存设备，不处理混合架构共享，也不覆盖远端持久内存。它检查的正确性条件也比较弱，主要是程序崩溃或已有断言失败，而不是像 linearizability 这类更高层语义，除非 benchmark 自己把这些性质编码成断言。它也不系统探索并发调度非确定性，而是对固定 schedule 探索崩溃非确定性，再靠不同随机种子补充其他交错。

实验也没有回答“大型真实应用会怎样”这个问题。基准大多是改造后的微基准，不是生产级 CXL 服务，而且性能表是在 bug 都修掉之后测的。memory poisoning 虽然被实现成一个可选项，但因为作者没有合适应用，所以没有真正评测。另一个小问题是论文对“new bug”数量的叙述和表格标注并不完全一致；这不影响方法本身，但会让结果呈现显得稍微不够严谨。

## 相关工作

- _Gorjiara et al. (ASPLOS '21)_ — Jaaru 提供了 persistent memory 的约束细化模板，而 CXLMC 把它推广到部分机器失效和多进程 CXL 程序。
- _Lantz et al. (USENIX ATC '14)_ — Yat 对 persistent memory 采用崩溃后状态的急切枚举，CXLMC 正是要避免这种在 CXL 下更不可扩展的做法。
- _Zhang et al. (SOSP '23)_ — CXL-SHM 展示了部分失效容忍的 CXL 内存管理系统，而 CXLMC 证明这类软件已经需要专门的 bug-finding 工具。
- _Assa et al. (ASPLOS '26)_ — CXL0 给出面向 CXL 分解式内存的语义模型，CXLMC 则补上面向 x86-CXL 程序的可执行模型检测。

## 我的笔记

<!-- 留空；由人工补充 -->
