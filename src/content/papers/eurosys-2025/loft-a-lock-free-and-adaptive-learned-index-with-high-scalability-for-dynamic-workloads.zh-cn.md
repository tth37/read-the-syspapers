---
title: "LOFT: A Lock-free and Adaptive Learned Index with High Scalability for Dynamic Workloads"
oneline: "LOFT 用基于 CAS 的误差有界插入、溢出 learned bucket 和 shadow node 重训练，把 learned index 从怕写入的结构改造成能在动态负载下继续扩展的并发索引。"
authors:
  - "Yuxuan Mo"
  - "Yu Hua"
affiliations:
  - "Wuhan National Laboratory for Optoelectronics, School of Computer, Huazhong University of Science and Technology"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717458"
code_url: "https://github.com/yuxuanMo/LOFT.git"
tags:
  - databases
  - memory
  - transactions
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

LOFT 的判断很激进也很有效：concurrent learned index 不必死守节点内严格有序，只要每个 key 仍落在模型给出的一个很小搜索区间里就够了。基于这个判断，它把插入改成区间内的 `CAS` 占位，把真正溢出的记录放进小型 learned bucket，再用 shadow node 在后台重训练，最终在动态负载上把吞吐最高做到现有 learned index 的 `14x`，尾延迟也明显更低。

## 问题背景

learned index 之所以吸引人，是因为它能用模型替掉一部分指针密集的树结构，在内存型 key-value store 里既省空间，也省遍历成本。但这套优势基本建立在数据分布稳定的前提上。一旦 workload 里持续插入，模型拟合就会变差，现有方案只能在两种坏选择之间摇摆。XIndex、FINEdex 这类 out-of-place 设计把新数据放进旁路 buffer，结果是 read 需要额外探测，background retraining 一旦跟不上，尾延迟就会上来。ALEX+、LIPP+、SALI 这类 in-place 设计把数据尽量留在原节点，可一旦 predicted position 被占，就会触发 shift、chain 新节点或 coarse-grained lock。论文给出的动机实验很扎实：插入比例只到 `5%`，learned index 吞吐平均就会掉约 `50%`，而最强的并发版本大多也只扩到 `24` 线程左右。

重训练又把问题放大了一层。blocking retraining 会直接卡住节点；完全异步的 retraining 虽然不堵前台，却会让旧模型服役太久，buffer 和预测误差一起变坏。再加上大多数系统拿固定阈值做 retraining，热写节点、热读节点和冷节点被迫共用一套空槽策略，动态 workload 自然很难稳定。

## 核心洞察

这篇论文最值得记住的一点是：learned index 真正需要维持的，不是节点内全局排序，而是一个更弱但足够的性质，即每个 key 仍然待在模型预测的那段小范围里。只要这个性质成立，insert 就不必再为保持顺序去移动一串已有记录，read 也仍然能在很小的范围内完成搜索。

这一步放松带来的收益很直接。插入不再是 shift 或拿锁，而是从 predicted position 开始，在 `pre_ran` 范围内找第一个 `EMPTY_KEY`，用 `CAS` 抢占即可。若这段范围真的满了，再把记录丢进小型 learned bucket。重训练也不必原地重建并让前台等待，旧节点可以继续作为 shadow node 服务请求。

## 设计

LOFT 的整体结构还是标准 learned index：root 里的 `RMI` 先把请求路由到某个 data node，再由节点里的线性模型完成局部定位。区别在于它改写了节点不变量。初始化时，节点用 `PLA` 训练，先按 `epsilon = 1.5` 做扩张，再把 predicted range `pre_ran` 设成 `32`。此后系统只要求 key 留在这个小范围内，不再要求节点内严格有序。

插入因此被彻底改写。LOFT 先算出 predicted position，再在 predicted range 里连续发 `CAS`，谁先把 `EMPTY_KEY` 换成目标 key，谁就拿到槽位；若失败的 `CAS` 返回的是同一个 key，就直接转成 update。整个过程不移动已有记录。若整段范围都满了，记录就转入 expanded learned bucket，默认扩张因子 `beta = 8`。read 先线性扫 predicted range，必要时再查 bucket；delete 采用 soft delete，这样在下一轮 retraining 前不会产生重复 key。

重训练运行在 `RCU` 保护下，分成 copy、retraining、sync 三段。background thread 先把节点标成 retraining，前台写操作把改动过的 key 记进 append-only log，后台线程再复制、排序、重训并生成新的 data node。随后 root 中的指针被原子切到新节点，旧节点退成 shadow node。进入 sync 后，read 和 write 仍可借助 shadow node 读取或补写更新值，所以前台流量本身也在帮系统完成同步。每个节点还会维护少量 metadata，后台线程据此决定 split、expand 或 merge，并动态调整 `epsilon` 与 `pre_ran`：写密集节点增大空槽，读密集节点收紧搜索窗口，冷节点则偏向压缩空间。

## 实验评估

原型用 C++ 实现，跑在一台双路 Linux 服务器上，硬件是两颗 `26` 核 Xeon Gold `6230R` 和 `188 GB` DRAM。对比对象很全，包括 Masstree、DyTIS、ART-OLC、XIndex、FINEdex、ALEX+、LIPP+ 和 SALI。工作负载既有不同读写比例的 YCSB，也有 `5` 个真实数据集，每个都包含 `2` 亿个唯一 `8` 字节 key。

结果很清楚：只要 workload 是论文真正想解决的动态场景，LOFT 基本都处在最前面。混合 YCSB 下，它在所有读写比例里都拿到最高吞吐；读密集场景能扩到 `80` 线程，写密集场景能扩到 `48` 线程。论文在 `80` 线程下给出的平均提升分别是：相对 XIndex `3.1x`、相对 FINEdex `3.4x`、相对 ALEX+ `1.7x`、相对 LIPP+ `14x`、相对 SALI `3.8x`。在一个每 `4` 亿次操作就切换一次访问模式的动态 workload 里，LOFT 的平均吞吐还比 ALEX+ 高 `16%`，而且没有后者那种 blocking retraining 引发的周期性抖动。

尾延迟也支持同样的结论。论文报告 LOFT 最多能把 tail read latency 降低 `90%`，并把自身的典型尾延迟概括为 read 约 `1,000 ns`、insert 约 `5,000 ns`。不过，这不是一篇在任何数据分布上都稳赢的论文。作者自己也展示了，在 Genome、Fb、OSM 这些更难拟合的数据集上，ART-OLC 可以追平甚至超过 LOFT。换句话说，LOFT 的优势很大程度上仍建立在 learned model 至少还能近似分布这一前提之上。

## 创新性与影响

LOFT 的创新点不只是把 `CAS` 和 `RCU` 搬进 learned index。真正新的，是它把不变量改成 error-bounded placement，而不是局部精确顺序。这样一来，`CAS` 插入、overflow bucket、shadow node 重训练和按节点自调参数才能被串成同一套并发设计。论文也明确把自己定位成第一个 lock-free learned index，这个判断大体站得住。

## 局限性

LOFT 通过放松顺序换来了并发性，但也因此放弃了节点内的 binary search，性能高度依赖 `pre_ran` 保持足够小；在 Genome、Fb、OSM 这类难拟合数据集上，ART-OLC 就能追平甚至反超它。它还要额外承担 expansion、bucket、log 和 shadow node 的内存开销，快路径也默认 key 是 `8` 字节、value 是可原子写的 `8` 字节。论文讨论了更长 key 的 fingerprint 办法，却没有真正评测，也没有展开 crash recovery 或故障处理。

## 相关工作

- _Kraska et al. (SIGMOD '18)_ - 这篇工作提出了 learned index 的基本问题设定；LOFT 延续这个方向，但把重点转向动态并发负载下的更新路径。
- _Ding et al. (SIGMOD '20)_ - ALEX 依靠预留空槽和保持局部有序来做 in-place 更新，而 LOFT 则直接放弃严格局部顺序，以换取无锁插入。
- _Tang et al. (PPoPP '20)_ - XIndex 用 delta buffer 和 non-blocking retraining 来处理更新；LOFT 则坚持 in-place 插入，并用 shadow node 做同步而不是做 buffer compaction。

## 我的笔记

<!-- 留空；由人工补充 -->
