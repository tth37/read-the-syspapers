---
title: "Hitchhike: Efficient Request Submission via Deferred Enforcement of Address Contiguity"
oneline: "Hitchhike 把多个非连续读请求先合成一个内核请求，只在驱动里再还原成连续 NVMe 命令，从而显著降低提交开销。"
authors:
  - "Xuda Zheng"
  - "Jian Zhou"
  - "Shuhan Bai"
  - "Runjin Wu"
  - "Xianlin Tang"
  - "Zhiyuan Li"
  - "Hong Jiang"
  - "Fei Wu"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, China"
  - "University of Texas at Arlington, Arlington, Texas, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790173"
code_url: "https://github.com/haslaboratory/Hitchhike-AE"
tags:
  - storage
  - kernel
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Hitchhike 的出发点是：Linux 在高并发随机读下吃掉大量 CPU，不只是因为设备快了，而是因为它把“地址必须连续”这个约束从 syscall 一直执行到 NVMe 驱动。论文的办法是让一个内核请求先携带多个非连续 offset 和 buffer，只在驱动层再拆回满足协议要求的连续 NVMe 命令。

## 问题背景

论文抓住的是现代存储系统里一个非常具体、但也非常普遍的矛盾。今天的 NVMe SSD 已经能提供数百万 IOPS，图计算、KV 存储和向量检索这类系统也会持续保持大量 outstanding I/O；但 Linux 只要看到目标地址不连续，就仍然把请求当成彼此独立的小单元处理。于是，同一个 CPU 核心会反复支付请求检查、offset 翻译、bio 构造、buffer pinning、提交和完成回调等成本，软件栈反而成了设备前面的瓶颈。

作者用两组实验把问题量化得很清楚。在 PCIe 5.0 SSD 上，`128 KB` 顺序读用单核、约 `60%` CPU 就能跑满带宽；但 `4 KB` 随机读要吃掉 `2-4` 个核心，而且仅内核 I/O 栈就占了总 CPU 周期的 `80%` 以上。即便四个 `4 KB` 请求最终能在 block layer 里合并成一个 `16 KB` 请求，scatter submission 的提交时间仍然是直接发一个 `16 KB` 请求的 `3.27x`，吞吐只有后者的 `34.2%`。现有 `io_uring`、SPDK 等接口虽然降低了一部分开销，但仍保留“一个连续地址范围对应一个请求”的基本抽象，而旁路路径又会牺牲文件系统语义。

## 核心洞察

这篇论文最重要的洞察是：严格地址连续性真正必需的地方只有设备边界，而不是整个软件栈。文件系统、block layer 和异步提交路径完全可以像 `readv` 处理多段 buffer 一样，先处理一个由多个非连续 offset 组成的向量；只要在真正生成 NVMe 命令之前恢复成连续 LBA 段即可。Linux 之所以多做了很多事，并不是这些层天然必须逐请求工作，而是它们被过早绑到了 NVMe 协议形状上。

这也解释了为什么 Hitchhike 不只是另一个 batching 接口。论文把内核工作区分成两类：一类和具体地址绑定，仍然要按 offset 逐项迭代；另一类与单个地址无关，现在可以对整组请求只支付一次。作者还用 Amdahl-law 模型定量说明收益来源：在 `4 KB` 随机读案例里，用 `beta = 0.7275`、`K = 0.8` 和 merge size `64` 预测出 `2.34x` 加速，实测是 `2.29x`。

## 设计

Hitchhike 引入了新的提交抽象 `hio`。一个 `hio` 可以把多个普通请求，也就是论文所说的 hitchhikers，合并起来，只要它们指向同一个 file descriptor。每个被合并的请求贡献自己的 offset 和 buffer，因此一个 Hitchhike 请求同时携带 offset vector 和 buffer vector。这个约束是有意保守的：不同文件可能对应不同命名空间或文件系统路径，所以 Hitchhike 只在同一个 `fd` 内合并，在文件分散时就退化成多个小组甚至普通 I/O。

进入内核后，Hitchhike 通过标志位区分普通请求和 Hitchhike 请求。访问检查、offset 到 sector 的翻译、DMA 映射以及 tag 分配都按向量逐项执行；而请求检查、bio 准备、bio 提交等步骤则对整组请求只做一次。真正关键的是驱动里的 deferred metadata binding：驱动把前面向量化得到的 DMA 地址、LBA 和 tag 重新一一匹配，再生成若干条标准 NVMe 命令，各自写入 submission queue。完成路径也采用同样思路，子命令先释放各自资源，但完整回调要等整组 hitchhikers 都完成后才统一触发。

实现上，作者把 Hitchhike 集成进了 `libaio`、`io_uring`、FIO、Blaze 和 LeanStore。由于 `libaio` 的 `iocb` 只有 64 字节，系统引入 `struct hitchhiker` 保存 offset 元数据；`io_uring` 则增加了新的 flag 和共享内存支持。当前实现明确聚焦于异步、direct-I/O、读密集场景。

## 实验评估

论文的实验与核心论点是对得上的。平台使用 Linux `6.5`、两颗 Xeon Gold 6430，以及三块 NVMe SSD，大多数结果基于 Dapustor H5300。最关键的工作点就是高并发 `4 KB` 随机读，参数实验显示 merge size 到 `64`、且 Hitchhike request concurrency 至少为 `4` 时效果最好；而 queue depth 低于 `8` 时收益很小，因为几乎没有足够的请求可供合并。

在 raw block path 上，最醒目的数字是单线程 `hitchhike-uring` 达到 `2.8 M` IOPS，而 `libaio` 是 `0.8 M`，`io_uring-fb` 是 `1.1 M`，`io_uring_cmd-fb` 是 `1.3 M`，SPDK 大约是 `2.0 M`。论文还声称饱和 NVMe 带宽所需 CPU 核数最多可减少 `75%`。文件路径上的收益没那么夸张，但仍然很实在：在 H5300 上，`hitchhike-uring` 达到 `1.6 M` IOPS，相比 `libaio` 提升 `2.6x`，相比 `io_uring` 提升 `2.3x`，相比 `io_uring-fb-iopoll` 也有 `1.5x`。底层开销测量也能对上机制本身：平均提交延迟降到 raw `169 ns`、file `315 ns`，中断处理时间降到 `226 ns`。真实应用里，Blaze 端到端执行时间下降 `30-66%`，LeanStore 在 YCSB A/B/C/F 上提升 `17-34%`。我认为这足以支撑论文对“读密集、高 queue-depth、异步存储引擎”场景的主张；这里的场景限定是我根据实验设置做出的概括，不是论文原句。

## 创新性与影响

和 SPDK、I/O Passthru 这类 bypass 路线相比，Hitchhike 的新意在于它不逃离标准内核栈，而是修改“请求抽象”本身。和那些优化队列调度、中断处理或 block layer 组件的论文相比，它更早一步地追问：为什么上层软件栈非得坚持“一个连续 offset 范围对应一个请求”？

因此，这篇论文最可能影响的是做存储引擎、图系统以及 Linux 高 IOPS 路径优化的人。即使后续系统不直接照搬 `hio` 这个接口形状，“只在真正需要协议约束的层上强制连续性”这个思路本身也很可能被复用。

## 局限性

这个设计的边界是明确的。Hitchhike 只合并同一 file descriptor 上的请求，因此一旦 workload 把请求分散到很多文件，merge 机会就会迅速下降，最后退化成普通 I/O。它的最佳效果还依赖足够深的 queue depth 和足够多的同文件 outstanding requests；论文自己也显示 queue depth 低于 `8` 时收益不明显。

实现范围同样比概念本身更窄。当前版本聚焦异步 direct I/O，且主要优化读请求。Buffered I/O 被留到未来工作，因为 page cache 会引入另一组复杂策略问题；另外，虽然 Hitchhike 在高 queue depth 下的吞吐超过了 SPDK，但在多线程扩展时，SPDK 的延迟保持仍然更好，因此 Hitchhike 并不是所有低延迟部署场景里的通用替代品。

## 相关工作

- _Yang et al. (CloudCom '17)_ — SPDK 通过把存储栈搬到用户态来消除内核开销，而 Hitchhike 保留内核语义，通过在标准栈内合并非连续请求回收这部分效率。
- _Zhong et al. (OSDI '22)_ — XRP 通过 eBPF 把存储函数塞进内核旁路路径，Hitchhike 则通过改变提交单元本身来处理同样的高开销问题，而不是新增一条旁路。
- _Joshi et al. (FAST '24)_ — I/O Passthru 为 block device 暴露更直接的 `io_uring` 到驱动路径；Hitchhike 则仍然支持经过文件系统，并重点消除驱动之上的逐请求重复工作。
- _Hwang et al. (OSDI '21)_ — Rearchitecting Linux Storage Stack 优化的是若干具体存储栈组件，而 Hitchhike 修改的是导致随机读重复工作的端到端请求模型。

## 我的笔记

<!-- 留空；由人工补充 -->
