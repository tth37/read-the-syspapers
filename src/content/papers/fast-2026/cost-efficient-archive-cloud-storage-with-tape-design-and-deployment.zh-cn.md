---
title: "Cost-efficient Archive Cloud Storage with Tape: Design and Deployment"
oneline: "TapeOBS 用 HDD 暂存、批量 EC 与恢复调度，再配合 tape-aware 的库内执行，把磁带变成云归档后端，并将 10 年 TCO 模型压低 4.95x。"
authors:
  - "Qing Wang"
  - "Fan Yang"
  - "Qiang Liu"
  - "Geng Xiao"
  - "Yongpeng Chen"
  - "Hao Lan"
  - "Leiming Chen"
  - "Bangzhu Chen"
  - "Chenrui Liu"
  - "Pingchang Bai"
  - "Bin Huang"
  - "Zigan Luo"
  - "Mingyu Xie"
  - "Yu Wang"
  - "Youyou Lu"
  - "Huatao Wu"
  - "Jiwu Shu"
affiliations:
  - "Tsinghua University"
  - "Huawei Cloud"
  - "Minjiang University"
conference: fast-2026
category: reliability-and-integrity
tags:
  - storage
  - datacenter
  - fault-tolerance
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TapeOBS 是 Huawei Cloud 的归档对象存储服务，前面放一个小型 HDD pool，后面才是 tape pool。它最关键的招式，是把磁带视为“全异步、可批量调度的后端”，而不是同步对象存储：写入先落 HDD，恢复请求先重排再触达 tape，每个 tape library 内再用 SSD 元数据、dedicated drives 和 tape-aware 调度去规避磁带最糟糕的性能特性。按论文的 `10` 年模型计算，这让总 TCO 相比 HDD 归档服务降低 `4.95x`，而且系统上线后已经保存了数百 PB 的原始用户数据。

## 问题背景

云归档存储的工作点很特殊：数据规模极大、保留时间很长、读取极少，但用户仍然希望它具备 object API 和强持久性。磁带之所以诱人，是因为它比 HDD 更便宜、寿命更长、能耗更低，而且容量路线图也更明确。但 tape library 绝不是一个“更慢的磁盘柜”。在 TapeOBS 里，一个 library 大约有 `1000` 盘磁带，却只有 `4` 个 drive；一次 mount 大约要 `80` 秒；而磁带内部的随机读还会因为 wind/rewind 产生很高 seek 成本。

因此，简单把 HDD 后端替换成磁带，很快就会失效。同步的用户读写会直接暴露 tape pool 有限的聚合带宽；按对象做 erasure coding 会让一个对象分散到多个 library，恢复时吞掉多个 drive；把元数据放在磁带上则会制造大量随机寻址；如果 drive 在无关磁带之间来回切换，drive thrashing 会吞掉大部分时间。论文真正要解决的，不是“怎么用磁带存对象”，而是“如何把请求形状改造成磁带擅长处理的形式，让磁带真的能承担云归档后端”。

## 核心洞察

这篇论文最值得记住的判断是：磁带只有在服务边界被上移之后，才适合作为云归档存储介质。也就是说，用户可见的对象操作必须与磁带操作解耦，而磁带访问必须按批次调度。只要系统插入了这层异步边界，后续设计就可以围绕磁带的真实物理约束，而不是假装它是一个在线随机访问层。

这层边界带来三个连锁收益。第一，写入可以按预期生命周期分组，把寿命相近的数据放到同一批磁带上，从而降低后续 GC 重写的有效数据量。第二，可以把多个对象打包进一次 EC append，让小对象通常只落在一盘 tape 上，而不是跨很多盘。第三，restore 请求可以按 partition 分组、按 offset 排序，把原本随机的请求流重塑成具有物理局部性的访问流。后面所有库内优化，本质上都是为了把这几个批量决策真正执行出来。

## 设计

TapeOBS 由 service layer、index layer、persistence layer 和一个名为 DataBrain 的控制平面组成。Service layer 暴露 OBS API，并把对象操作翻译成 append-only 的 `PLog`。Index layer 维护对象 ID 到 `⟨plog-id, offset, size⟩` 的映射。Persistence layer 同时包含 tape pool 和 HDD pool；在生产环境里，HDD pool 的容量约为 tape 的 `4%`。MDC 负责分配 `plog-id`，并维护 partition view，把每个 partition 映射到跨 library 的 EC group。

第一项核心设计是“全异步 tape pool”。用户写入先被 HDD pool 吸收，再异步刷入 tape；restore 请求也不是直接读 tape，而是先由 DataBrain 调度，再把对象拷回 HDD pool。这样做一方面利用了 restore 的小时级 SLA，另一方面也利用了 HDD pool 更高的聚合带宽去吸收突发流量，从而避免把磁带延迟直接暴露给用户。

第二项关键设计是 batched erasure coding。TapeOBS 不再对每个对象单独做 EC，而是在 service layer 把多个对象聚成一次 `PLog append`，再把这一批数据编码后分散到多个 library。论文里的 `4+2` 例子中，前四个较小对象都只落在单盘 tape 上，只有第五个对象跨两盘，因此恢复一个对象通常需要更少的 drive。生产环境中，TapeOBS 使用的是 Huawei 的 `12+2` LDEC。

第三项是库内本地优化。每个 library 的 `4` 个 drive 被静态分成 `2` 个写盘、`1` 个读盘和 `1` 个内部盘，用于 GC、repair 与 consistency checking，从而减少不同任务之间的相互干扰。每个 head server 还配置两块 NVMe SSD：`MetaStore` 用 `256B` 的 sub-PLog 元数据记录物理位置，使得系统查位置时不必先碰磁带；`DataStore` 则在真正落 tape 前提供持久缓冲。磁带上的 metadata partition 和每 `4KB` 一个 DIF 让 SSD 元数据丢失后仍能恢复。最后，tape library scheduler 对一组读请求做 wrap-aware 的 SCAN 调度，并根据 drive buffer 做反馈式 flow control，把一次异常写带宽从约 `168.65 MB/s` 的退化水平拉回到 `336.53 MB/s`。

## 实验评估

论文的评估由三部分组成：经济模型、生产环境画像，以及少量针对局部机制的微基准。作者首先给出一个 `10` 年成本模型：初始容量 `100 PB`、年增长率 `50%`，在这个前提下，tape 方案相对 HDD 方案的 CapEx 低 `2.68x`，OpEx 低 `16.11x`，总 TCO 低 `4.95x`。部署方面，TapeOBS 目前是单 AZ 服务；每个 tape pool 由 `14` 个 rack 组成，总容量 `140 PB`；论文写作时系统已经保存了数百 PB 的原始用户数据。

工作负载数据基本支持作者的设计目标。小于 `500 MB` 的对象占用了 `93.81%` 的容量，而最大客户群的操作几乎全是写；表 4 中最高的读比例也只有 `0.674776%`。在一个代表性的 24 小时窗口里，HDD pool 的利用率稳定在 `71.625%-71.675%`，并受 `75%` watermark 控制；与此同时，tape pool 以比较平稳的速率消化分批写入的数据。Tape pool 的平均写吞吐是 `118.81K` append ops/min，而读吞吐极低，峰值只有 `5.85K` ops/min。

最具体的延迟结果，是把一个 stripe 持久化到 tape pool 前端 SSD 缓冲区所需的时间：中位数为 `18.51 ms`，`P99` 为 `27.75 ms`。这说明论文在“让 tape-backed archive service 具备可运营性”这个目标上拿出了实证。不过，论文并没有给出端到端的 restore latency 分布，也没有直接对比旧 HDD 归档服务与新 tape 服务在生产上的 A/B 结果，因此它对“可行性”和“经济性”的论证强于对用户可见时延的论证。

## 创新性与影响

这篇论文的创新，不是单独发明一种新磁带格式，也不是单独提出一个新 EC 算法，而是把多层 tape-aware 机制组合成了一个可落地的云服务设计：异步 staging、按生命周期聚批、service-layer b-EC、dedicated drives、SSD 元数据，以及 drive-aware 的本地调度。它是一篇很典型的 systems-and-deployment paper，因为它真正回答了“要让磁带承担生产级对象存储后端，架构上必须退让和重构哪些地方”。

这对云存储架构师、冷数据基础设施运营者，以及研究归档介质替代 HDD 的系统研究者都很有价值。它也给那些停留在“设备抽象”或“文件系统抽象”的冷存储论文提供了一个对照：一旦系统真的要满足 object-storage 语义，并在生产规模上运行，真正的难点往往出现在控制面、调度和库内执行细节上。

## 局限性

论文对一些约束讲得比较坦率，同时也能从设计里看出更多限制。首先，TapeOBS 目前只是单 AZ 服务。其次，dedicated drives 是静态划分的，因此工作负载波动较大时，某些 drive 可能被闲置；作者也把更粗粒度的动态重分配留作未来工作。再次，batched EC 虽然降低了常态恢复时的 fan-out，但会放大 degraded read 的代价：如果故障盘上的对象大小为 `S`，重建时可能需要 `S × m` 的数据量。

这套设计还依赖较强的运营余量。HDD pool 只有 tape 容量的大约 `4%`，但其中 `25%` 空间必须被刻意留空，以吸收突发和故障。论文目前不支持 deduplication，也没有启用 tape 内建压缩，因为大量用户数据本身已经加密。最后，评估重点放在系统内部指标上，缺少跨多小时 SLA 档位的 restore 尾延迟，以及与其他云归档服务的直接对照。

## 相关工作

- _Pease et al. (MSST '10)_ — LTFS 用硬件分区和 XML metadata 把 tape 暴露成文件系统；TapeOBS 则把 metadata 放到 SSD 上，并对外暴露异步对象服务。
- _Koltsidas et al. (ICDE '15)_ — GLUFS 在分布式文件系统里整合 disk 与 tape；TapeOBS 的重点则是云对象语义、跨 library 的 batched EC，以及 restore 调度。
- _Gharaibeh et al. (MSST '14)_ — DeduT 研究 tape system 上的 deduplication；TapeOBS 则把设计预算放在批量化、放置策略和 drive 级执行上。
- _Zhou et al. (FAST '23)_ — SMRSTORE 展示了基于 HM-SMR drives 的归档对象存储；TapeOBS 选择了更便宜但运维更棘手的磁带点位，此时 mount 成本和 drive contention 成为主导问题。

## 我的笔记

<!-- 留空；由人工补充 -->
