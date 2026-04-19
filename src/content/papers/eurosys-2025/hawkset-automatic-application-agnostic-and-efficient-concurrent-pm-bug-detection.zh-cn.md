---
title: "HawkSet: Automatic, Application-Agnostic, and Efficient Concurrent PM Bug Detection"
oneline: "HawkSet把 concurrent PM bug detection 从追逐稀有调度，改成分析 unpersisted data 的生命周期，因此一次有覆盖的执行就能更稳定地抓到 race。"
authors:
  - "João Oliveira"
  - "João Gonçalves"
  - "Miguel Matos"
affiliations:
  - "IST Lisbon & INESC-ID"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717477"
code_url: "https://github.com/Jonyleo/HawkSet-exp"
tags:
  - persistent-memory
  - formal-methods
  - fuzzing
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HawkSet 的核心做法，是把 concurrent PM bug 看成一个值在「已经可见、但还没 durable」这段时间里的保护失效，而不是非得等工具亲眼撞上某次坏调度。它用 binary instrumentation、PM-aware lockset analysis、vector clock 过滤和 Initialization Removal Heuristic，在与 PMRace 重叠的应用上重现其已知 bug，并在 P-Masstree、P-ART 上命中与 DURINN 相同的操作，再额外找出 7 个新 bug；在 Fast-Fair 上，相比 PMRace 的 time-to-race 最多快约 159x。

## 问题背景

Persistent Memory 最麻烦的一点，不是写入慢，而是可见性和持久性脱钩。一个 store 进了 cache 之后，别的线程已经能读到；但如果还没经过正确的 `flush` 和 `fence`，崩溃之后这个值仍可能消失。于是就会出现一类很 PM 特有的并发错误：消费者线程已经根据新值做了动作，可生产者线程的写入却没有真正落盘，crash 后只留下副作用，不留下原因。

现有办法各有短板。传统 race detector 不懂 PM 语义，只会看 store 当下有没有被锁保护，却不会把分析窗口延长到 persist 或 overwrite 之前。PMRace 和 DURINN 这类 concurrent PM 工具虽然懂 durability，但它们依赖 key-value-store 级别的语义、定制驱动、或者反复执行去「撞到」具体 interleaving。这样一来，工具既不够通用，也很难在大工作负载里高效地把难复现 bug 稳定挖出来。

## 核心洞察

论文最重要的判断是：persistency-induced race 的边界不在 store 指令本身，而在 unpersisted value 的整个生命周期。只要一个值已经对其他线程可见，但在某个时刻之前还不能保证 crash 后保留，那么这整段区间都该被当成危险窗口来分析。

一旦这么定义，lockset analysis 就重新变得有用。作者引用的观察是，PM access 只占全部内存访问的大约 4%，因此只盯住 PM access 做更重的分析是可承受的。真正要补的是三件事：让 lockset 能表达 store 到 persist 的生命周期；过滤掉实际上不可能并发的跨线程访问；再把初始化阶段常见但无害的伪冲突压掉。

## 设计

HawkSet 用 Intel PIN 做 binary instrumentation，主体大约 2600 行 C++。执行时它记录 PM 的 load、store、flush、fence，以及线程创建、join 和同步原语。内部有一个 memory simulation，用最保守的模型看待持久化：只有显式 `flush` 再加 `fence`，数据才算真的 durable。这个假设故意不依赖 eADR 一类额外硬件能力。

真正的新抽象叫 `effective lockset`。普通 lockset 只看 store 发生时拿着哪些锁；HawkSet 则把 store 的 lockset 与后续 persist 时的 lockset，或者覆盖该值的 overwrite store 的 lockset 取交集。这样得到的，才是从值变得可见到值真正 durable 期间一直在生效的保护。为了防止同一把锁被中途释放又重新获取而误判成连续临界区，系统还给 lockset 加了 thread-local timestamp，每次 acquire 就递增。

光有这个还不够，因为很多访问对虽然锁集不相交，实际上根本不会并发。为此 HawkSet 再用 vector clock 跟踪 thread creation、PM access 和 join，只把 truly concurrent 的 store/load 对送进后续分析。接着它应用 Initialization Removal Heuristic：某个 PM 地址在第一次被第二个线程访问前，都近似视为还没发布；但只有那些在发布前已经显式持久化的初始化 store 才会被丢弃。这个细节很关键，因为如果对象指针先被发布、初始化后持久化，那恰恰可能是真 bug。

最后一步是把不同线程里访问同一 PM region 的 store 和 load 配对；若两者并发，且 store 的 `effective lockset` 与 load 的 lockset 交集为空，就报告 persistency-induced race。实现里还处理了部分重叠访问，并给双方都保存 backtrace，方便开发者回看。

## 实验评估

评测覆盖 9 个 PM 应用，包括树、哈希表、learned index、Memcached-pmem 和 MadFS，硬件是一台 128-core Xeon 加 1 TB Intel DCPMM 的机器，工作负载最多到 100k operations、8 个线程。结果上，HawkSet 共报出 20 个 persistency-induced race，其中 7 个此前未知；论文明确说，它在与 PMRace 重叠的应用上找回了对方已知 bug，并在 P-Masstree、P-ART 上命中了 DURINN 报告过的同类操作，但没有把后者表述成严格的一一对应 race match。

最有说服力的是和 PMRace 在 Fast-Fair 上的对比。用 PMRace 自带的 240 个 seed，HawkSet 每个 workload 平均只跑 6.65 秒，而 PMRace 每次都吃满 600 秒上限。对一个已知 Fast-Fair race，论文给出的 expected time-to-race 改善约为 159x。更关键的是，HawkSet 还能报出 PMRace 抓不到的那个新 Fast-Fair bug，因为后者需要撞上非常具体的 edge-case insertion interleaving，而 HawkSet 不要求直接观察到那次调度。

性能方面，结论也算扎实而克制。端到端测试时间随工作负载增长是次线性的，最大 100k-operation 实验只比 3 分钟多一点；峰值内存大约 4 GB。误报仍然存在，但 IRH 的效果明显：它在 Fast-Fair、MadFS、P-Masstree、P-ART 上把 false positive 全部剪掉，在另外几类程序上也能去掉大部分；唯独 Memcached-pmem 依旧噪声较大，因为安全的 PM region reuse 会被近似模型看成错误发布。

## 创新性与影响

HawkSet 的新意不只是把 lockset 套到 PM 上，而是把分析对象从「一次 store」改成「一个值从 visible 到 durable 的整段生命周期」。再叠加 vector clock 过滤与初始化启发式之后，经典的并发分析技术就被改造成了一个真正能处理 concurrent PM bug 的检测器。

这篇论文的影响也比较直接。对 PM 系统开发者来说，它提供了一个更接近 binary-level、对应用语义依赖更小的调试入口，不必像 PMRace 或 DURINN 那样围着 key-value-store 抽象打转。对研究者来说，它把 persistency-induced race 这个 bug class 的边界讲清楚了，这个视角未来也很可能继续适用于 CXL 一类新的 persistent tier。

## 局限性

HawkSet 仍然强依赖 coverage。某段 PM access 如果 workload 根本没跑到，工具就不可能报告对应 race。它也只负责报告 race，不做语义级验证，因此在 lock-free 设计里会产生不少 benign race，需要人工判断是否真的会破坏正确性。论文自己也承认，这类噪声在部分 lock-free 结构上很明显。

IRH 也不是万灵药。只要程序会重用 PM region，先前已经被视为「发布过」的地址后来重新初始化时，就可能继续触发 false positive；Memcached-pmem 正是这个例子。作者没有进一步去 instrument PM allocator，因为那会把工具绑死在具体分配接口上，削弱 application-agnostic 的目标。最后，HawkSet 也不是绝对零配置：PM 文件路径需要提供，遇到自定义同步原语或基于 CAS 的并发控制时，仍可能要补一份小配置文件或 wrapper。

## 相关工作

- _Chen et al. (ASPLOS '22)_ - PMRace 依赖 fuzzing 和 delay injection 去直接观察 PM inter-thread inconsistency，而且基本局限在 key-value-store 风格的工作负载；HawkSet 则靠 PM-aware lockset reasoning 从一次 trace 里就能推出候选 race。
- _Fu et al. (OSDI '22)_ - DURINN 会把执行提升到 operation 级，再用 breakpoint 强行制造 adversarial interleaving 来检查 durable linearizability；HawkSet 的分析粒度更低，直接落在 PM access 上，不依赖高层操作语义。
- _Savage et al. (TOCS '97)_ - Eraser 给出了经典的 dynamic lockset race detection，而 HawkSet 可以看作把这套思路延长到了 persistence lifetime，再补上 timestamp 和 vector-clock pruning。
- _Fu et al. (SOSP '21)_ - Witcher 关注的是 NVM key-value store 的 crash consistency testing，本身并不理解并发；HawkSet 处理的则是只有在 visibility 和 durability 脱钩时才会出现的那类错误。

## 我的笔记

<!-- 留空；由人工补充 -->
