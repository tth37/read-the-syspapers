---
title: "Overcoming the Last Mile between Log-Structured File Systems and Persistent Memory via Scatter Logging"
oneline: "SLOT 不再为 PM 上的 LFS 维护大段连续日志，而是把元数据 entry 打散到可立即复用的槽位里，再用缓冲区感知策略把 locality 尽量捡回来。"
authors:
  - "Yifeng Zhang"
  - "Yanqi Pan"
  - "Hao Huang"
  - "Yuchen Shan"
  - "Wen Xia"
affiliations:
  - "Harbin Institute of Technology, Shenzhen"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3717488"
code_url: "https://github.com/HIT-HSSL/slotfs-eurosys"
tags:
  - filesystems
  - persistent-memory
  - crash-consistency
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的判断很直接：PM 上的 LFS 真正背着的是连续日志空间带来的 GC 负担。SLOT 把元数据日志拆成按 entry 管理的散布槽位，用 checksum、链表和时间戳重建 crash consistency，再靠缓冲区感知策略把 locality 尽量捡回来；最终 SlotFS 在真实工作负载上比 NOVA 快 27%-47%。

## 问题背景

LFS 一直很适合 persistent memory，因为它的持久化协议简单：把更新打成 log entry，顺序写入，再靠原子 tail 更新宣布提交，恢复时顺序重放即可。问题在于，现有 PM LFS 仍然沿用块设备时代的连续空间假设。像 NOVA、MadFS 这样的系统虽然已经跑在 byte-addressable PM 上，日志却还是按块维持连续；日志老化之后，为了继续追加，只能跑 GC。

到了 PM 上，这个代价会特别刺眼，因为介质本身已经很快。论文里 NOVA 的顺序写实验显示，GC 时间占比会从 1.5% 涨到 64.0%，带宽从 988 MiB/s 掉到 341 MiB/s；再加 1 到 3 个后台写线程，前台吞吐还会再降 10.2%-20.1%。但如果简单把 entry 打散，传统 LFS 依赖的 tail-pointer 提交和顺序恢复模型又会被破坏。论文要解决的，就是如何拿掉连续性，却不丢掉 LFS 风格的 crash consistency。

## 核心洞察

作者最重要的观察是：对 byte-addressable PM 来说，跨多个 log entry 的连续性没有 GC 那么值钱。论文专门做了一个碎片化但不做 GC 的 NOVA 变体，它相对理想的无 GC 追加版本只慢 4.5%-9.8%；真正把系统拖慢的，是 59.6%-79.8% 的 GC 损失。所以 locality 依然重要，但更像优化目标，而不是正确性前提。

于是 SLOT 把语义往单个 entry 上收。系统不再要求整段日志连续，只要求单个 entry 能独立提交。之后再把 LFS 的旧保证按这个粒度重建：用 checksum 判定提交，用链表找到有效 entry，用时间戳恢复逻辑写入顺序。

## 设计

SLOT 在 PM 里预留一张固定大小的 slot table，每个 slot 放一个元数据 log entry。每个 slot 除了文件系统自己的字段，还带 `next`、时间戳和 checksum。entry 失效后不用等 GC，要么改链表直接回收，要么留在 per-inode 的无效列表里，下次直接覆盖复用。因为记录的只是 metadata，不是数据块本身，所以额外空间大约是 PM 容量的 1%-2%。

崩溃一致性也按 entry 来做。传统 LFS 需要维护全局 tail；SLOT 直接把 checksum 和 entry 一起写下去，中途掉电就靠校验失败把这次写判掉。恢复时沿着 per-inode 链表找有效 entry，再按时间戳重放。为了减少追加时的回写，系统还预留 ghost slot，这样多数情况下不用回头修改旧尾部。

为了把 PM 写缓冲区也考虑进去，SLOT 又加了三组启发式：best-effort allocator 先找 64 个连续 slot，再退到 16 和 1；guided dispatcher 根据 I/O 大小、空间利用率和 cacheline 大小，在复用旧 entry 与尾部追加之间选择；gather thread 则在空闲时把分散 entry 重写成 cacheline 级的小连续子链。原型 SlotFS 把这些机制落在一个带 Hodor 隔离的 userspace PM 文件系统里。

## 实验评估

实验平台是 16 核 Xeon Gold 5218，加上 `2 x 256 GiB` Optane DCPMM；基线包括 NOVA、PMFS、SplitFS、ext4-DAX 和 MadFS。最能说明论文主张的，是 128 GiB 的 GC 压力测试。顺序写时，NOVA 为了完成 128 GiB 用户请求，实际打到介质上的 I/O 有 275.3 GiB，其中 132.1 GiB 来自 GC，带宽只有 393 MiB/s；SlotFS 的 media I/O 是 136.7 GiB，GC I/O 为 0，带宽到 1845 MiB/s。

1 GiB 的单线程 FIO 说明它不只是理论上省 GC。顺序 append 上，SlotFS 在 4 KiB 和 16 KiB 下分别比其他系统快 1.33x-4.21x 和 1.27x-2.12x。overwrite 的结果则更克制：它明显快于 NOVA，但面对那些不提供完整数据原子性的原地更新系统，未必总能赢；论文也给出了放松原子性的 SlotFS-Relax 来说明这部分代价。

其余结果与主线一致。SlotFS 扛住了数百轮随机崩溃恢复，FxMark 元数据操作最好，单线程 Fileserver 上也分别比 PMFS、NOVA、SplitFS 高 41%、41%、62%。不过最干净的证据还是和 NOVA 的正面对比，因为部分其他基线的持久化语义不同，而且 userspace 执行本身也会带来额外收益。

## 创新性与影响

这篇论文的新意，不是把 GC 再优化一次，而是提出 PM 元数据日志很多时候根本不该继续依赖 GC。SLOT 把日志管理粒度从块改成 entry，再围绕这个粒度重写提交和恢复规则。对做 PM 文件系统、CXL 持久层、以及其他 log-structured PM 系统的人来说，这篇论文的价值就在于逼着大家重新审视那些从块设备时代继承下来的连续空间假设。

## 局限性

论文并没有把 SLOT 说成放之四海而皆准。读密集型负载下，SlotFS 往往只是和其他 PM 文件系统接近；在要求强原子性的 overwrite 路径上，它也未必能赢过那些原地更新的设计。另外，SlotFS 的端到端优势里有一部分来自 userspace 加 Hodor，因此并不是所有相对内核文件系统的提升都该直接记到 SLOT 头上。

部署成本同样不低。SLOT 需要预留 slot 空间、维护 DRAM 索引，并在恢复时扫描日志链；论文给出的 crash recovery 也要 1.14-1.90 秒。整套实现主要在 Optane DCPMM 上调出来，未来若换成 flush 粒度更粗的 PM 或 CXL 设备，这些启发式参数是否还成立，论文基本留给了后续工作。

## 相关工作

- _Xu and Swanson (FAST '16)_ - NOVA 把 per-inode logging 带到 PM 上，但日志仍按块管理，扩容时仍要付 GC 代价；SLOT 则把管理粒度降到单个 entry，并放弃 tail-pointer 提交模型。
- _Kadekodi et al. (SOSP '19)_ - SplitFS 关注的是 PM 文件系统的软件栈开销，通过直接数据访问和受控内核协作减少系统调用负担；SLOT 处理的是 log-structured 设计内部的 GC 与 crash consistency 问题。
- _Zhong et al. (FAST '23)_ - MadFS 通过压缩和虚拟化 per-file log 来减轻 GC 成本，但清理动作本身依旧存在；SLOT 的立场更进一步，目标是让 metadata logging 根本不再依赖 GC。
- _Zhou et al. (SOSP '23)_ - Trio 研究的是安全的 userspace NVM 文件系统架构，而 SlotFS 借助 Hodor 做进程内隔离，真正新增的核心机制是 scatter logging layout。

## 我的笔记

<!-- 留空；由人工补充 -->
