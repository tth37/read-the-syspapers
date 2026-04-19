---
title: "Collaborative Text Editing with Eg-walker: Better, Faster, Smaller"
oneline: "Eg-walker 把编辑历史存成事件 DAG，只在并发回放时临时构造 CRDT 状态，把常驻内存压到现有 CRDT 的十分之一量级，并把长分支合并从小时级降到毫秒级。"
authors:
  - "Joseph Gentle"
  - "Martin Kleppmann"
affiliations:
  - "Independent"
  - "University of Cambridge"
conference: eurosys-2025
category: reliability-and-formal-methods
doi_url: "https://doi.org/10.1145/3689031.3696076"
code_url: "https://github.com/josephg/diamond-types"
tags:
  - pl-systems
  - formal-methods
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Eg-walker 是一种混合式协作文本编辑算法。它继续把持久层做成 OT 风格的索引式历史，但只在并发回放时临时展开 CRDT 状态；因此既保住了 peer-to-peer 收敛语义，又把两条离线分支的合并压到 `O((k+m) log(k+m))`，同时摆脱了现有文本 CRDT 常驻的逐字符元数据负担。

## 问题背景

这篇论文抓住的是协作编辑里最顽固的那道分界线。Operational Transformation 在分歧很短时很好用，可一旦两边离线各写了很多内容，或者把文档当成 Git 那样分支再合并，合并代价至少会随双方操作数呈二次增长。论文里的异步轨迹 A2 用 OT 基线要 61.1 分钟才能合完，已经远远超出可接受范围。

CRDT 则反过来，把并发定位问题从索引空间搬到字符 ID 空间，因此天然适合 peer-to-peer 复制。但它要求字符 ID、墓碑和排序元数据长期陪伴文档，打开文档时要读进来，编辑时要常驻内存。论文指出，即便是当前最好的文本 CRDT，在只做查看和编辑时，内存开销也仍然超过 OT 的 10 倍。真正的问题因此变成：能不能既拿到 CRDT 的长分支合并能力，又不把 CRDT 的常驻成本带进日常编辑。

## 核心洞察

Eg-walker 的关键判断是：逐字符的 CRDT 元数据只在解决并发时才需要，不该陪着文档长期存在。真正需要持久化的，可以只是两样东西：保存原始索引式插入与删除操作的事件图，以及当前纯文本内容。历史是顺序的，就直接追加或回放；历史一旦并发，再临时重建足够表达并发关系的内部结构去重放后缀。

这件事之所以成立，是因为算法同时维护 prepare version 和 effect version。前者表示下一个事件原本应被解释的上下文，后者表示当前已经重基完成的版本。effect version 只向前推进，而 prepare version 可以在 DAG 里前后移动，于是 Eg-walker 既能按事件生成时的原始语义解释索引，又能输出一条已经线性化的执行序列。

## 设计

底层数据模型是一张事件 DAG。每个事件保存一次插入或删除、一个唯一事件 ID，以及其父事件集合。Eg-walker 会先做拓扑排序，并尽量让同一分支连续出现，避免无谓的分支来回切换。

临时内部状态是一条带墓碑的字符记录序列。每条记录都带有插入它的事件 ID、prepare-state 标记 `s_p`、effect-state 标记 `s_e`，以及并发插入排序所需的额外字段。`s_p` 可以是 `NotInsertedYet`、`Ins` 或 `Del_n`；`s_e` 只有 `Ins` 和 `Del`。回放时只有三个动作：`apply(e)` 在 prepare version 里解释事件并输出变换后操作，`retreat(e)` 把 prepare version 往回退，`advance(e)` 再把事件补回 prepare version。也就是说，它不再像 OT 那样做成对 transform，而是把问题改写成在一份短暂存在的内部状态上行走。

为了让索引映射保持高效，作者用了两棵平衡树。第一棵是 order-statistic B-tree，用来把输入索引映射到当前可见记录，再从记录回推出 effect version 里的输出索引，复杂度都是 `O(log n)`；第二棵 B-tree 把事件 ID 映射到对应记录，使 `retreat` 和 `advance` 不必线性扫描。

另一个决定性能的关键概念是 critical version。只要某个 frontier 能把历史切成「之前所有事件」和「之后所有事件」两块，那么之前那部分就不会再影响之后事件的变换结果。Eg-walker 到达这样的点后，可以把整份内部状态清空，只保留事件图和当前文本；若未来又出现并发，只需从最近相关的 critical version 之后重放后缀，并从一个代表更早未知文本的 placeholder 开始。两条长度分别为 `k` 和 `m` 的离线分支因此能在 `O((k+m) log(k+m))` 内合并，而不是落回 OT 近似 `O(km)` 的形态。

## 实验评估

评测使用了 7 条真实编辑轨迹：3 条顺序轨迹、2 条带人工延迟的双人并发轨迹，以及 2 条从 Git 历史重建的异步轨迹。比较对象包括 Automerge、Yjs、一个 TTF 风格的 OT 基线，以及作者自己实现、并与 Eg-walker 共享大量 Rust 代码的 reference CRDT。

最醒目的结果是异步合并。轨迹 A2 上，Eg-walker 只要 23.5 ms，而 OT 基线要 61.1 分钟；A1 上则是 56.1 ms 对 6.3 秒。这说明它改变的是长分支合并的复杂度形态，不只是常数项。

顺序轨迹上，critical-version 清理让大部分内部状态工作可以直接跳过，于是 Eg-walker 合并完整历史只要 1.8 ms、2.7 ms、3.6 ms；reference CRDT 分别要 17.9 ms、19.1 ms、26.9 ms，Automerge 和 Yjs 更慢。加载时间也很亮眼：由于可以直接缓存最终纯文本，Eg-walker 的 cached load 只有 0.01-0.12 ms，而被测试的 CRDT 基本要在加载时重建元数据。论文还指出，它在回放时的峰值内存与最好的 CRDT 大致同量级，但 steady state 会低 1 到 2 个数量级，因为常驻的只剩文档文本。

## 创新性与影响

Eg-walker 的新意，在于它重画了抽象边界。OT 保留索引式操作，却在长分歧历史上爆炸；文本 CRDT 让并发处理变便宜，却把元数据永久留在系统里。Eg-walker 继续把外部模型做成索引式操作，但把 CRDT 降成一个只在回放并发后缀时才存在的引擎，再通过 critical version 尽快把它清掉。这对 local-first 软件、peer-to-peer 协作工具，以及寻找实用文本 datatype 的 CRDT 研究都很重要。

## 局限性

这套设计假设 reliable broadcast、父事件最终可达，以及副本是 non-Byzantine 的；论文研究对象也只覆盖 plain text。任意 DAG 的最坏回放复杂度仍是 `O(n^2 log n)`，而且作者承认在极高并发轨迹上，拓扑遍历顺序选差了会让 A2 慢到 8 倍。评测基准虽然已经明显好于同类工作，但仍只有 7 条轨迹，其中实时并发轨迹只有两条、且都是双人场景，也没有覆盖网络传输、UI 延迟或 richer document types 的端到端产品表现。

## 相关工作

- _Nichols et al. (UIST '95)_ - Jupiter 代表了经典 OT 路线：继续使用索引式操作，但在长分支上要付出成对变换成本；Eg-walker 通过短暂内部状态回放，避开了这种爆炸。
- _Nicolaescu et al. (GROUP '16)_ - YATA 一类 peer-to-peer shared editing 方法要求逐字符 ID 与排序元数据长期陪伴文档；Eg-walker 只在解决并发时短暂借用这类排序思想。
- _Attiya et al. (PODC '16)_ - strong list specification 给出了协作文本编辑应满足的正确性目标，而 Eg-walker 把自己的 replay 语义对齐到这个目标上，同时重做了性能权衡。
- _Roh et al. (JPDC '11)_ - replicated abstract data types 让文本收敛依赖持久存在的标识符状态；Eg-walker 则把这部分重状态限制在短暂的、后缀局部的内部结构里。

## 我的笔记

<!-- 留空；由人工补充 -->
