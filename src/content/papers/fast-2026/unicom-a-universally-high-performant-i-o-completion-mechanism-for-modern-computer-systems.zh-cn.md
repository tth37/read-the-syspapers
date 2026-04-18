---
title: "UnICom: A Universally High-Performant I/O Completion Mechanism for Modern Computer Systems"
oneline: "UnICom 把 direct I/O completion 拉回内核，用调度标签、共享 polling 线程和 shortcut I/O path 在低负载时接近 polling，在高负载时避免 busy-wait 抢占 CPU。"
authors:
  - "Riwei Pan"
  - "Yu Liang"
  - "Sam H. Noh"
  - "Lei Li"
  - "Nan Guan"
  - "Tei-Wei Kuo"
  - "Chun Jason Xue"
affiliations:
  - "City University of Hong Kong"
  - "ETH Zurich & Inria-Paris"
  - "Virginia Tech"
  - "Delta Electronics and National Taiwan University"
  - "Mohamed bin Zayed University of Artificial Intelligence"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/MIoTLab/UnICom"
tags:
  - storage
  - kernel
  - scheduling
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`UnICom` 认为，一次 kernel trap 的代价足够小，可以把 I/O completion 放回内核，同时继续绕过大部分传统存储栈。借助 `TagSched`、`TagPoll` 和 `SKIP`，它在 CPU 空闲时接近 polling 的低延迟，在 CPU 紧张时又避免 polling 的 busy-wait 浪费。

## 问题背景

低延迟 NVMe SSD 让软件开销从次要问题变成主要瓶颈。论文引用已有结果指出，在 Optane 级设备上，一个 `4 KB` 读请求里，软件甚至可能占到总延迟的一半左右。现有完成机制因此暴露出明确短板。Polling 在 I/O 线程独占 CPU 时最灵敏，但会把周期浪费在 busy-wait 上；interrupts 节省 CPU，但一旦设备延迟只有几微秒，睡眠、唤醒和中断投递本身就很贵。Table 1 进一步显示，在 ext4 上，单是 interrupt handling 就占了一个 `4 KB` direct read 延迟的大约 `33%`。

作者关心的正是 mixed workloads。真实系统里，存储密集型代码经常与计算密集型线程或进程并行运行，这也是 polling 最容易伤害整体吞吐的场景。论文还认为 `io_uring` 不是同步应用的通用答案，因为它仍受底层 completion 路径约束，跨进程共享能力有限，还会把程序推向异步模型。目标因此很明确：保留 synchronous direct I/O，支持跨进程，并在不同 CPU 负载下尽量逼近 polling 和 interrupts 中更好的那一种。

## 核心洞察

论文最重要的判断是：真正该担心的成本不是“进入内核”，而是进入内核以后沿着旧路径做了什么。作者机器上一次 syscall 约为 `150 ns`，而代表性的 `4 KB` 读请求设备延迟约为 `4010 ns`。这意味着系统完全可以先 trap 到内核，重新利用 scheduler 和 permission infrastructure，然后再绕过传统 I/O stack 里那些真正昂贵的部分。一旦 completion 在内核里，系统就能让 sleeping I/O threads 继续对 scheduler 可见，用轻量状态完成唤醒，并把跨进程 polling 合并起来。

## 设计

`TagSched` 改写了 synchronous I/O thread 的睡眠语义。线程提交 I/O 后不会被真正移出 run queue，而只是把 PCB 标成 `IO-WAIT`；完成到来时再改回 `IO-NORMAL`。为避免 missed wake-up，等待被实现成 decrement，唤醒实现成 increment，因此乱序事件会自然抵消。若完成的 I/O thread 被 compute thread 挡在后面，`TagSched` 还会发送 IPI，让 scheduler 立即重新选择任务。

`TagPoll` 是共享的内核 completion thread，负责替所有 I/O threads 和 processes 轮询 NVMe queues。每个请求都带着提交线程的 PCB 指针，因此 poller 可以在完成时直接标记请求、恢复调度 tag，并在需要时触发抢占。它还会预测下一次 completion 方式：如果某个 I/O thread 独占一颗 CPU，下一次就直接 polling；否则就回到 `TagSched` 的 sleep/wake 路径。

`SKIP` 则负责把请求足够便宜地送到设备。内核模块 `UnIDrv` 管理 NVMe queues，并维护从 file offset 到 physical block 的 per-file extent tree；用户态 `Ulib` 用 `LD_PRELOAD` 截获 direct-I/O 文件操作，再经 `user_io_submit` 转发进去。相较 `BypassD`，这避免了复杂的用户态 permission machinery、静态 queue allocation，以及静态 fmap 的内存开销。

## 实验评估

实验运行在 Linux `6.5.1`、`16` 个 E-cores 和 `Intel Optane SSD P5801x` 上，另用 `Kingston NV3` 做次级检查。比较对 `UnICom` 算是保守的：`BypassD` 可以使用全部 NVMe queues，而 `UnICom` 需要专门拿出一颗核心运行 completion thread。

在纯 I/O 微基准上，`UnICom` 在 `4 KB` random read 上比 ext4 高 `43.5%`，在 `4 KB` random write 上高 `34.9%`，并因 extent-tree 映射更轻而略微超过 `BypassD`。单线程时，它把 ext4 的平均读延迟在 `4 KB` 上降低了 `42%`、在 `128 KB` 上降低了 `17.4%`；在饱和场景里，对 `4 KB` 读请求的 P99 仍比 ext4 低 `31.2%`，同时避免纯 polling 在 `128 KB` 情况下出现的极端尾延迟。

最强的证据来自 mixed workloads。固定 `16` 个 compute threads 时，`UnICom` 的 `4 KB` read IOPS 比 ext4 高 `39.4%`，比 `BypassD` 高 `88.8%`。固定 `16` 个 I/O threads、逐步增加 compute pressure 时，它对 ext4 仍有平均 `33.2%` 的优势，在 `32` 个 compute threads 下则比 `BypassD` 高 `82.7%`。在 RocksDB+YCSB 中，它在单线程下对 `64 B` 和 `200 B` values 分别比 ext4 高 `24%` 和 `28%`，到 `32` 线程时仍保有 `9%` 和 `18%` 的优势。消费级 SSD 上相对 ext4 的收益只剩 `5.3%`，这也印证了作者的判断：该机制最适合软件开销已接近介质延迟的设备。

## 创新性与影响

相对于 `BypassD`，这篇论文的创新并不只是把代码搬回内核，而是利用这次回到内核的机会重新拿回 scheduler coordination、跨进程共享和安全 direct access。相对于 `Cinterrupts` 和 `Aeolia`，它改的是 completion 机制本身，而不是只把 interrupts 做得更便宜。更大的启发是：一次小的 kernel trap，可能比在用户态重建协调原语更便宜。

## 局限性

这个原型只加速 direct I/O，并依赖 `LD_PRELOAD`、定制内核模块，以及文件系统侧的 extent-tree hooks。单个 completion thread 也是明确的扩展上限；按论文估算，它大约在 `1820 KIOPS` 左右会成为瓶颈。Cold open 还需要构建 extent tree，文件有 `4`、`9`、`186` 个 extents 时，延迟分别上升到 `28 us`、`57 us` 和 `146 us`。最后，论文最强的结果仍来自一个基于 ext4 的原型和一块极快的 SSD，因此它更像是在证明 Optane 级设备上的机制有效性，而不是给出所有存储系统的通用答案。

## 相关工作

- _Yadalam et al. (ASPLOS '24)_ — `BypassD` 把 direct file I/O 和 queue access 推到用户态并依赖 polling，而 `UnICom` 把 completion 留在内核里，以便跨进程共享 polling 并在竞争场景下减少 CPU 浪费。
- _Tai et al. (OSDI '21)_ — `Cinterrupts` 主要通过调节 interrupt coalescing 优化小 I/O，而 `UnICom` 直接重做 sleep/wake 机制，并能按线程在 poll-like 与 interrupt-like 行为之间切换。
- _Li et al. (SOSP '25)_ — `Aeolia` 依赖 Intel User Interrupts 来加速用户态存储中断，`UnICom` 则不要求特殊 CPU 特性，而是把普通 kernel trap 当作足够便宜的基础设施来构建。
- _Joshi et al. (FAST '24)_ — `I/O Passthru` 通过 `io_uring` 缩短 Linux NVMe 路径，`UnICom` 则在缩短路径之外，再叠加调度标签、共享 completion thread 和对 synchronous I/O 的透明支持。

## 我的笔记

<!-- 留空；由人工补充 -->
