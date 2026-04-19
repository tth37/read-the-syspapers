---
title: "Jupiter: Pushing Speed and Scalability Limitations for Subgraph Matching on Multi-GPUs"
oneline: "Jupiter 把跨 GPU 拉邻接表改成把搜索上下文送到数据所在 GPU 继续执行，再批量聚合小消息，让分布式子图匹配真正扩到多节点。"
authors:
  - "Zhiheng Lin"
  - "Ke Meng"
  - "Changjie Xu"
  - "Weichen Cao"
  - "Guangming Tan"
affiliations:
  - "SKLP, Institute of Computing Technology, CAS, University of Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
conference: eurosys-2025
category: graph-and-data-systems
doi_url: "https://doi.org/10.1145/3689031.3717491"
code_url: "https://github.com/AnySparse/Jupiter"
tags:
  - graph-processing
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Jupiter 的做法很直接：既然远端邻接表又大又要反复拉，不如把当前子图匹配任务暂停下来，连同候选集一起打包，送到真正持有那段图拓扑的 GPU 上继续算。再配合面向超小消息的批量聚合，它把通信量最多压低 105x，在相同显存预算下把可处理图规模推到先前系统的大约 10 倍，并在 4×A100 上对已有分布式 GPU 方案拿到最高 120x 加速。

## 问题背景

分布式 GPM 最难受的地方，在于真正有用的远端结果很小，可为了得到它，系统却常常得先搬整段邻接表。一个 GPU 手里拿着 partial embedding，想判断它能否继续扩成目标模式，就得查看某个远端顶点的邻居；但最后真正满足约束的往往只是其中极少一部分。论文把这种「为了一点点有效交集，先搬一大段邻接表」称作 communication amplification，并测到最高 109.1x。

现有系统只是把账单换个位置结。G2 Miner 这类 replication 方案把整图复制到每张 GPU，上手最痛快，但可处理规模直接被显存封顶。VSGM、G2-AIMD 走的是 host-memory 路线，用重叠的 k-hop subgraph 把 CPU 内存当扩展显存，代价是额外复制、重预处理和 CPU 介入。纯 data-fetching 也不轻松，论文给的例子是：一个 14 GB 的图，搜索过程中可能累计产生 8 TB 通信，因为相同的远端邻接表会被一遍遍拉回来。更糟的是，如果只发送必要状态，消息又会碎得厉害；在 4-clique 实验里，93% 的消息都不到 200 字节。

## 核心洞察

Jupiter 的关键判断是：跨 GPU 迁移的不该是邻接表，而该是搜索上下文。因为候选集会在一轮轮 set operation 后持续收缩，所以一个暂停后的子任务，通常远小于它正准备去读取的远端拓扑。

接受这一点以后，delegation 就成立了。系统不把 `N(u)` 拉到当前 GPU，而是把当前子任务序列化后送到持有 `N(u)` 的 GPU，让它在本地继续执行，再把更小的新 context 或最终答案送回来。搜索语义没有变，真正改变的是跨设备流动的对象。

## 设计

Jupiter 把整个 GPU 集群抽象成一块 distributed shared memory，底层用 NVSHMEM 实现。系统分成三个角色：`Executor` 负责执行和单 GPU 引擎接近的 set-centric 匹配逻辑；`Delegator` 在下一步需要远端拓扑时决定任务该往哪张 GPU 迁移；`ContextManager` 提供 DSM 层面的分配、读写和序列化能力。

被迁移的工作单元是一个 `<S, P, op>` context。`S` 和 `P` 是当前待匹配边两端的候选集，`op` 是要做的 set operation。远端 GPU 恢复这个 context 之后，就能在本地枚举 `S`、读取对应的 `N(v)`，再计算 `N(v) op P`，不必先把拓扑搬过来。若 `S = P`，Jupiter 只写一个引用标记，避免把相同集合物化两次。Delegator 还会按图分区把一个 context 拆成多个子 context，让每张 GPU 只接手自己那部分顶点；后续再遇到远端分区时，这个过程还能继续递归。

第二个关键点是小消息聚合。Jupiter 不会把每个 context 一生成就立刻发走，而是先写入每张 GPU 的共享缓冲区，再凑成足够大的批量消息统一发送。缓冲区按类似 CSR 的方式组织，并通过 lock queue 处理并发写入。系统再用 `LUT(s, t)` 按消息大小和并发度挑选更合适的通信配置：intra-node 用类似 UGache 的 core dedication 避免 NVLink 冲突，inter-node 则先在节点内归并，再做跨节点转发。实现上，图分区和 workload context 都放在 DSM 里，采用 1-D partition，并可选配一层静态 graph cache 来减少重复远端读取。

## 实验评估

论文的实验设计基本撑得住中心论点。单机部分使用最多 8 张 A100-80GB，通过 NVLink 互连；多机部分使用带 V100-32GB 的节点，节点内走 NVLink，节点间走 100 Gb/s InfiniBand。数据集从 500 MB 的 CitePatents 一直到 361 GB 的 UK-2014，比较对象包括 G2 Miner、VSGM、G2-AIMD、PBE，以及作者自己的 data-fetching 基线 `Jupiter-DF`。论文还明确说明这些系统共享同一 matching order 和 symmetry breaking 规则，因此对比算是有约束的。

结果与机制是对得上的。单 GPU 上，Jupiter 还能保持 G2 Miner 84%-98% 的性能，说明分布式支持不是白来的，但代价也还算克制。到了 4×A100，Jupiter 相对 VSGM 平均加速 21.5x、相对 G2-AIMD 平均加速 12.2x，最高达到 120x。更关键的是规模边界被真正推开了：面对 325 GB 的 ClueWeb12 和 361 GB 的 UK-2014，其他方案不是超时就是 OOM，而 Jupiter 仍然能跑完，所以论文所说「同样内存资源下可处理约 10 倍更大的图」并不夸张。

优化分析也相当扎实。delegation 相对 `Jupiter-DF` 最多把通信量降到 1/105，平均下降 14x；通信时间占比从 33%-42% 压到 5% 以下，而 context switch 的额外开销最高只有 3.1%。单节点内带宽能跑到 227 GB/s，约为 NVLink 理论峰值的 75.7%；跨节点则到 10 GB/s，约为 InfiniBand 理论峰值的 80%。GPU 利用率长期保持在 95% 以上，扩展性则做到单节点 8 GPU 为 87.5%-92.5%，多节点 4×V100 集群为 57.5%-75%。真正的边界也很清楚：如果图能完整复制到每张 GPU 上，完全避免通信的 G2 Miner 仍可能更快。

## 创新性与影响

Jupiter 的新意不在算法层，而在执行模型层。过去的 partitioned graph mining，大体就是复制拓扑、从主机流式换页、或者按需拉邻接表；Jupiter 则把搜索本身变成可迁移对象，让 context 动、拓扑不动，再用 DSM 和 batching 把它做成 GPU 上可落地的机制。更重要的是，delegation 还能和 Subgraph Morphing、IEP 一起工作，这说明它不像某个特定 pattern 的技巧，更像一层可复用的运行时基底。

## 局限性

Jupiter 的优势主要出现在它瞄准的场景里：大图、分区、通信主导。若整图能轻松复制到每张 GPU，上下文迁移这套机制本身就是额外成本，replication 路线自然可能更快。论文也承认，遇到度数很低的顶点时，context switch 的收益未必明显。

实现层面它也明显依赖 NVIDIA 生态。NVSHMEM、NVLink/NVSwitch、InfiniBand 以及经验型带宽配置，都让这套系统更像围绕特定硬件栈精调过的方案，而不是能立刻平移到任意加速器集群的通用系统。多节点扩展虽然不错，但和理想线性仍有差距；论文还明确展示了 inter-node 并发过高时，CPU proxy threads 反而会把性能拖下去。另一方面，论文也没有研究动态图更新、在线 repartition，或其他加速器生态上的可移植性。

## 相关工作

- _Chen and Arvind (OSDI '22)_ - G2 Miner 通过把整图复制到每张 GPU 上来换取零通信；Jupiter 则坚持非重叠分区，只在需要时迁移紧凑的搜索 context。
- _Jiang et al. (SC '22)_ - VSGM 依赖 CPU 管理的重叠 k-hop view 扩展 GPU 内存；Jupiter 避免这类重复子图，并把通信尽量留在 GPU 侧 DSM 内完成。
- _Yuan et al. (ICDE '24)_ - G2-AIMD 改进了 VSGM 的调度策略，但仍然沿用 host-memory streaming 这条大路线，而 Jupiter 试图整体替换这一路线。
- _Chen and Qian (ASPLOS '23)_ - Khuzdul 在分布式 CPU 图分区上按需拉缺失邻接数据；Jupiter 的出发点相反，是把暂停后的搜索送到数据所在位置继续执行。

## 我的笔记

<!-- 留空；由人工补充 -->
