---
title: "Mantle: Efficient Hierarchical Metadata Management for Cloud Object Storage Services"
oneline: "Mantle 把 COSS 元数据拆成每命名空间的 IndexNode 与共享 TafDB，把深层路径解析变成单 RPC 查找，并把高冲突目录更新改成追加式 delta。"
authors:
  - "Jiahao Li"
  - "Biao Cao"
  - "Jielong Jian"
  - "Cheng Li"
  - "Sen Han"
  - "Yiduo Wang"
  - "Yufei Wu"
  - "Kang Chen"
  - "Zhihui Yin"
  - "Qiushi Chen"
  - "Jiwei Xiong"
  - "Jie Zhao"
  - "Fengyuan Liu"
  - "Yan Xing"
  - "Liguo Duan"
  - "Miao Yu"
  - "Ran Zheng"
  - "Feng Wu"
  - "Xianjun Meng"
affiliations:
  - "University of Science and Technology of China"
  - "Baidu (China) Co., Ltd"
  - "Tsinghua University"
  - "Institute of Artificial Intelligence, Hefei Comprehensive National Science Center"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764824"
project_url: "https://mantle-opensource.github.io/"
tags:
  - storage
  - filesystems
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mantle 把 cloud object storage 的元数据路径重构成“每命名空间一个 `IndexNode` + 跨命名空间共享的 `TafDB`”。`IndexNode` 只在内存里保存轻量级目录访问元数据，因此深层分层路径解析可以压缩成单次 RPC，而完整元数据仍由可扩展的 `TafDB` 承载。随后，Mantle 再用追加式 delta record 和本地 rename loop detection 消除更新热点，把查找与高冲突目录修改同时做快。

## 问题背景

论文的出发点很具体：现代 COSS 早已不是只存放扁平 blob 的后端。作者在百度生产环境里看到，支撑 analytics 和 ML 的命名空间往往有数十亿个条目，平均目录深度约为 `11`，最深可达 `95`，单命名空间峰值元数据吞吐达到数十万次每秒。此类工作负载会反复访问很深的对象路径，同时大量并发地创建、删除、重命名目录，而上层计算任务又对元数据延迟极其敏感。

标准 COSS 分层元数据架构在这里会暴露两个瓶颈。第一，路径解析太慢。代理收到 REST 请求后，需要在按父目录 ID 分片的元数据表上逐级解析路径；因为每一层都必须先拿到当前目录的 inode ID，才能算出下一层所在分片，所以一次 lookup 天然会展开成多轮 RPC，并在每一级做权限检查。论文测得，在 `objstat`、`dirstat` 和 `delete` 中，lookup 分别占到总元数据延迟的 `89.9%`、`91.2%` 和 `63.1%`。

第二，目录更新在共享目录上会严重冲突。`mkdir` 和跨目录 `dirrename` 之类操作要同时更新多个位置的元数据；如果父目录落在不同 shard 上，就必须走分布式事务。在 Spark 这类会把大量临时目录原子地搬入同一个输出目录的场景下，`mkdir` 与 `dirrename` 的吞吐相对无冲突场景分别暴跌 `99.7%` 和 `99.4%`。而很多 DFS 里的经典优化在 COSS 里并不好用，因为代理是无状态的，API 很窄，客户端也不能配合做缓存或推测执行。

## 核心洞察

Mantle 最重要的判断是：COSS 元数据里“必须 scale out 的部分”和“决定 lookup 快慢的部分”应该拆开管理。一次路径解析或 rename 协调并不需要完整目录状态，它真正依赖的只是父子关系、目录 ID、权限以及一个锁位。如果把这部分访问元数据放进每命名空间一个的内存服务里，而把完整元数据继续留在可扩展的共享数据库中，那么路径解析就能在不牺牲命名空间规模的前提下变成单 RPC。

这套拆分还能顺便重写更新路径。一旦 `IndexNode` 持有某个命名空间的权威目录索引，rename 的 loop detection 就不必再做分布式搜索，而可以在本地完成；一旦 `TafDB` 里的热点目录属性更新不再原地覆盖同一行，而改成追加独立 delta，绝大多数写写冲突也会消失。换句话说，Mantle 不是分别修补 lookup 与 update 两个点问题，而是通过一次架构重划，同时改变两条关键慢路径。

## 设计

Mantle 由三部分组成：沿用的 proxy layer、共享的分片元数据库 `TafDB`，以及每个 namespace 独占一个的 `IndexNode`。`TafDB` 保存所有 namespace 的完整元数据；`IndexNode` 只保存每个目录大约 `80` 字节的访问元数据，包括父目录 ID、目录名、目录 ID、权限和锁位。论文把这称为目录 access metadata 与 attribute metadata 的拆分。lookup 与权限检查在 `IndexNode` 上完成，而可扩展的对象元数据存储、绝大多数属性读写仍由 `TafDB` 负责。

第一组关键机制是单 RPC lookup。proxy 把整条路径发给 `IndexNode`，后者在内存里完成解析，而不是在数据库分片间来回跳转。为了避免 CPU 开销重新把 `IndexNode` 变成瓶颈，Mantle 设计了 `TopDirPathCache`，但它不缓存完整路径，而只缓存距离叶子至少 `k` 层的截断前缀。作者的理由是：上层前缀更稳定，而接近叶子的目录最容易被 rename。每个 cache entry 保存解析后的目录 ID 以及沿路径聚合后的权限掩码。系统最终选择 `k = 3`，因为它只需要“缓存所有路径”方案 `12%` 的内存，却保留了大部分时延收益。

缓存一致性由 `Invalidator` 负责。它结合了记录正在被修改目录的 `RemovalList`，以及覆盖所有已缓存路径的 radix-tree `PrefixTree`。lookup 先检查请求路径是否与 in-flight 修改重叠；若重叠，就直接绕过缓存并在索引上逐级查找。否则，它可以从命中的截断前缀继续解析剩余后缀。并且只有在 lookup 期间没有并发修改穿插进来时，新的解析结果才会写入缓存。这样做避免了重锁，同时又不会让 rename 或属性更新后的过期前缀长期残留。

Mantle 还把 `IndexNode` 背后的 Raft 复制组真正用来扩展读吞吐，而不是只做热备。follower 和 learner 在向 leader 查询 `commitIndex`、并等待本地 `applyIndex` 追平之后，也可以对外提供路径解析服务，因此读吞吐不再被单节点封顶。为了避免 follower 上的本地缓存过期，cache invalidation 信息会通过 Raft log 复制，使各副本的缓存状态足够一致。

更新路径对应第二组机制。针对 `mkdir`/`rmdir` 对热点父目录属性的争用，Mantle 在 `TafDB` 中引入 delta record：它不再原地重写父目录属性行，而是为每个事务追加一条以父目录 ID、特殊名字 `/_ATTR` 和事务时间戳为键的 delta。后台 compaction 再把这些 delta 合并回主属性记录。这样，原本会反复 abort/retry 的写写冲突就被变成了彼此独立的 append。代价是 `dirstat` 需要扫描 delta，因此系统只会在目录持续高冲突时启用它。

跨目录 `dirrename` 也被重新放到 `IndexNode` 上协调。proxy 先让 `IndexNode` 解析源路径和目标路径、给源目录加锁，并检查从两条路径最近公共祖先到目标目录的那段路径里是否会形成循环。如果没有锁冲突、也不存在 loop，proxy 再通过一次分布式事务同时更新 `TafDB` 与 `IndexTable`。最后，`IndexNode` 的写路径还使用 Raft log batching 来摊薄频繁 `fsync` 的成本。容错方面，系统依赖 Raft 保证复制一致性，并用请求 UUID 让新的 proxy 能安全接管一次中断的 rename。

## 实验评估

实验部署在 `53` 台服务器上，预先向每个系统装载一个 `1B` 条目的 namespace，对象与目录比例为 `10:1`，并与作者重实现的 Tectonic、LocoFS、InfiniFS 比较。工作负载既包括 mdtest 微基准，也包括 Spark analytics 和 AI audio preprocessing 两个真实应用，因此能够分别验证论文的两个核心主张：lookup-heavy 路径是否更快，以及 contention-heavy 目录修改是否真正被解开。

在对象操作和目录读操作上，Mantle 始终最快。论文总结的 lookup latency 降幅相对 Tectonic 为 `83.9-89.0%`，相对 InfiniFS 为 `80.0-84.2%`，相对 LocoFS 为 `16.4-74.5%`；对应吞吐提升分别达到 `2.49-4.30x`、`1.96-3.44x` 和 `1.07-2.50x`。更有说服力的是路径深度实验：十层路径相对单层路径会让 Tectonic 的 lookup latency 增加 `6.82x`，InfiniFS 增加 `6.4x`，而 Mantle 只增加 `1.09x`，这直接支持了“单 RPC lookup 消除路径深度敏感性”的中心论点。

在目录修改上，最重要的结果来自高冲突场景。Mantle 相对 Tectonic、InfiniFS、LocoFS 的加速分别达到 `1.20-20.90x`、`1.16-116.00x` 和 `2.87-80.78x`。大规模实验中，它在高冲突下实现了 `58.8K` 次 `mkdir`/秒和 `38.0K` 次 `dirrename`/秒。ablation 也比较扎实：`TopDirPathCache` 让 `dirstat` 吞吐翻倍，Raft log batching 提升无冲突 `mkdir`，delta record 基本消除了高冲突 `dirrename` 的失败重试，而 follower read 则把 `objstat` 扩展到带两台 follower 和两台 learner 时的 `1.8945M` 次/秒。

应用级结果进一步证明这不是只对 mdtest 生效的系统优化。启用真实数据访问后，Mantle 让 Spark analytics 的端到端完成时间相对 Tectonic、InfiniFS、LocoFS 分别缩短 `73.2%`、`93.3%` 和 `63.3%`；对 audio preprocessing，则分别缩短 `47.7%`、`40.1%` 和 `38.5%`。论文还提供了 `19` 个内部 namespace、超过 `1.5` 年的生产部署经验，这显著增强了可信度。评估上的主要保留意见是：三个基线系统都来自作者重实现而非原始代码，因此即使作者声称性能与原论文一致，比较仍然存在一定不确定性。

## 创新性与影响

相对 _Pan et al. (FAST '21)_ 的 Tectonic，Mantle 把 object storage 中按路径长度增长的多轮 RPC 元数据遍历，换成了每命名空间一个的内存索引所提供的单 RPC lookup。相对 _Li et al. (SC '17)_ 的 LocoFS，Mantle 并不是简单把所有目录逻辑丢给一个专用节点，而是只把最窄的 access metadata 放进去，把完整元数据继续留在可扩展数据库。相对 _Lv et al. (FAST '22)_ 的 InfiniFS，Mantle 不再依赖 speculative parallel lookup，而是让正常路径本身更便宜。

它更大的影响在于重新定义了“分层 object-storage 元数据服务”这个问题：关键不只是把数据库表做得更快，而是把 lookup control plane 从完整元数据平面里剥离出来。对于正在为 analytics 和 AI 工作负载设计 S3-like 服务的云存储团队来说，这种 framing 很可能比某个单独优化更有价值。论文属于新的机制与架构设计，而不是测量论文；真正的新意是 access/attribute metadata 拆分、带轻量一致性维护的单 RPC lookup，以及用 delta record 消除更新冲突的组合。

## 局限性

Mantle 并没有消除 `IndexNode` 的单节点属性，只是把它做到足够高效，能够支撑当前工作负载。论文自己也承认，`IndexNode` 的 CPU 已经成为下一步的可扩展性瓶颈，而写吞吐仍受限于单个 Raft 组。作者展示的 RDMA 原型说明这里还有优化空间，但当前系统仍明显依赖这个“每命名空间中心节点”的执行效率。

设计收益也依赖工作负载形态。`TopDirPathCache` 之所以成立，是因为上层路径前缀相对稳定，而大多数 rename 发生在更靠近叶子的目录。论文并没有深入评估更扁平的 namespace，或频繁重命名高层目录的场景；在这些情况下，cache hit rate 可能变差，invalidator 的收益也会下降。delta record 同样带有代价，它提升写可扩展性的同时会增加 `dirstat` 成本，因此系统只能按需启用，而不是一刀切地全局打开。

评估方法也有现实边界。最强的对照系统来自作者重实现而不是原始实现；Tectonic 还采用了放宽一致性的变体，而 metadata caching 更多是额外实验而不是统一基线维度。这些选择不足以推翻 Mantle 的主要结论，但会让“领先幅度到底有多大”这个问题保留一些余量。

## 相关工作

- _Pan et al. (FAST '21)_ - Tectonic 代表了 cloud object storage 里的 DB-table 元数据路线；Mantle 保留可扩展数据库后端，但用 `IndexNode` 去掉了多轮路径遍历。
- _Li et al. (SC '17)_ - LocoFS 同样把目录元数据与对象元数据分离，但它的专用目录节点仍是协调热点；Mantle 通过更窄的 access-metadata 拆分来避免这一点。
- _Lv et al. (FAST '22)_ - InfiniFS 依赖 speculative parallel RPC 和 caching 来加速 lookup，而 Mantle 直接把 lookup 做成单 RPC，并用 follower 与 learner 扩展读吞吐。
- _Wang et al. (EuroSys '23)_ - CFS 通过缩小 critical section 来降低分布式文件系统元数据协调成本，而 Mantle 面向 COSS 场景，进一步加入 delta record 和本地 loop detection 来处理 rename-heavy 负载。

## 我的笔记

<!-- 留空；由人工补充 -->
