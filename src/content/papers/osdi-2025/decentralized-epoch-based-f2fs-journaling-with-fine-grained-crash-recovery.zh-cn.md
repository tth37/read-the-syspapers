---
title: "Decentralized, Epoch-based F2FS Journaling with Fine-grained Crash Recovery"
oneline: "F2FSJ 用每 inode 元数据变更日志、epoch 切换与 fast-forward apply 取代粗粒度 checkpoint，降低延迟并细化崩溃恢复。"
authors:
  - "Yaotian Cui"
  - "Zhiqi Wang"
  - "Renhai Chen"
  - "Zili Shao"
affiliations:
  - "The Chinese University of Hong Kong, China"
  - "College of Intelligence and Computing, Tianjin University, China"
conference: osdi-2025
code_url: "https://github.com/10033908/F2FSJ"
tags:
  - filesystems
  - storage
  - crash-consistency
  - kernel
category: memory-and-storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

F2FSJ 把 F2FS 基于 checkpoint 的恢复路径，改成了专门适配 out-of-place update 的 ordered metadata-change journaling。它把日志分散到每个 inode，用 epoch 在 journal period 之间切换而不引入全局停顿，并在 apply 阶段尽量直接刷新已经覆盖旧日志的最新 dirty metadata。对元数据密集 workload，它把 journaling 时间相对 F2FS checkpoint 最多缩短 4.9x，把平均延迟最多降低 35%。

## 问题背景

F2FS 因为 append-only 写入、冷热分离等特性，很适合 flash storage，所以在 Android 上被广泛采用。但它的 crash recovery 仍然建立在 checkpoint 之上。只要 dirty metadata 超过阈值，或者 timeout 到期，F2FS 就会触发 checkpoint，把脏数据、inode metadata 和 filesystem metadata 一起刷成 checkpoint pack。在论文实验里，这部分 checkpoint 时间在元数据密集 benchmark 中大约占总运行时间的 17% 到 47%，而 `create-4KB`、`rmdir`、`unlink-4KB` 的最坏 checkpoint 延迟分别达到 247 ms、233 ms、293 ms。

checkpoint 还只能提供粗粒度恢复。两次 checkpoint 之间如果发生崩溃，最近的数据和元数据就可能一起丢失。论文报告默认 60 秒 checkpoint 间隔下，最多会丢掉 9.1% 的数据或元数据；把间隔缩短到 1 秒虽然能少丢一些，但会增加执行时间。F2FS 的 roll-forward 路径主要帮助 `fsync`，但论文指出在 no-barrier 和 POSIX `fsync` 模式下，I/O reordering 仍可能让恢复后的 inode 状态和文件数据不一致。直接搬用 ext4 风格 journaling 也不行，因为 F2FS 的 inode 是 out-of-place update：只 journal inode 会遗漏 NAT/SIT/SSA 更新，而 journal 完整 metadata page 又会放大 I/O，并继承 JBD2 的集中式锁竞争。

## 核心洞察

论文最核心的判断是：对 F2FS 来说，合适的 journaling 单位不是整页 metadata，而是“按 inode 组织的 metadata change”。控制平面只追踪某个 journal period 里有哪些 inode 参与，数据平面则把真正的变更记录保存在这些 inode 自己的日志链表中。这样 journal commit 就不需要一个会卡住所有人的全局 transaction。

更重要的是，out-of-place-update 语义会在 apply 阶段反过来帮忙。旧的磁盘版本不会被原地覆盖，所以 F2FSJ 往往可以跳过中间日志，直接把内存里更新后的最新 dirty metadata 刷下去。论文把这称为 fast-forward-to-latest：只要最新 inode 状态已经覆盖旧日志效果，就没有必要逐条重放所有中间更新。

## 设计

F2FSJ 采用 ordered journaling：先刷数据，再提交 metadata change。为了控制开销，它只 journal 变更本身，而不是整页。对于涉及数据块的操作，它记录 inode 层面的修改以及相关的 filesystem metadata 更新，尤其是 SIT 和 SSA；与 inode 相关的 NAT/SIT/SSA 信息会在 commit 时一并附加进去，这样恢复时不必 journal 完整 metadata page。

journal period 由单调递增的 epoch 表示，状态为 `IDLE`、`RUNNING`、`COMMIT`。每个 inode 维护一个从 epoch 到 per-epoch log list 的 `e2l_mapping`。在某个 `RUNNING` epoch 里第一次修改该 inode 时，系统只注册一次 inode 并创建对应 log list；后续修改继续追加到同一链表。每个 log list 还有一个 `J_ticket`，记录仍在进行中的文件操作。遇到 `fsync` 或 timeout 时，当前 epoch 进入 `COMMIT`，同时立刻发放新的 `RUNNING` epoch；commit 线程只需等待相关 log list 的 ticket 清零，再聚合日志并按“journal descriptor block + payload + journal commit block”原子写入。

apply 阶段引入三种页面状态：`Uptodate`、`F2FSJ_Dirty`、`Dirty`。数据刷盘并完成 journal commit 后，页面变成 `Dirty`，表示“已提交但尚未 apply”。如果 apply 看到对应内存页处于 `Dirty`，就直接把这个最新页刷盘并标成 `Uptodate`，从而把跨 epoch 的旧更新折叠成一次写入；如果页面缺失或已经是 `Uptodate`，就可以跳过该日志；如果页面还是 `F2FSJ_Dirty`，说明另一个 epoch 仍在使用它，就退回到直接按日志更新磁盘。崩溃恢复按 commit 顺序重放剩余 epoch，并利用日志中的 NAT/SIT/SSA 信息定位旧 inode 再写出新 inode。一个实际代价是：GC 之前必须先完成 journal apply，因为 GC 会移动 inode 和数据块位置。

## 实验评估

原型在 Linux F2FS 上大约新增了 3,000 行代码，并使用一个 256 MB 连续 journal file。对 `mkdir`、`rmdir`、`create-4KB`、`unlink-4KB`，F2FSJ 的 journaling 时间相对 F2FS checkpoint 时间分别缩短 2.4x、1.7x、3.6x、4.9x。tail latency 大约下降三个数量级，平均延迟分别下降 23%、35%、13%、33%。

吞吐提升最明显的正是设计瞄准的场景：相对 checkpointed F2FS，F2FSJ 在 metadata-intensive workload 上提升 1.29x、1.16x、1.27x、1.11x，在 `create-4KB`、`unlink-4KB`、`copy-4KB` 上提升 1.14x、1.69x、1.30x。对大文件顺序或随机数据 workload，收益明显变小，因为 checkpoint 本来就不常触发，而 journaling 还会额外产生写入。恢复方面，F2FSJ 避开了 checkpoint 周期的 trade-off，在 file-count sweep 中比 F2FS roll-forward recovery 快 5.4x 到 6.8x；论文还报告它通过了 CrashMonkey 的 rename 与 create/delete 测试。

## 创新性与影响

这篇论文的贡献不是简单地“给 F2FS 加 journaling”，而是“按 out-of-place-update 的约束重新设计 F2FS journaling”。metadata-change logging、per-inode 去中心化、epoch-based handoff 和 fast-forward apply 缺一不可；四者一起才让 ordered journaling 在 F2FS 上比 checkpoint 更划算。这让它既对 Linux filesystem 工程实现有意义，也会影响后续 scalable journaling 与 flash-oriented crash recovery 研究。

## 局限性

F2FSJ 并不是通用加速器。对大文件数据密集型 workload，它往往只能和 checkpointed F2FS 打平；Webproxy、Varmail 这类真实 workload 也仍会被 F2FS metadata contention 或高频 `fsync` 流量限制。恢复路径同样没有 ext4 的 page replay 那么直接，因为 F2FSJ 需要读取旧 inode，并按 epoch 顺序更新 NAT/SIT/SSA。部署上，它需要专门的连续 journal 空间，且必须在 GC 之前先完成 journal apply；论文还主张它会减少 write amplification，但没有直接测量 SSD endurance。

## 相关工作

- _Lee et al. (FAST '15)_ — F2FS 提出了面向 flash 的 out-of-place 布局，以及 checkpoint 加 roll-forward 的恢复模型；F2FSJ 正是要把这条恢复路径替换成更细粒度的 ordered journaling。
- _Xu and Swanson (FAST '16)_ — NOVA 也采用 per-inode log，但它面向 hybrid volatile/non-volatile main memory，而不是面向 flash 设备的 journal 聚合与 apply。
- _Kim et al. (ATC '21)_ — Z-Journal 通过 per-core journaling 与 coherence commit 改善 JBD2 可扩展性；F2FSJ 则按 inode 与 epoch 分散工作负载。
- _Shirwadkar et al. (ATC '24)_ — FastCommit 在周期性 JBD2 commit 之上叠加 compact logical metadata logging；F2FSJ 则把 metadata-change journaling 直接做成 F2FS 的主恢复路径。

## 我的笔记

<!-- 留空；由人工补充 -->
