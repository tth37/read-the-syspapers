---
title: "Lockify: Understanding Linux Distributed Lock Management Overheads in Shared Storage"
oneline: "Lockify 让新建文件或目录的客户端直接声明自己是初始锁拥有者，并异步补齐目录节点确认，从而把 DLM 查询移出创建关键路径。"
authors:
  - "Taeyoung Park"
  - "Yunjae Jo"
  - "Daegyu Han"
  - "Beomseok Nam"
  - "Jaehyun Hwang"
affiliations:
  - "Sungkyunkwan University"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/skku-syslab/lockify"
tags:
  - filesystems
  - kernel
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`Lockify` 是一个面向共享磁盘文件系统的 Linux 内核分布式锁管理器，它把“新建文件或目录时必须先远程查出锁拥有者”这一步从同步关键路径中拿掉。因为新对象本来就没有既有 owner，创建者可以先声明自己拥有该锁，再让目录节点上的记账异步补齐，因此在原生 kernel DLM 之上把吞吐提升到最高 `6.4x`。

## 问题背景

论文研究的是共享磁盘文件系统，例如 `GFS2` 和 `OCFS2`。这类系统让多个客户端共享同一块存储设备，并依靠分布式锁管理器（`DLM`）协调访问。目标部署往往是低冲突的：论文引用的测量显示，`76.1%` 到 `97.1%` 的文件很少被多个客户端共同访问；高可用场景也常常只有一个主节点活跃、其他节点待命。

作者发现，这并不意味着 create 路径就便宜。即便只有一个客户端实际运行负载、其他客户端只是挂载同一文件系统，普通读写几乎不受影响，但大量创建文件和目录时吞吐会明显下降。以 `GFS2` 为例，低冲突的 5 客户端场景相比 1 客户端理想情况，吞吐最多下降 `86%`。真正拖慢系统的不是本地拿锁，而是创建新对象前必须跨节点找到 directory node，再通过它查询 owner 并等待回复的通信成本。`OCFS2` 上也有相同趋势，而 `O2CB` 因为可能要与所有客户端交互，表现还更差。

## 核心洞察

论文最重要的观察是：创建新对象与访问既有对象在语义上不同。对于已经存在的文件，系统必须知道当前 owner；但对于一个尚不存在的文件或目录，并没有“旧 owner”需要被发现。标准 Linux DLM 仍然会先哈希到某个 directory node，再同步询问 owner。Lockify 认为，这一步对 create 来说是可省的。

作者的核心命题是：对新对象创建而言，正确性要求的是 directory node 最终记录谁是 owner，而不是创建者必须在进入关键路径之前就同步等到确认。只要创建者能先声明 self-ownership，再把目录节点状态异步补齐，create 路径就可以重新变成本地操作。

## 设计

Lockify 在 kernel DLM 之上加入了三样东西。第一是 **self-owner notification**：当文件系统正在创建一个新文件或目录时，本地节点直接声明自己是初始 owner，而不是先去问 directory node。第二是带 `NOTIFY` 标志的 **扩展加锁接口** `dlm_lock(..., NOTIFY)`，把“当前请求是否适合 self-ownership”的判断留给文件系统层；已有对象上的操作仍然走标准路径。

第三是通过 wait-list 完成的 **异步 owner 管理**。每次通知发出后，Lockify 都插入一个 wait-list 项等待 directory node 确认；如果超时，就重发通知；如果发生恢复流程，也可以把未确认通知转发给新的 directory node。这样它才能在缩短 create 关键路径的同时维持 DLM 级别的一致性。

同一父目录下并发创建时，Lockify 仍然要求先独占拿到父目录锁，只是在持有该锁时把 ownership update 与真正的 create 操作并行起来，并在两者都完成后再释放父目录锁。原型实现基于 Linux `6.6.23`，并对 `GFS2` 和 `OCFS2` 做了小规模修改。

## 实验评估

实验使用 5 台服务器，每台机器配备双路 `Xeon Gold 5115`、`64 GB` 内存、本地 NVMe SSD，并通过 `56 Gbps` 链路互连；共享存储通过 `NVMe-over-TCP` 暴露给所有节点。核心微基准是 `mdtest`，总共创建 `35,000` 个文件和目录。

最强结果出现在低冲突场景。5 个客户端都挂载文件系统，但只有 1 个客户端实际运行负载时，Lockify 相比原生 kernel DLM 在 `OCFS2` 上把吞吐提升约 `2.9x`，在 `GFS2` 上提升约 `6.4x`。`GFS2` 的延迟拆解尤其说明问题：理想 1 客户端情况下，DLM 只占端到端延迟的 `4.4%`；标准 5 客户端路径中，这个比例升到 `46.7%`；换成 Lockify 后又降到 `8%`。这几乎直接证明，真正拖慢 create 的是远程 owner discovery，而不是本地 create 逻辑本身。

一旦进入高冲突区间，收益就会变窄。在 5 个客户端同时向同一个父目录下创建子项时，`OCFS2` 只提升 `1.09x` 到 `1.11x`，因为父目录锁本身就是主要瓶颈。`GFS2` 的结果更好，目录和文件创建分别达到 `5.2x` 和 `5.4x`，原因是它自己的锁请求排队与去重机制降低了父目录锁压力。真实工作负载也延续同样趋势：`Postmark` 中分别提升 `1.7x` 和 `2.0x`，`Filebench` fileserver 中提升 `1.07x` 到 `1.14x`，`webproxy` 中 `OCFS2` 提升 `1.08x`、`GFS2` 提升 `2.5x`。此外，`xfstests` 通过数与基线 DLM 完全相同（`GFS2` 为 `70/75`，`OCFS2` 为 `67/75`）；模拟 RDMA DLM 的间接对比则显示 Lockify 达到其 `87%` 到 `88%` 的吞吐，但这只是粗略上界，不是真实 RDMA 实现对比。

## 创新性与影响

与 `SeqDLM`、`Citron` 这类工作相比，Lockify 的范围窄得多：它不想重写所有场景下的 DLM，也不依赖 RDMA。它的创新点是把 self-owner notification 与异步 ownership reconciliation 嵌入现有 Linux 共享磁盘栈，专门优化新对象创建。

因此，这篇论文既提出了一个能落到 `GFS2`、`OCFS2` 这类系统里的实用机制，也把“低冲突并不等于低协调开销”这个系统诊断讲清楚了。

## 局限性

Lockify 的收益边界很明确：它只帮助“当前节点正在创建一个此前没有 owner 的锁对象”这种情况。对于已经存在的文件，它不改变锁路径；对于父目录等已有锁对象上的高冲突，它也无能为力，`OCFS2` 的高冲突结果正好说明了这一点。

此外，这个设计用异步状态管理替代同步等待，因此 wait-list、超时重传和恢复重发都成了必须维护的协议状态。论文的 `xfstests` 结果给出了一定信心，但验证面仍然有限。实验范围也比较集中：最亮眼的数字主要来自 5 节点、1 个活跃客户端的元数据创建负载，RDMA 对比也只是模拟而非真实实现。

## 相关工作

- _Chen et al. (SC '22)_ — `SeqDLM` 面向并行文件系统中的高冲突共享文件访问，而 Lockify 聚焦于共享磁盘文件系统中新对象 create 路径的 owner-discovery 开销。
- _Gao et al. (FAST '23)_ — `Citron` 借助 one-sided RDMA 处理分布式 range lock，而 Lockify 工作在普通 TCP 环境下，重点是元数据创建。
- _Yoon et al. (SIGMOD '18)_ — 这项 RDMA 化去中心化 DLM 工作更通用；Lockify 的适用范围更窄，但更容易落地到现有 kernel DLM 栈里。

## 我的笔记

<!-- empty; left for the human reader -->
