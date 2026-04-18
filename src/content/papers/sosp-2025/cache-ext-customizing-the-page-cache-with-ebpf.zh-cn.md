---
title: "cache_ext: Customizing the Page Cache with eBPF"
oneline: "cache_ext 把 Linux page-cache eviction 变成内核内 eBPF 接口，让每个 cgroup 都能运行适配自身工作负载的策略，而不是被固定的 LRU 风格策略绑定。"
authors:
  - "Tal Zussman"
  - "Ioannis Zarkadas"
  - "Jeremy Carin"
  - "Andrew Cheng"
  - "Hubertus Franke"
  - "Jonas Pfefferle"
  - "Asaf Cidon"
affiliations:
  - "Columbia University"
  - "IBM Research"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764820"
code_url: "https://github.com/cache-ext/cache_ext"
tags:
  - caching
  - memory
  - kernel
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

cache_ext 允许 Linux 在内核里用 eBPF 运行自定义 page-cache eviction 策略。它提供按 cgroup 隔离、以 list 为核心的接口，既能表达 LFU、S3-FIFO 这类通用策略，也能表达按应用语义区分 GET 和 SCAN 的策略，并且在匹配工作负载时明显优于默认 page cache。

## 问题背景

Linux page cache 仍建立在 active/inactive list 组成的 LRU 近似之上。论文认为这对 scan-heavy 访问、混合高优先级小请求与低优先级大扫描的数据库负载、以及更应按频次或应用语义决策的工作负载都不合适；`madvise()`、`fadvise()` 和 MGLRU 也仍被限制在既定的内核策略骨架里，实际帮助有限。

把策略放到 userspace 同样不够便宜。论文测得，一种只通过 eBPF ring buffer 转发 page-cache 事件、并不真正做策略计算的“最佳情况”设计，仍让 YCSB 慢 16.6%-20.6%，文件搜索慢 4.7%。因此核心问题是：怎样在保留内核热路径、租户隔离和指针安全的前提下，让 eviction 可编程。

## 核心洞察

论文最重要的观点是：只要内核继续掌握 mechanism，而对外暴露一个足够窄但足够像“policy”的控制面，page-cache customization 就能真正落地。cache_ext 并不让应用重写 page cache；它只给应用五类回调、由内核维护的 eviction list，以及一个分批“提名候选页”的接口。这个接口既小到足以保住性能、共享与安全，又大到足以表达真实存在的 eviction 算法。

另一个关键点是隔离边界。正确的边界不是“整台机器只跑一个策略”，而是“每个 cgroup 一个策略”，这样不同工作负载就能并存并使用不同规则，同时仍共享 page cache 的好处。

## 设计

cache_ext 的基础选择是把策略代码放在内核内执行。策略通过 `struct_ops` 回调实现，并通过 kfunc 与内核交互。框架暴露五类事件：策略初始化、folio admission、folio access、folio removal，以及 eviction request。这里特意区分“请求 eviction”和“folio 真的被移除”：策略只能提名候选者，最终是否可驱逐仍由内核判断；如果策略给出的候选不足，内核还可以退回默认路径补齐。

它的核心抽象是 eviction-list API。策略可以创建一个或多个可变长度链表，把 folio 插入、移动、删除，或者通过回调遍历链表。`list_iterate()` 支持简单模式和 batch-scoring 模式，因此既能表达 FIFO、MRU 这种简单队列，也能表达 S3-FIFO、MGLRU 这种多队列/多代策略，还能近似实现 LFU、LHD 这类基于分数的策略；频次、代际编号、扫描线程标识等额外元数据则放在 eBPF map 里。

这些 case study 说明接口并不玩具化。S3-FIFO 用两个 list 加一个 ghost queue；MGLRU 用 generation list 和 PID controller；GET-SCAN 按线程身份把页面分流到两条近似 LFU 的 list。LHD 最难，因为它需要周期性重配置和类似浮点的计算，所以 cache_ext 把重配置放到 `BPF_PROG_TYPE_SYSCALL` 路径，并使用定点数近似。隔离方面，作者扩展了 `struct_ops` 以支持 cgroup-specific policy；安全方面，框架维护 valid-folios registry，对每个 candidate 做校验，并提供 fallback。整个原型大约修改了 2000 行内核代码，其中只有约 210 行直接位于核心 page-cache 路径。

## 实验评估

实验运行在 CloudLab 机器上，配置是 16 核 AMD Rome、128 GB 内存、480 GB SSD，以及 Linux 6.6.8。实验覆盖面与论文主张基本匹配：YCSB、Twitter cache trace、scan-heavy 文件搜索、混合 GET/SCAN 工作负载、多 cgroup 隔离场景，以及专门测开销的微基准。

在 100 GiB 的 LevelDB 数据库、10 GiB cgroup 的设置下，cache_ext 的 LFU 相比默认 Linux 策略最高带来 37% 的吞吐提升，并把 P99 读延迟最多降低 55%；LHD 的表现通常也非常接近 LFU。但在 Twitter cache trace 上，没有任何单一策略能够通吃所有 cluster：LHD 在 cluster 34 最好，LFU 在 cluster 52 最好，MGLRU 在 cluster 17 和 18 最好，而默认策略在 cluster 24 反而最好。这个“负结果”很关键，因为它支持论文的核心论点：真正有价值的是 programmability，而不是某个万能算法。

最醒目的 workload-specific 结果来自 Linux 源码树上的文件搜索。对这种重复扫描负载，cache_ext 的 MRU 几乎比默认策略和 MGLRU 都快 2 倍，因为基线的 recency 启发式在这里正好方向相反。应用感知的 GET-SCAN 策略也很有说服力：它把 point query 页和 scan 页分开管理，使 GET 吞吐提升 70%、GET 的 P99 延迟下降 57%，代价是 SCAN 吞吐下降 18%。针对 RocksDB compaction 的 admission filter 也把 P99 延迟再降了 17%，但吞吐几乎不变。

开销结果也让设计显得可信。valid-folios registry 的内存代价是 cgroup 内存的 0.4%-1.2%；在 `fio` 中，一个 no-op policy 带来的 CPU 开销最高只有 1.7%；而用 cache_ext 重写的 MGLRU 在 YCSB 上与内核原生 MGLRU 的差距只有约 1%。隔离实验还说明按 cgroup 定制策略确实有意义：LFU+MRU 的 tailored 组合相对默认基线让 YCSB 提升 49.8%，文件搜索提升 79.4%。不过证据仍主要集中在 file-backed、以 `pread()` 为主的负载，而不是大量 `mmap()` 的场景。

## 创新性与影响

这篇论文的新意不在于提出了一个新的 eviction 算法，而在于提出了一种内核接口设计，使现代 cache-policy 研究可以不依赖专门的 Linux 内核分叉就落地。相较于已有的 page-cache customization 工作，cache_ext 比单队列的 eBPF 方案更有表达力，避免了 userspace delegation 在热路径上的成本，还显式处理了多租户隔离与安全问题。

它对研究者和工程实践者都有意义。研究者可以直接把 LHD、S3-FIFO 或应用特定规则放到 Linux page cache 上试验；工程团队也得到了一条从“默认 page cache 不适合我们的负载”到“写几百行策略代码”的路径，而不是去维护一份深度内核补丁。

## 局限性

cache_ext 并没有证明存在一个更好的默认策略；Twitter trace 的结果恰恰说明不存在这种简单答案。使用者仍然需要挑选或编写与自己工作负载相匹配的策略，而且选错策略会明显伤害性能，YCSB 上的 MRU 就是例子。

它也有明确的技术限制。由于 eBPF 还缺少成熟的通用数据结构与浮点支持，一些策略只能做近似实现；LHD 就需要专门的重配置路径和定点数近似。cgroup 隔离在多个租户共享同一文件时也并不完美，加载策略需要 root 权限，而且实验主要关注 file-backed access，并常常让 LevelDB 使用 `pread()` 而不是 `mmap()`。

## 相关工作

- _Yelam et al. (USENIX ATC '25)_ — PageFlex 同样利用 eBPF 做 Linux paging customization，但它把策略工作委托给 userspace，重点也更偏向 paging 和 prefetching，而不是内核内的 file-cache eviction。
- _Cao et al. (USENIX ATC '24)_ — FetchBPF 让 Linux prefetching 可以被 eBPF 自定义，而 cache_ext 处理的是更难的 eviction 策略、更加复杂的数据结构，以及按 cgroup 隔离的多租户问题。
- _Yang et al. (SOSP '23)_ — S3-FIFO 是操作系统 page cache 之外提出的现代 cache 算法；cache_ext 的贡献在于把这类策略带进 Linux 内核，而不是再发明一个新的默认算法。
- _Beckmann et al. (NSDI '18)_ — LHD 证明了基于概率建模的 eviction 可以优于简单 recency 启发式，而 cache_ext 让这种策略第一次具备了进入 Linux page cache 的现实接口。

## 我的笔记

<!-- empty; left for the human reader -->
