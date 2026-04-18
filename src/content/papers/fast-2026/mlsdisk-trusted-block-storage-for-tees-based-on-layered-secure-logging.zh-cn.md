---
title: "MlsDisk: Trusted Block Storage for TEEs Based on Layered Secure Logging"
oneline: "MlsDisk 用 layered secure logging 取代 SGX-PFS 的全盘 Merkle 树级联更新，把 TEE 的可信块存储改成顺序追加，同时保住 CIFC 语义。"
authors:
  - "Erci Xu"
  - "Xinyi Yu"
  - "Lujia Yin"
  - "Xinyuan Luo"
  - "Shaowei Song"
  - "Qingsong Chen"
  - "Shoumeng Yan"
  - "Jiwu Shu"
  - "Hongliang Tian"
  - "Yiming Zhang"
affiliations:
  - "SJTU"
  - "Ant Group"
  - "NICE Lab, XMU"
  - "THU"
conference: fast-2026
category: reliability-and-integrity
code_url: "http://github.com/asterinas/mlsdisk"
tags:
  - storage
  - confidential-computing
  - security
  - crash-consistency
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`MlsDisk` 是一个面向 `TEE` 的 secure virtual disk，它用四层 log-structured 设计替代了 SGX-PFS 的全盘 Merkle 树更新路径。核心做法是把用户数据、索引、日志和日志元数据放进不同的安全抽象里，让真正需要付出 Merkle 树代价的只剩下小型元数据结构。这样它在保持 confidentiality、integrity、freshness、consistency（`CIFC`）的同时，把写密集场景下相对 `PfsDisk` 的性能提升到 `7.3x-21.1x`，并把 trace-driven workload 的性能提升到 `1.4x-3.6x`。

## 问题背景

TEE 保护的是内存，不是底层 host disk。实际部署里，unmodified file system、数据库和其他应用仍然需要一个可信块设备，才能把数据持久化到不受信任的主机上，同时不暴露给恶意宿主机。论文要满足的目标比“把磁盘加密”更强：磁盘既要防 snooping，也要防 tampering、单块回滚，以及 crash 后的不一致，这四项被统一表述为 `CIFC`。

问题在于，现有最强的 `SGX-PFS` 通过覆盖整个磁盘状态的 Merkle Hash Tree 来保证这些语义，而每次覆盖写都会触发从叶子到根的级联更新。论文指出，如果树高为 `H`，一次写入就可能带来 `H` 次额外更新；再加上 recovery journal，放大因子大约会变成 `2H`。结果就是 secure storage 被迫表现成一个 metadata 极重、随机写极多的系统。论文的动机实验也验证了这一点：只提供 confidentiality 和 integrity 的 `CryptDisk`，在 trace-driven benchmark 上已经比 `SGX-PFS` 快约 `4.1x`，在 4 KiB 随机写上快约 `2.5x`。

append-only log 看起来像一个自然出路，因为它能把覆盖写转成顺序写，也天然保留旧版本用于恢复。但论文中的 `NaiveLog` strawman 说明，这条路并不完整：没有索引时，读操作要从尾到头扫描整段历史；没有垃圾回收时，空间占用会无限增长。直接复用成熟存储引擎也不理想，因为正确性和安全性会缠在一起，难以证明。论文真正要解决的问题因此变成：能否保留 logging 的性能收益，同时又不失去对 freshness 和 crash consistency 的系统化控制？

## 核心洞察

这篇论文最关键的命题是：只有把安全存储职责按“层”拆开，而不是塞进一个单体磁盘格式里，secure logging 才真正可控。`MlsDisk` 不试图用一种通用机制同时保护用户块、索引、文件元数据和 journal state。相反，每一层只负责保护自己的 payload，再把自己的元数据交给下一层，而下一层已经提供 `CIFC`-compliant 的持久化抽象。

这样的分层会直接改变成本结构。最上层的用户块可以 out-of-place 地按大批量顺序写出，因为它们的 encryption key、MAC 和物理地址都放在索引里，而不是嵌进一个全盘 Merkle 树。索引本身可以使用 `LSM-tree`，因为它的 `WAL` 和 `SSTable` 又是通过事务化 secure log 来持久化。真正带有 Merkle 树开销的，只剩下这些相对较小的日志；而这些日志的根元数据又会继续下沉到一个为 append 和 recovery 优化的小 journal 中。论文最值得记住的一点是：`CIFC` 在这里是通过组合得到的。某一层之所以安全，不是因为所有字节都参与同一条更新链，而是因为它的元数据被下一层安全地保住了。

## 设计

`MlsDisk` 一共分四层。`L3` 是应用看到的 block I/O layer。它会把 4 KiB 的 logical block 聚成批，分配新的连续 host block address（`HBA`），为每个块生成新 key，计算 `AES-GCM` MAC，把密文顺序写到磁盘上，然后把映射记成 `LBA -> (HBA, key, MAC)`。这些映射保存在 `Logical Block Table` 中，同时 `Reverse Index Table` 维护 `HBA -> LBA`，供垃圾回收使用；`Block Validity Table` 则标记每个物理块是 free、used 还是 invalid。

`L2` 用一个事务化 `LSM-tree`，也就是 `TxKV`，来实现这个索引。每条插入先进入 `WAL`，再进入 `MemTable`，最后刷成 `SSTable`。关键点在于，flush 和 compaction 不是后台偷偷执行的“尽力而为”动作，而是通过下一层事务接口完成，所以索引结构本身也具备 crash consistency。`L1` 就提供了这个抽象：`TxLogStore` 管理 append-only secure log，支持事务化 create、append、read、delete 和 commit。每个 `TxLog` 内部仍然有自己的 Merkle 树，但其元数据保存在内存里的 `TxLogTable` 中。

`L0` 通过 `EditJournal` 来保护这张表。它把 `CryptoChain` 用于 append-only edits，把 `CryptoBlob` 用于周期性的 authenticated snapshot。这里论文有意保留了一个与 `NaiveLog` 类似的链式结构，但它只作用于几 MB 的元数据，而不是全部用户数据。恢复流程也是自底向上：先恢复 `L0` 的最新有效 snapshot 并回放后续 edit，再把 `L1` 各个 log 重建到有效长度，接着从 `WAL` 和 `SSTable` 重建 `L2`，最后向 `L3` 暴露一致的索引。垃圾回收以 16 MiB segment 为单位进行，并且通过事务化更新逻辑索引、反向索引、validity bitmap 与 allocation log 来保证安全；只有元数据提交成功后，旧数据块才会真正被回收。论文还进一步引入了 delayed reclamation，把旧块回收 piggyback 到 `LSM` compaction 上，以及 two-level caching，避免 Merkle 节点和用户数据争抢同一层 cache。

## 实验评估

实验在一台 Intel SGX 机器和一台 AMD SEV 机器上进行，三种 secure virtual disk 都提供 `100 GB` 用户可见容量，并配有 `1.5 GB` cache。对比对象是 `CryptDisk` 和 `PfsDisk`。`MlsDisk` 本身约需 `2%` 的元数据空间，并额外保留 `10%` 作为 delayed reclamation 的 over-provisioning。这个对比设置基本对准了论文目标：它比较的是 secure virtual disk 的几条主要设计路线，而不是不相干的上层文件系统实现。

核心结果支持论文主张。在 `FIO` 中，`MlsDisk` 相对 `PfsDisk` 的写性能提升达到 `7.3x-21.1x`，读性能提升达到 `1.4x-2.4x`。相对 `CryptDisk`，它在随机写上尤其强：SGX 上是 `1.1x-8.9x`，SEV 上是 `1.1x-6.8x`；而顺序写和顺序读只付出较小额外开销。五个 datacenter trace-driven workload 上，它相对 `PfsDisk` 的性能提升为 `1.4x-3.6x`，并且在写密集的 `wdev` 上相对 `CryptDisk` 也快约 `2.5x`。Filebench 中又取得了 `1.4x-2.3x` 的提升，而数据库评测也足够诚实：`BoltDB` 提升 `4.2x-5.5x`，`PostgreSQL` 提升 `1.3x-4x`，但 `SQLite` 与 `RocksDB` 基本持平，因为它们自己的写路径已经偏 log-structured。

敏感性分析让这些结果更可信，而不是只在一个甜蜜点上获胜。随着磁盘逐渐写满，写放大只从 `1.025` 增加到 `1.115`，在接近满盘时 `MlsDisk` 仍比 `CryptDisk` 快 `8.2x`。cleaning 也很关键，因为一旦关闭，系统在若干轮随机写后就会耗尽大块连续空闲空间。两个优化确实有效：delayed reclamation 让 4 KiB 随机写吞吐提高 `31%`，two-level caching 让随机读提高 `18%`。需要注意的是，论文在评测中没有开启第 8 节的可选扩展，所以这些结果证明的是基础 `CIFC` 系统，而不是已经完整实现了 whole-disk rollback 或 eviction attack 防御的系统。

## 创新性与影响

这篇论文的创新点并不只是“把 secure storage 改成用日志”。真正的新东西在于，它给出了一套可组合的存储架构，既让安全论证更清晰，也让 log-structured 的性能优势能真正释放。相较于 `SGX-PFS` 与 `SecureFS`，`MlsDisk` 把主数据路径从“全局、原地更新的 Merkle 维护”中解放出来。相较于 `Speicher` 这类 secure `LSM` 工作，它不是把一个复杂存储引擎整体搬进 TEE 再试图补证明，而是有意识地把不同机制放在最容易维持不变量的层里。

因此，这篇论文对 confidential computing 和存储系统两边都有价值。对于构建 `SGX`、`SEV` 等持久化服务的人来说，它说明 secure virtual disk 不必在“强安全语义”和“可用吞吐”之间二选一。更一般地，它还给出了一个重要观点：分层组合不仅是证明技巧，也是性能技巧，因为它把昂贵的加密元数据维护限制在最小的必要范围内。

## 局限性

`MlsDisk` 最擅长的仍然是 secure random overwrite 多的场景。面对顺序 workload，它相对 `CryptDisk` 的优势会缩小；像 `SQLite`、`RocksDB` 这种本身已经把写入整理成日志的系统，收益也有限。这个设计还依赖运行时余量：论文明确要求再预留 `10%` 磁盘空间给 delayed reclamation，而且如果不做 cleaning，连续空闲空间很快就会枯竭。

它在安全和并发上也有边界。论文的主评测没有启用 irreversibility 和 sync atomicity 扩展，因此 whole-disk rollback 与 eviction attack 仍然属于“提出了办法，但未在主系统中完整展示”的范围。`TxLogStore` 也不是一个提供完整通用隔离级别的事务系统，而是通过禁止同一日志并发写、lazy deletion 和随机 log ID 来降低冲突概率。这些选择是务实的，但也说明 `MlsDisk` 更像是一个针对 secure virtual disk 场景精心设计的专用系统，而不是任何事务存储栈都能直接套上的通用底座。

## 相关工作

- _Kumar and Sarangi (RAID '21)_ — `SecureFS` 在 `CryptDisk` 风格方案之上补充 freshness，但仍主要依赖 in-place 的元数据管理；`MlsDisk` 则改用分层、log-structured 的组合式设计。
- _Bailleu et al. (FAST '19)_ — `SPEICHER` 在 `SGX` 内保护 `LSM` key-value store，而 `MlsDisk` 用自定义分层原语提供透明 secure block device，并显式处理跨层恢复。
- _Angel et al. (OSDI '23)_ — `Nimble` 提供 rollback-resistant trusted storage，`MlsDisk` 可以把它用作 irreversibility 扩展的基础，但 `MlsDisk` 的核心贡献仍是 `CIFC` virtual-disk 架构本身。
- _Tian et al. (FAST '25)_ — `AtomicDisk` 关注 TEE 存储中的 eviction attack 与 sync atomicity，而 `MlsDisk` 的重点是 layered secure logging，并把 sync atomicity 作为扩展能力讨论。

## 我的笔记

<!-- 留空；由人工补充 -->
