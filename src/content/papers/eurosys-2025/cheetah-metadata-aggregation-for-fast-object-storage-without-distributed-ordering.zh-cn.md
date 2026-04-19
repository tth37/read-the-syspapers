---
title: "Cheetah: Metadata Aggregation for Fast Object Storage without Distributed Ordering"
oneline: "Cheetah把一次 put 需要的元数据收进 MetaX，让元数据写入与数据写入并行执行，从而在不牺牲一致性的前提下加速小对象存储。"
authors:
  - "Yiming Zhang"
  - "Li Wang"
  - "Shengyun Liu"
  - "Shun Gai"
  - "Haonan Wang"
  - "Xin Yao"
  - "Meiling Wang"
  - "Kai Chen"
  - "Dongsheng Li"
  - "Jiwu Shu"
affiliations:
  - "Shanghai Key Laboratory of Trusted Data Circulation, Governance and Web3"
  - "NICE XLab, XMU"
  - "KylinSoft"
  - "SJTU"
  - "Huawei Theory Lab"
  - "HKUST"
  - "NUDT"
  - "Tsinghua University"
conference: eurosys-2025
category: storage-memory-and-filesystems
doi_url: "https://doi.org/10.1145/3689031.3696080"
tags:
  - storage
  - crash-consistency
  - fault-tolerance
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Cheetah 把一次 put 用到的元数据合并成 MetaX，在 meta server 上原子写入，同时把对象数据并行写到 raw-block data server。对于 immutable object，这样就能拿掉关键路径上的 distributed ordering，同时保持一致性。

## 问题背景

论文针对的是 Haystack 这一类目录式对象存储。对象到 volume 的映射放在目录服务，对象在 volume 内的 offset metadata 则跟数据一起留在 data server。对小对象 put 来说，这意味着为了 crash consistency，client log、volume metadata、offset metadata 和 data 必须跨节点按顺序持久化；delete 也得在目录侧和数据侧来回更新。对象只有几 KB 到几百 KB 时，真正拖慢系统的常常不是数据写盘，而是这些元数据等待和 RPC。

另一条路线是 Ceph 这类 hash placement。它的扩展性更强，但系统扩容时会触发 data migration。于是问题变得很明确：能不能既保留目录式方案的 migration-free growth，又把小对象写路径上的 metadata ordering 去掉，同时在故障后仍然说得清楚谁已经 committed、谁该被回滚。

## 核心洞察

核心判断是，把一次 put 会一起提交、一起恢复、一起验证的元数据，直接视作一个原子对象。MetaX 把对象到 volume 的映射、volume 内 extents、checksum 和请求日志收在一起；只要 MetaX 在 meta server 上原子落盘，data 就可以并行复制到 raw-block data server。这样，一致性不再依赖跨三个组件的分布式写顺序，而是依赖 MetaX 的本地原子性、对象在双侧都完成前保持不可见，以及 immutable object 不会覆盖旧状态。

为了让这个思路能扩展，论文进一步区分 metadata migration 和 data migration：前者可以接受，后者尽量避免。于是 Cheetah 用 CRUSH 只管理 metadata placement，再用 PG 绑定 VG 的方式把 data 固定住。

## 设计

Cheetah 有四类角色：运行 Raft 的 manager cluster，保存 MetaX 的 meta server，提供 raw-block 读写的 object-agnostic data server，以及对外暴露 put/get/delete 的 client proxy。MetaX 通过 `OBMETA_name`、`PGLOG_pgid_opseq`、`PXLOG_pxid_reqid` 这类 KV 原子写入保存。

put 路径是核心。client proxy 先把对象名映射到一个 PG，再用 CRUSH 找到这个 PG 的 primary meta server。primary 负责分配 logical volume 和 extents，并把 MetaX 持久化到自己和 backup meta server。与此同时，proxy 把对象数据连同 `lvid/extents` 发给 data replicas，让它们直接写 raw blocks。只有 meta replicas 和 data replicas 都返回成功，put 才算 committed；在此之前对象一直是 pending，避免不同 get 读到不一致副本。

扩展性来自 hybrid PG/VG mapping。CRUSH 只负责把 PG 映射到 meta server，而每个 PG 还绑定一个 volume group，只有该 PG 的 primary meta server 才能从这个 VG 分配 logical volume。这样，meta server 扩容时迁移的是 PG 所属关系和 metadata，不是 object data。delete 也因此变得很轻：只需要删除 MetaX 并清理位图。恢复则依赖复制后的 MetaX、checksum、view number 和 lease 去补齐或撤销未完成的 put；论文宣称同一对象上的操作满足 linearizability。

## 实验评估

实验平台共有 15 台机器，其中 3 台同时承担 client 和 manager，9 台做 data machine，3 台做 meta machine，metadata 和 data 都是三副本。micro benchmark 重点测 8 KB、64 KB 和 512 KB 对象；作者也明确说明，1 MB 及以上时各家系统会因为 bulk data I/O 占主导而变得接近。

和 Haystack 相比，Cheetah 的 mean put latency 最多降低 2.37x，mean get latency 最多降低 25%；8 KB put 在并发 1000 时，峰值吞吐仍大约高 6%。ablation 结果也支持论文主张：把 data path 改成 filesystem-backed 的影响只有约 10%，而把 distributed ordering 加回去，吞吐损失最高能到 40%。这说明主要瓶颈确实在跨节点写顺序，而不是某个单独的数据路径实现。

系统层面的结果也和设计目标一致。meta service 随 meta machine 增加接近线性扩展；带 VG 的扩容过程不会像无 VG 版本那样触发 data migration，也不会像 Ceph 那样在迁移期掉速。meta server 故障后的 metadata 在几秒内恢复，磁盘恢复大约需要 16.3 秒，聚合带宽达到 24.9 GB/s。三周生产 trace 下，Cheetah 仍优于 Haystack，存储效率保持在 85% 以上。

## 创新性与影响

Haystack 和 Tectonic 把一次写入涉及的状态分散在多个服务里；Cheetah 把它们收成一个原子 MetaX 记录。Ceph 用 CRUSH 解决可扩展 placement；Cheetah 把 CRUSH 用在 metadata 上，再通过 VG 保证扩容时 data 不动。后续做 crash-safe metadata path、write-heavy object storage 的工作，很可能都会把它当成参照系。

## 局限性

第一，Cheetah 强依赖 immutability 和上层唯一命名；一旦要支持 overwrite，就得引入唯一子名或 two-phase commit。第二，它的收益主要集中在 small-object 场景，作者自己也承认对象到 1 MB 以上时差距会明显缩小。第三，系统依赖同步复制、view 切换和 lease 协调，恢复期间受影响的 PG 或 VG 可能暂停写入，因此可用性上的代价并没有被完全消除。

## 相关工作

- _Beaver et al. (OSDI '10)_ - Haystack同样采用目录式对象放置，但 volume metadata 和 offset metadata 仍然分离，因此 put 依旧受跨节点有序写入约束。
- _Pan et al. (FAST '21)_ - Tectonic通过分层分片元数据统一多类存储系统，而 Cheetah 把单个对象写路径压缩成一个 MetaX 记录，重点优化 immutable small-object I/O。
- _Wang et al. (FAST '20)_ - MapX解决的是 Ceph-RBD 和 Ceph-FS 在扩容时的数据迁移问题，而 Cheetah 面向 object storage，同时处理扩容迁移和元数据提交路径的开销。
- _Weil et al. (OSDI '06)_ - Ceph提供了可扩展的 CRUSH placement，而 Cheetah 只把 CRUSH 用在 metadata placement 上，再通过 volume group 避免扩容时搬迁 object data。

## 我的笔记

<!-- 留空；由人工补充 -->
