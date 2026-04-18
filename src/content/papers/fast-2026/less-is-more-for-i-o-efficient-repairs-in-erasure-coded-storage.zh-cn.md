---
title: "LESS is More for I/O-Efficient Repairs in Erasure-Coded Storage"
oneline: "LESS 用少量扩展 RS 子条带把修复限制在单个局部编码视图内，在接近 Clay 修复 I/O 的同时把 I/O seek 保持在线性规模。"
authors:
  - "Keyun Cheng"
  - "Guodong Li"
  - "Xiaolu Li"
  - "Sihuang Hu"
  - "Patrick P. C. Lee"
affiliations:
  - "The Chinese University of Hong Kong"
  - "Shandong University"
  - "Huazhong University of Science and Technology"
conference: fast-2026
category: reliability-and-integrity
code_url: "https://github.com/adslabcuhk/less"
tags:
  - storage
  - fault-tolerance
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`LESS` 在每个条带上叠加少量扩展 `RS` 子条带，让一个失效块通常可以在单个扩展子条带内完成重建，而不必像普通 `RS` 那样读取 `k` 个整块。它相对 `Clay` 牺牲了一点 repair-I/O 最优性，但把 sub-packetization 保持在线性规模，并把 I/O seek 压到足以在真实修复时间上获胜的水平。

## 问题背景

这篇论文抓住的是一个很“系统”的现实：现代纠删码存储里的修复延迟，越来越受制于本地存储 I/O，而不是网络或有限域运算。传统 `(n,k)` `RS` 修复要读取 `k` 个完整 helper blocks，因此本地访问数据量和修复时间都会很高。

现有 repair-friendly code 也都留着缺口。`Clay` 在一般 `MSR` 码里把 repair I/O 做到最优，但代价是指数级 sub-packetization 和大量分散读取；`LRC` 通过增加冗余来换修复效率，失去了 `MDS` 最优性；`Hitchhiker`、`HashTag`、`ET` 等 `MDS` 方案则只改善一部分修复，或者仍然留下不少 I/O 开销。论文因此把问题定义成两个维度：既要少读数据，也要少产生 I/O seeks。

## 核心洞察

论文最重要的判断是：比起单纯追求“访问字节数最优”，更有价值的是把 repair I/O 和 I/O seeks 一起压低。`LESS` 的办法是在 `(n,k,α)` 条带上叠加 `α + 1` 个彼此重叠的 extended sub-stripes，并把 `α` 控制在 `2` 到 `n-k` 之间，保持“小而可调”。

这个设计带来一个关键结构性质：任意一个失效块的全部 sub-block 都会共同落在某一个 extended sub-stripe 中，而那个 extended sub-stripe 本身又是一个 `RS` 编码对象。于是修复可以被限制在一个局部编码视图里完成，同时保留 `RS` 的部署友好属性：`MDS`、systematic、以及一般 `(n,k)` 参数支持。

## 设计

`LESS` 先把条带中的 `n` 个块分成 `α + 1` 个大小近似相等的 block groups，然后构造 `α + 1` 个 extended sub-stripes。对每个 `z ≤ α`，`X_z` 由 group `G_z` 的全部 sub-block 加上整个条带里第 `z` 个 sub-stripe 的全部 sub-block 组成；最后一个 `X_{α+1}` 则由最后一个 group 再加上一组“对角线” sub-block 组成。每个 sub-block 都恰好属于两个 extended sub-stripes。

作者随后为这些 sub-block 选择不同的 Vandermonde 编码系数，使每个 extended sub-stripe 都满足一个 `RS` parity equation，并能容忍 `n-k` 个 sub-block 失效。真正需要显式编码的只有前 `α` 个 extended sub-stripes；最后一个由前面的等式自动推出。论文里的 `(6,4,2)` 例子表明，一个失效块只需 `6` 个 helper sub-block，而不是 `4` 个整块，repair I/O 降低 `25%`。

修复路径则严格跟随 group 结构。若 group `G_z` 中的块 `B_i` 失效，`LESS` 就在 `X_z` 内修复它，并优先读取同组内连续存放的 helper sub-block。这样，repair I/O 大致为 `k + (α-1)|G_z|` 个 sub-block，而 I/O seek 数固定为 `k + α - 1`。由于 group 大小差异至多为 `1`，data blocks 和 parity blocks 的收益也基本均衡。对某些 multi-block repair，`LESS` 还能在同一 group 内一起修复最多 `floor((n-k)/α)` 个失效块；其他情况则退回 conventional repair。

## 实验评估

数值分析把这个 tradeoff 说得很清楚。以默认 `(14,10)` 为例，`LESS (α=4)` 的平均 repair I/O 为 `4.64` 个 blocks，平均 I/O seeks 为 `13`；`RS` 需要 `10` 个 blocks，`Hitchhiker` 需要 `7.50`，`HashTag-4` 需要 `6.04`，`ET-4` 需要 `5.86`。`Clay` 在纯 repair I/O 上仍然最强，只要 `3.25` 个 blocks，但平均 seek 数高达 `286`。对 `(124,120)` 这样的宽条带，`LESS (α=4)` 也能把 repair I/O 从 `120` 降到 `48.6`，而 seek 数只是 `123`，几乎贴着 `RS` 的 `120`。这正是本文的核心结论：少许字节数让步，可以换来避免请求数爆炸。

基于 `HDFS/OpenEC` 的原型说明这些收益确实能落到真实时间上。作者在 Hadoop `3.3.4` HDFS 上，用 `OpenEC` 和 `Jerasure` 实现 `LESS`，新增 `8.7 KLoC` C++ 代码，并在 `15` 台 `i5-7500`、`16 GiB` 内存、`7200 RPM` SATA `HDD` 的机器上评测。`LESS (α=4)` 相比 `RS`、`Hitchhiker`、`HashTag-4`、`ET-4`、`Clay` 的单块修复时间分别降低 `50.8%`、`35.9%`、`21.5%`、`21.5%`、`33.9%`；full-node recovery 分别降低 `48.3%`、`34.3%`、`17.8%`、`19.4%`、`36.6%`。

灵敏度实验也支持同样的解释。网络提高到 `10 Gbps` 后，`Clay` 的 seek 开销彻底暴露，`LESS (α=4)` 在单块修复时间上比它快 `83.3%`。当 packet size 降到 `128 KiB` 时，`LESS` 仍能保持领先，因为它的 sub-packetization 很小。主要代价在编码吞吐上：`256 KiB` packet 下，`RS` 为 `2.8 GiB/s`，`LESS (α=4)` 为 `1.6 GiB/s`。在作者的 `HDD` 场景里，这一代价没有抵消修复时间收益。

## 创新性与影响

`LESS` 不是一个调度技巧，也不是对旧编码的简单工程优化，而是一个把 seek count 明确纳入目标函数的新 code family。相对 `Clay`，它的新意在于承认“多读一点数据”是值得的，只要能换来更小的 sub-packetization 和更规整的 I/O；相对 `LRC`，它又没有放弃 `MDS` 最优冗余。

这使论文同时对编码理论和系统实践有价值。它说明一个码即使不是严格意义上的 repair-I/O-optimal，也可能在真实 wall-clock repair time 上更好。

## 局限性

`LESS` 本质上是一种权衡，而不是免费的改进。它在纯 repair I/O 上并不超过 `Clay`，因此如果底层随机访问代价很低、瓶颈重新回到网络，它的优势可能会变小。对 multi-block repair 的收益也只在失效块落入同一 block group 时才成立，否则仍会退回 conventional repair。

论文的评测范围也有限。原型建立在 `HDFS/OpenEC` 上，重点覆盖 `(14,10)` 以及 `n-k ≤ 4` 这类常见参数。作者证明了足够大域上总能找到编码系数，并列出了常见情况下可行的 primitive elements，但没有深入讨论更大参数范围下的实现与运维复杂度。再加上 `LESS` 的编码吞吐低于 `RS`，这在 CPU 很强、SSD/NVMe 占主导的系统里可能会比文中的 `HDD` 集群更重要。

## 相关工作

- _Vajha et al. (FAST '18)_ — `Clay` 在一般 `MSR` 设置下把 repair I/O 做到最优，而 `LESS` 刻意多花一点 repair I/O，以换取更小的 sub-packetization 和更低的 seek 开销。
- _Rashmi et al. (SIGCOMM '14)_ — `Hitchhiker` 通过在两个 `RS` 子条带上做 piggybacking 来降低修复成本，但它主要改善 data-block repair，而不是像 `LESS` 那样同时兼顾 data 与 parity 的均衡收益。
- _Huang et al. (ATC '12)_ — `Azure-LRC` 通过 locality 改善单块修复，而 `LESS` 则坚持 `MDS` 与 systematic，不依赖额外冗余来换取局部恢复。
- _Tang et al. (INFOCOM '23)_ — `Elastic Transformation` 也提供可调的修复权衡，但 `LESS` 通过 layered extended sub-stripes 在相近的小 `α` 下取得了更低的 repair I/O。

## 我的笔记

<!-- 留空；由人工补充 -->
