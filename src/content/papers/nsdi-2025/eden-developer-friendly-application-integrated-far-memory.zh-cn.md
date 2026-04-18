---
title: "Eden: Developer-Friendly Application-Integrated Far Memory"
oneline: "Eden 只在少数高频 fault 点加 hint，让大多数 far-memory miss 走用户态 fast path，并用 read-ahead 与 priority reclaim 逼近 AIFM 的效果。"
authors:
  - "Anil Yelam"
  - "Stewart Grant"
  - "Saarth Deshpande"
  - "Nadav Amit"
  - "Radhika Niranjan Mysore"
  - "Amy Ousterhout"
  - "Marcos K. Aguilera"
  - "Alex C. Snoeren"
affiliations:
  - "UC San Diego"
  - "Technion, Israel Institute of Technology"
  - "VMware Research"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/eden-farmem/eden"
tags:
  - memory
  - disaggregation
  - kernel
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Eden 只要求开发者在少数会产生大多数 far-memory fault 的位置加入 hint。借助这些 hint，系统能在用户态发起取页、用 Shenango 用户线程隐藏 RDMA 延迟，并把 read-ahead 与 eviction priority 直接挂到访问点上。论文报告它比 Fastswap 快 19.4%-178%，并在不少场景下逼近 AIFM。

## 问题背景

far memory 长期卡在两个都不理想的极端之间。像 Infiniswap、Fastswap、Hermit 这样的透明 paging 系统几乎不要求应用修改，本地访问也便宜，因为 guarding 交给了硬件页表和 TLB；但 miss path 很重，page fault 要先 trap 到内核，光 fault 处理就大约 1 微秒，作者的 RDMA 集群里真正远程取页还要再花 5-6 微秒。Fastswap 因此会 busy-wait，而且内核只看得到 page 粒度，很难表达应用特定的 prefetch 与 reclaim。

AIFM、Carbink 这样的 app-integrated 系统则把内存管理移到用户态并按 object 粒度工作，从而避开不少 fault 开销，也能直接利用数据结构知识；代价是开发者要改用 remotable pointer、在很多位置插 software guard，并在本地命中时继续支付 guard 成本。TrackFM、Mira 这类编译器方案虽然减轻了手工移植，但仍然需要广泛插桩。Eden 的经验观察是：性能关键的 fault 点其实很稀疏。对 22 个应用的分析显示，中位数只需 12 个代码位置就能覆盖 95% 的 fault，这让“稀疏标注”的中间路线成为可能。

## 核心洞察

Eden 的核心命题是：software guard 只要放在那几个真正高价值的 fault 点上，就已经足够。它不是像 AIFM 那样包住所有潜在的远程 dereference，而是只在通常会触发 page fault 的热点位置放 hint。hint 至少提供地址和写权限需求，扩展字段 `rdahead`、`ev_prio`、`seq` 则用来表达简单但高价值的应用知识。

这样一来，hint 触发时运行时就能在硬件 page fault 发生前，于用户态检查 page metadata、提前发起 RDMA 取页，并在等待期间切去跑别的 Shenango 用户线程。至于其他位置，程序仍然使用普通 page-based 内存，因此本地访问不必承担 object-based guard 的常驻成本。

## 设计

Eden 构建在 Shenango 之上，包含若干 application core 和一个 dedicated control core。应用核心执行轻量级用户线程并发出 `hint_fault(...)`。runtime 收到 hint 后会先把地址对齐到 page，检查每页 metadata；若页面已在本地就直接返回，若页面缺失则阻塞当前线程、发起 RDMA read、切去运行别的线程，数据回来后再用 `UFFDIO_COPY` 映射页面；若只是缺少写权限，则通过 `UFFDIO_WRITEPROTECT` 放开。

unhinted fault 仍可能出现。Eden 把内存注册到单个 `userfaultfd` 上，由 control core 处理真实的硬件 fault 事件。每页 metadata 会记录 presence、dirty、lock 和正在处理该 fault 的 core ID。页锁保证同一页的并发 fault 只真正取一次数据，fault stealing 则用来处理死锁与负载不均。

reclaim 同样是混合式的。Eden 支持 default、second-chance、LRU 和 priority reclaim。脏页会先被 write-protect，再复制、RDMA 回写，最后用 `madvise(MADV_DONTNEED)` 移除。由于 Linux 原生接口主要擅长 batch 连续区间，Eden 另外实现了向量化的 `UFFDIO_WRITEPROTECT` 与 `madvise`，让离散页面也能在一次内核切换和一次 TLB flush 中批量回收。

## 实验评估

评估运行在三台 100 Gbps 服务器上，端到端测试了 DataFrame、synthetic Web service、Memcached 和 parallel sort，并辅以微基准。开发者成本部分很具体：DataFrame 只需 11 条单行 hint 就覆盖了 97.3% 的 fault，而 AIFM 版本曾修改 1,192 行代码。更广泛的 22 应用分析里，作者报告只需 2-32 个 hint 就能覆盖 95% 的 fault。

DataFrame 上，Eden 在 fully local 情况下约有 12% 的额外开销，而 AIFM 约为 30%，因为 Eden 避开了 remotable pointer 的常驻检查成本。在 22% 本地内存时，向量化 eviction 加上定向 read-ahead 把 Eden 的归一化运行时间降到 1.75x baseline，接近 AIFM 的 1.67x，并且比 Fastswap 好 37%。在 synthetic Web service 上，priority reclaim 能保护热 hash-table 工作集，使 Eden 相比 Fastswap 获得论文中最大的 178% 收益，并在大约 40% 以上本地内存时与 AIFM 保持接近。

论文也明确展示了 Eden 的弱点：当工作集由极小对象组成且缺乏空间局部性时，page 粒度会造成明显的 I/O amplification，Eden 在最缺内存的 synthetic 设置下就落后于 AIFM。Memcached 则说明另一个 regime：用户态 latency hiding 比 object 粒度更重要，10% 本地内存时 Eden 达到 1.31 MOPS，而 Fastswap 只有 0.54 MOPS，提升 104%。微基准也支持设计本身：向量化 write-protect 与 unmap 吞吐提高约 5.4-6.6 倍和 3.7-5.7 倍，hinted fetch 吞吐则比 Fastswap 高 38-88%。所以这组实验很有说服力，但它最强的证据仍然集中在热点路径明显、或带有扫描结构的 workload 上。

## 创新性与影响

Eden 的贡献是把两类看似对立的方案连接起来：一边是透明 paging，另一边是 object-based app integration。与 Fastswap 相比，它把常见 miss path 前移到用户态，并允许访问点直接携带策略信息；与 AIFM 相比，它保留了 page-based 编程模型，只要求少量热点标注，而不是重写数据结构。

这种 framing 很有价值。它把 far memory 的争论从“透明还是集成”改成了更具体的问题：少数高信息量访问点究竟能回收多少收益？这会对 memory disaggregation、hybrid paging/runtime 系统和稀疏自动插桩工具都有参考意义。

## 局限性

Eden 不是透明系统。开发者仍要跑 tracing tool、识别热点 fault 点并添加 hint；如果 fault 行为分散、会随 workload 大幅变化，或者热点主要藏在看不见源码的库里，Eden 的优势就会下降。

更深层的限制来自 page 粒度。小对象、弱局部性的 workload 会遭遇 cache amplification 和 network I/O amplification，synthetic Web service 已经说明了这一点。此外，Eden 的 miss path 仍受制于内核页表和 `userfaultfd`，因此 unhinted path 会慢于纯 app-integrated 系统，某些情况下甚至会慢于其他 paging 方案。最后，AIFM 与 TrackFM 的比较主要是跨 artifact 环境的归一化结果，不是完全同硬件 head-to-head。

## 相关工作

- _Ruan et al. (OSDI '20)_ - AIFM 同样把 far memory 暴露给应用，并支持应用特定策略，但它依赖 remotable pointer 与遍布程序的 software guard；Eden 则保留 paging，只在热点 fault 点上放稀疏 hint。
- _Amaro et al. (EuroSys '20)_ - Fastswap 代表透明 paging 这一端的设计；Eden 继承了 page-based 兼容性，但通过 hint 让大量 miss 在进入内核前就由用户态先处理。
- _Qiao et al. (NSDI '23)_ - Hermit 用 feedback-directed asynchrony 改善透明 far memory，而 Eden 则接受少量开发者标注，以换取更低 miss 开销和更直接的策略输入。
- _Tauro et al. (ASPLOS '24)_ - TrackFM 用编译器插入 software guard 来自动化 app integration，但它仍然需要在大量 dereference 上付出 local-access 开销，这正是 Eden 想避免的成本。

## 我的笔记

<!-- 留空；由人工补充 -->
