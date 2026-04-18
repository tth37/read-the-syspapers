---
title: "CEtoFS: A High-Performance File System with Host-Server Collaboration for Remote Storage"
oneline: "CEtoFS 把远端 NVMe SSD 的数据路径搬到用户态，并把权限检查、并发控制和原子写日志下沉到存储服务器。"
authors:
  - "Wenqing Jia"
  - "Dejun Jiang"
  - "Jin Xiong"
affiliations:
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences"
  - "University of Chinese Academy of Sciences"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - filesystems
  - storage
  - rdma
  - disaggregation
  - crash-consistency
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`CEtoFS` 面向通过 `NVMe-over-RDMA` 访问的解耦式 NVMe SSD。它把元数据管理留在内核文件系统里，但把数据路径放进用户态，并让目标端存储服务器负责按块权限检查、冲突请求排序和原子写的 redo logging。这样做既去掉了发起端厚重的内核栈，也把原本浪费在主机锁串行上的网络等待时间转化成了目标端可并行处理的工作。

## 问题背景

这篇论文的出发点是：当 NVMe SSD 和 RDMA 网络都进入个位数微秒量级时，文件系统软件栈不再是可以忽略的固定成本。作者在远端 Optane SSD 上测量 `Ext4`，发现端到端读写延迟中约 `65%` 到 `66%` 来自软件栈，而仅 `NVMe-over-RDMA` 驱动本身就占了 4 KB 写延迟的 `36.1%`。也就是说，访问远端块设备时，瓶颈已经从“设备太慢”变成了“主机内核路径太长”。

远端存储还会放大本地文件系统原本就存在的两个问题。第一，inode 级别锁在主机端串行化冲突访问；每个后继请求不仅要等前一个请求完成 SSD 服务，还要等命令发送和完成通知跨越网络返回，因此网络时延会直接扩大锁等待成本。论文里的实验甚至显示，线程数增加时远端共享文件写吞吐会下降。第二，失败原子写依赖 journaling 或 copy-on-write。放到远端 SSD 上以后，两者都意味着额外跨网络搬运数据：journaling 先远程写日志，再读回日志做 checkpoint；copy-on-write 则会触发频繁的元数据更新。于是，真正的问题不是“让文件系统能访问远端 NVMe”，而是“让权限、并发和原子性机制在微秒级远端存储上依然划算”。

## 核心洞察

论文最重要的观点是：在存储解耦之后，主机不应该继续承担那些可以在目标端验证正确性的高频工作。`CEtoFS` 因此把文件系统拆成内核控制面和用户态数据面，再把三项最耗时、最容易被网络放大的职责下沉到目标端：权限检查、并发排序，以及基于 redo log 的原子写。

这个拆分之所以成立，是因为这三类功能只需要有限而明确的状态。目录树、extent 映射、ACL 等权威元数据依然由内核维护；但文件一旦打开，目标端就可以根据按块索引的 reverse permission table 验证请求是否合法，可以只序列化那些确实有顺序依赖的 request group，也可以在目标端先写日志再后台 checkpoint，从而避免数据在网络上来回折返。换句话说，`CEtoFS` 不把存储服务器视为被动 NVMe target，而是把它当成数据路径正确性的可信执行点。

## 设计

`CEtoFS` 由三个部分组成。`K-FS` 是普通内核文件系统，论文原型使用 `Ext4`，它继续负责 `open`、`mkdir`、inode 管理、extent 索引和打开时的权限检查等元数据控制面。`U-Lib` 是链接到应用里的用户态 shim，它拦截文件系统调用，在用户态直接执行 `read` 和 `write`，并维护一棵内存 extent tree，把文件偏移翻译成设备块地址；如果缓存里没有对应映射，就通过 `fiemap` 向 `K-FS` 拉取最新 extent 信息。`T-Handler` 则运行在目标端服务器上，以用户态进程形式接收 RDMA 请求并直接访问 SSD。

它的数据路径围绕“每个打开文件一个请求队列”展开。每个文件打开时都会分配两个位于 RDMA 内存中的 ring buffer：`server_rb` 用于主机向目标端发送请求，`host_rb` 用于目标端回写完成通知。`U-Lib` 通过 `RDMA_WRITE_WITH_IMM` 提交请求，并在 immediate data 里携带请求所在地址，这样 `T-Handler` 不必轮询所有队列。原型目前最多支持 `64K` 个请求队列。

权限检查通过块粒度的 reverse permission table 下沉。元数据块和空闲块归 `K-FS` 所有，数据块的 owner 则是所属文件的 inode 号。目标端处理每个请求时检查两件事：发起该请求的队列是否属于拥有该块的文件，以及队列上的读写权限是否匹配本次操作类型。这样 `CEtoFS` 就能在维持用户态快速数据路径的同时，阻止应用随意访问任意块地址。追加写因为事先没有块映射，所以分成两步：先由 `K-FS` 用 `fallocate` 分配新块并设置权限项，再由用户态直接写入这些块。

并发控制方面，`CEtoFS` 在发起端构造 request group。基础策略把相邻读请求并为一组，而每个写请求单独成组；这些组可以并行发往目标端，再由目标端保证组间顺序。更激进的 merging group 策略则分别维护读范围树和写范围树，检测相邻 group 是否访问不冲突的区间；若无冲突，就把它们合并，让同一文件上不同区间的请求也能在 SSD 上并发执行。目标端再用当前 group ID、首个 request ID 表、已完成请求计数和 request-to-queue 映射等状态，安全地推进后续 group。

失败原子 I/O 通过 `atomic_write_start`、`atomic_write_commit` 和 `atomic_write_abort` 三个接口暴露给应用。目标端执行 redo logging：写入先落到目标端日志区，事务元数据写入恢复表，之后再异步 checkpoint 回原始位置。由于日志逻辑位于目标端，主机只需要把数据跨网络发送一次。

## 实验评估

原型运行在两台服务器上，CPU 为双路 24 核 Xeon Platinum 8260，网卡为 Mellanox ConnectX-5 RDMA NIC，目标端 SSD 是 Intel Optane P4800X。对比系统包括 `Ext4`、`F2FS` 和 `uFS`，所有实验都使用 `O_DIRECT`，以尽量只测存储路径本身。

单线程微基准首先证明了用户态数据路径的收益。读性能方面，`CEtoFS` 相比 `Ext4` 提升 `10%` 到 `1.12x`，相比 `F2FS` 提升 `9%` 到 `1.23x`，并且整体接近 `uFS`。4 KB 随机读平均延迟约 `19 us`，而远端 `Ext4` 为 `42.34 us`。覆盖写方面，`CEtoFS` 平均比 `Ext4`、`F2FS`、`uFS` 分别高约 `74%`、`65%`、`24%`；追加写则分别高 `52%`、`50%`、`12%`。

真正拉开差距的是共享文件上的扩展性。在 `FxMark` 的 `DWOM` 工作负载中，多线程并发覆盖同一个共享文件，论文报告 `CEtoFS` 吞吐最高可提升 `19x`。原因在于它避免了主机端 reader-writer lock 的长时间串行化，并利用 merging group 让无冲突区间在目标端并行执行。宏基准也呈现同样趋势：`Fileserver` 相对三种基线大约提升 `64%` 到 `75%`，而元数据占比更高的 `Varmail` 收益较小，因为这类工作负载仍然频繁进入内核控制面。`LevelDB` 中，`write sync` 延迟相对 `Ext4` 降低 `57%`，相对 `F2FS` 降低 `30%`。原子写实验里，目标端 offload 相比发起端 undo journaling 快 `1.8x`，相比 redo journaling 快 `58%`。这些结果基本支撑了论文的中心主张，但实验环境主要局限于单一 RDMA 加 Optane 平台，以及 direct I/O 的工作负载。

## 创新性与影响

和 _ReFlex_ 这类 remote storage 工作相比，`CEtoFS` 的目标不只是做出更快的块访问路径，而是追问：既然远端块访问已经足够低延迟，文件系统本身该怎样重新分工。和 `uFS` 这样的本地用户态文件系统相比，它的真正新意在于目标端协作模型，也就是把权限、并发和原子性这三类会被网络显著放大的工作，下沉到远端服务器去做。

因此，这篇论文会直接影响解耦式存储设备、RDMA 文件系统和 kernel-bypass 存储栈的设计者。它更像是一组机制上的重新组合，而不是提出了一个全新的抽象问题；但这组组合很有价值，因为它明确指出了哪些传统文件系统功能在 remote NVMe 上会变得特别昂贵，并给出了一种相对干净的重新切分方法。

## 局限性

这套设计建立在“目标端服务器可信且可编程”的前提上。对于由存储厂商控制的 appliance，这个假设并不离谱，但它显然不是所有远端存储环境都天然满足的条件。原型还采用“每个打开文件一个请求队列”的方式，目前上限是 `64K` 个队列；论文提出可以让权限相同的文件共享队列来继续扩展，但并没有给出实测结果。

论文最好的结果主要出现在数据路径占主导的 direct-I/O 工作负载上。像 `Varmail` 这种元数据密集型场景，收益会因为 `K-FS` 仍需处理大量元数据操作而变小。原子写机制也不是透明的 POSIX 语义增强，而是要求应用显式调用事务边界 API。最后，实验仅覆盖单发起端、单目标端、单 Optane SSD 的配置，多目标扩展、集群协调以及 DPU 部署都留给了未来工作。

## 相关工作

- _Klimovic et al. (ASPLOS '17)_ — `ReFlex` 主要提供 kernel-bypass 的远端 flash 数据路径，而 `CEtoFS` 在此基础上进一步把权限、并发和原子写决策也纳入文件系统级的目标端协作。
- _Kadekodi et al. (SOSP '19)_ — `SplitFS` 同样拆分控制面和数据面，但它针对的是 persistent memory，并依赖页表来做权限控制；`CEtoFS` 面向的是远端 SSD，因此改用块所有权检查。
- _Liu et al. (SOSP '21)_ — `uFS` 是面向本地 SSD 的高性能用户态文件系统；`CEtoFS` 则把用户态思路推广到解耦式 NVMe，并重点处理网络放大的串行化成本。
- _Ren et al. (OSDI '20)_ — `CrossFS` 关注的是本地高速存储上的可扩展访问，而 `CEtoFS` 用 request grouping 和目标端排序来在远端访问延迟下维持正确性与并发度。

## 我的笔记

<!-- empty; left for the human reader -->
