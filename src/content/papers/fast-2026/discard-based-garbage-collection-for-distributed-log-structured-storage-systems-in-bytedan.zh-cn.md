---
title: "Discard-Based Garbage Collection for Distributed Log-Structured Storage Systems in ByteDance"
oneline: "DisCoGC 把 discard 变成 ByteStore 的主回收路径、把 compaction 降为低频整理，在不拉高延迟的前提下把生产 TCO 降低约 20%。"
authors:
  - "Runhua Bian"
  - "Liqiang Zhang"
  - "Jinxin Liu"
  - "Jiacheng Zhang"
  - "Jianong Zhong"
  - "Jiahao Gu"
  - "Hao Guo"
  - "Zhihong Guo"
  - "Yunhao Li"
  - "Fenghao Zhang"
  - "Jiangkun Zhao"
  - "Yangming Chen"
  - "Guojun Li"
  - "Ruwen Fan"
  - "Haijia Shen"
  - "Chengyu Dong"
  - "Yao Wang"
  - "Rui Shi"
  - "Jiwu Shu"
  - "Youyou Lu"
affiliations:
  - "ByteDance"
  - "Tsinghua University"
conference: fast-2026
category: indexes-and-data-placement
tags:
  - storage
  - datacenter
  - filesystems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文认为，对于 ByteDance 的 append-only 存储栈，只要 workload 会产生大段、快速失效的旧数据，`compaction` 就不该继续做默认 GC 原语。`DisCoGC` 把 `discard` 变成常规路径，把 `compaction` 留给低频整理，再用边界对齐、批处理、流控和 trim 优化把这套方案真正落到 ByteDrive、ByteStore、UFS 和商用 SSD 上。在线上混合负载中，它把总写放大降低了 `25%`，把 TCO 降低了约 `20%`，同时没有拉高延迟。

## 问题背景

ByteDrive 和 ByteStore 组成了 ByteDance 的大规模分布式块存储栈，支撑在线服务、AI 模型下载、倒排索引维护以及离线计算等 workload，整体规模达到 EB 级。它的写路径是 append-only 的：上层随机写会被改写成对 `LogFile` 的追加写，旧版本数据之后再由垃圾回收回收。最初的回收方式是 `compaction`，也就是把旧 `LogFile` 里仍然有效的数据搬到新 `LogFile`，再删除旧文件。

问题在于，这种方式天然把成本压在两个方向上拉扯。如果 `compaction` 做得保守，失效数据会长期占着 SSD 空间，`space amplification` 上升；如果 `compaction` 做得激进，系统就会重写更多有效数据，抬高逻辑写放大、SSD 磨损和前台 I/O 竞争。论文直接指出，这个权衡已经让 ByteDance 每个月多付出数百万美元的 TCO。

作者之所以相信可以换一种 GC 原语，是因为他们先看了生产 trace。`SAR` 和离线 workload 都有很强的顺序写与频繁覆盖特征：把相邻写合并后，`SAR` 中有 `65%` 的写请求超过 `256 KiB`，离线 workload 也有 `55%` 超过这个阈值。这意味着 `LogFile` 里会形成很长、很连续的失效区间。从原理上说，只要能直接对这些区间执行 `discard`，就可以不搬运有效数据而直接回收空间。真正的难点在于生产栈是多层的：EC stripe、压缩块和 UFS 分配单元彼此不对齐；高频 `discard` 会放大元数据更新；打洞后的 `LogFile` 会更碎；底层 SSD 的 trim IOPS 还可能根本不够。

## 核心洞察

这篇论文最重要的命题是：当 append-only 云存储里的失效数据本来就以长连续区间出现时，主回收机制应该从 `compaction` 切换成 `discard`。`discard` 以区间为单位回收空间，近似常数成本，不需要把仍然有效的数据重新写一遍，因此可以在不额外制造逻辑写放大的前提下压低 `space amplification`。`compaction` 仍然保留，但它的职责应该退化成次级整理器，而不是默认主路径。

但这不是把一个 API 打开就结束的事情。一个上层可见的失效区间，必须能够穿过 `LogFile`、chunk replica、UFS cluster 和 SSD trim 语义，最终在各层都被正确回收。论文真正有价值的洞察因此更偏系统工程：高频 `discard` 负责“少搬数据”，而边界修复、速率控制和整理型 `compaction` 负责“不把系统本身搞碎”。只有两者同时成立，`discard` 才能从一个局部优化变成可部署的 GC 方案。

## 设计

整条数据路径从 ByteDrive 的随机写接口开始，到 ByteStore 的 append-only `LogFile` 结束。每个 volume 会被切成多个 segment；每个 segment 对应一个活跃 `LogFile` 和若干封存的旧 `LogFile`；每个 `LogFile` 再被分成多个 chunk，并以副本或 EC 方式分布到不同 `ChunkServer`；每个 `ChunkServer` 则运行一个 userspace filesystem，其分配单元是由 `4 * 4064 B` 数据扇区组成的 cluster。`DisCoGC` 把 `discard` 这条路径自顶向下插进来：`BlockServer` 扫描 segment 的 `LSM-tree`，找出尚未丢弃的失效 `LogFile` 区间，经由 ByteStore SDK 把这些区间映射到 chunk replica，再在 UFS 中释放相应 cluster，最后把成功状态记下来，避免重复下发。

设计里最核心的两个问题都是对齐失败。第一类是 `EC loss`：上层 `discard` 请求是任意长度区间，但 EC 只能按完整 stripe 丢弃。第二类是 `cluster loss`：EC packet 通常按 `4 KiB` 的倍数组织，而 UFS 的分配单元却是 `4 * 4064 B`，导致传到 UFS 的丢弃区间仍然可能卡在 cluster 边界上。论文给了两个对应修复。其一是 `boundary extension`：如果一个新 `discard` 区间和之前已经丢弃的区间相邻，`BlockServer` 会把新区间向邻居方向轻微扩展，最多延长几 MiB，这样就能把原本卡在边界上的垃圾一并回收。其二是把 EC stripe unit 改成 `n * 4 * 4064 B`，让 stripe 边界和 UFS cluster 对齐，从根上消除 `cluster loss`。

接下来是元数据与调度问题。每次 `discard` 都要改 UFS 的 `MetaPage`，如果请求过密，就会直接跟前台 I/O 争 CPU 和 SSD 写。`DisCoGC` 的做法是先在 `LogFile` 内做批处理，把多个区间合成一个请求，单批最多 `64` 个区间；再做并行度感知的调度，从待处理 segment 中优先选择可回收范围最大的 top-`k`；最后再加一道 `flow control`，硬性限制 `discard` IOPS，让突发流量在过大时自动退回到更保守的节奏，而不是把系统打崩。

因为 `discard` 会把 `LogFile` 和 chunk 打得更稀疏，`compaction` 不能完全消失。论文把两者做成独立调度。通常情况下，系统按“垃圾率最高”的 segment 做 `compaction`，这里的垃圾率还会显式加上边界损失项；如果发现 `LogFile` 数量超过阈值，说明元数据压力开始上升，调度器就切换到“优先整理最碎的 segment”。在 SSD 层，UFS 又额外实现了 `trim filter` 和 `trim merger`：前者避免为太小的区间下发 trim，后者把相邻的小区间合并成大 trim。实现上还有 per-segment discard WAL，以及对已下发和失败区间做压缩 bitmap 跟踪，用来控制额外内存成本。

## 实验评估

论文最有说服力的部分是线上结果。在线上混合负载中，超过 `90%` 的无效区间大于 `128 KiB`，超过 `70%` 的无效区间大于 `1 MiB`，这正是 `discard` 最擅长的工作区间。生产集群里，baseline 和 `DisCoGC` 分别运行在 `1.37` 与 `1.23` 的 `space amplification` 下；在这个前提下，`DisCoGC` 把逻辑写放大降低了 `32%`，把总写放大降低了 `25%`，并把 TCO 降低了约 `20%`。物理写放大最多会上升 `10%`，但因为 GC 时少搬了大量有效数据，最终写进 NAND 的总字节数仍然更少。论文同时报告，延迟和按 TiB 归一化的吞吐几乎没有变化。

离线 trace replay 则解释了收益来自哪里。`SAR` trace 改善最大，作者估算其 TCO 改善超过 `25%`，因为模型下载和索引更新会形成很大的连续垃圾区间。在线 workload 改善最小，因为写入仍然偏碎；即便如此，论文仍然报告在这种不理想场景里还有 `2%-5%` 的 TCO 收益。作者把这件事解释为鲁棒性：当 `discard` 不擅长处理某类 workload 时，系统会逐步退回到接近 compaction-only 的行为，而不是出现明显回退。

分项实验同样有价值，因为它证明最终收益不是由某个小技巧单独带来的。只打开 `discard` 加流控，就能把逻辑写放大降低 `8.4%-13.9%`；加入批处理后，又能继续降低 `2.7%-11.7%`；再加上 `boundary extension`，还会再降 `5.5%-16.1%`。这说明跨层对齐问题并不是边角料，而是决定 GC 效率的主因之一。trim 实验也支持这一点。在 SSD model A 上，单开 trim 就能把物理写放大从 `1.4` 降到 `1.3`；但在 trim IOPS 明显不足的 model B 上，必须再加 filter 和 merger，才能把物理写放大和删除延迟压回可部署范围。整体来看，实验确实支撑了论文主张：`discard` 本身有效，但只有配套的系统工程做到位，收益才不会被副作用吞掉。

## 创新性与影响

这篇论文的创新点不在于发明了一个新的 SSD 接口，也不只是改进了一个 `compaction` heuristic。它真正提出的是一种跨层 GC 方案：在生产级分布式 append-only 存储栈里，把 `discard` 提升为主回收路径，再用边界修复、调度控制和 trim 优化把这条路径做成安全、稳定、可落地的系统。相对那些让主机直接接管闪存管理的方案，这篇论文选择的是更难但也更现实的目标：保留商用 SSD 和既有云存储栈，只在系统内部做协同改造。

因此，这篇论文的影响更可能先落在工程实践上。做云存储运营的人可以把它当成生产证据，说明只要 `discard` 路径足够精细，确实可以换到真金白银的 TCO 节省。做 log-structured block、object 或 KV 系统的人，也能从中学到一个更一般的教训：想靠“少搬数据”获益，前提是整条栈在对齐单位和速率约束上达成一致。就这个意义上说，它既是一个新机制，也是一篇有很强操作指导价值的部署论文。

## 局限性

这套方案的收益高度依赖 workload。论文自己也承认，`SAR` 和离线 trace 最适合 `DisCoGC`，因为它们会产生大段连续失效区间；而碎片化更强的在线 workload 收益明显更小。换句话说，`DisCoGC` 不是对所有 append-only 系统都成立的普适替代，它只是在覆盖局部性足够强时，才比 `compaction` 更像合理默认值。

此外，这个设计和 ByteDrive + ByteStore 耦合得很深。它需要同时修改 `BlockServer`、ByteStore SDK、UFS 布局、EC stripe 规格以及监控与恢复路径。这样的确让论文更像扎实的系统工作，但也意味着它没有展示一个对通用存储栈“低成本接入”的路线。最后，评估主要是与 ByteDance 自己的 compaction-only baseline 比较。这个 baseline 对生产决策是最正确的，但它仍然没有回答：如果从头改用 host-managed flash，或者更激进地重写上层 allocator，收益会不会进一步扩大。

## 相关工作

- _Lu et al. (FAST '13)_ - 研究文件系统行为如何放大 flash 写入，而 `DisCoGC` 把问题推进到分布式 append-only 存储栈，并用协同的 discard 与 compaction 来解决。
- _Bjørling et al. (FAST '17)_ - `LightNVM` 通过 open-channel SSD 让主机直接接管垃圾回收，而 `DisCoGC` 保留商用 SSD，只围绕现有 discard/trim 接口做跨层协同。
- _Lu et al. (ICDCS '19)_ - `OCStore` 将分布式对象存储与 open-channel SSD 联合设计，这篇论文则面向标准 SSD 上的 ByteDrive + ByteStore，重点是如何在不搬运有效数据的前提下回收大段失效区间。
- _Kim et al. (ATC '22)_ - `IPLFS` 用 discard 放弃本地 log-structured 文件系统中的旧空间，而 `DisCoGC` 需要在生产云存储里处理 EC 对齐、碎片化和 trim 速率限制等多层问题。

## 我的笔记

<!-- 留空；由人工补充 -->
