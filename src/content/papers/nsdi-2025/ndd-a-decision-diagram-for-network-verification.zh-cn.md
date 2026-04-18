---
title: "NDD: A Decision Diagram for Network Verification"
oneline: "NDD 把 BDD 式 network verification 提升到 field 粒度，按字段计算 atoms，并消除了最严重的 atom explosion 瓶颈。"
authors:
  - "Zechun Li"
  - "Peng Zhang"
  - "Yichi Zhang"
  - "Hongkun Yang"
affiliations:
  - "Xi'an Jiaotong University"
  - "Google"
conference: nsdi-2025
category: network-verification-and-synthesis
code_url: "https://github.com/XJTU-NetVerify/NDD"
project_url: "https://xjtu-netverify.github.io/papers/2025-ndd-a-decision-diagram-for-network-verification"
tags:
  - networking
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

NDD 用一个按 field 分支、并在边上挂 per-field BDD 的两层 decision diagram，取代了面向整包头、按 bit 递归的 BDD 推理。它还把 atoms 的计算与增量更新收进库内部，使现有验证器不再为全局 atom 计算支付最坏的内存与递归代价。对五个基于 BDD 的网络验证器，论文在 field locality 明显的负载上报告了大约两个数量级的时间和内存改进。

## 问题背景

这篇论文抓住的是一个表示层面的错位：网络规则天然以 field 为单位书写，但 BDD 式验证器把它们压平成一个统一的 bit vector。设备实际匹配的是 dstIP、srcPort、community、链路失效位这类字段，而且大多数规则只碰其中少数几个；BDD 却看不到这种 field 语义，因此两个在某些字段上共享大量结构、只在别的字段上不同的 packet sets，仍会被编码成不同节点。

首先受伤的是内存。当验证器在整个网络状态上计算 equivalence classes，也就是 atoms 时，不同字段之间会发生组合式膨胀，形成更多全局 atoms。论文展示了这种增长会在 multi-layer networks 上直接冲垮 BDD node table。其次受伤的是时间。BDD 的逻辑运算一次只前进一位；如果两个操作数从不同变量开始，库还要花额外递归去对齐变量位置。对宽包头和路由属性来说，这就把验证器的内层循环拖得很慢。

更麻烦的是，BDD 库并不原生支持网络验证真正关心的事情，比如 atoms 的计算、变更后的增量更新，以及 packet transformers 的处理。于是每个验证器都要在 BDD 之上再造一套 atom-management 逻辑，同时继续承受同样的可扩展性问题。

## 核心洞察

论文的核心命题是：只要网络语义本身具有 field locality，验证器就应该把这种结构一直保留到符号表示层。若 reduction 和 logical operations 都被限制在同一 field 内部的 BDD 上，那么普通 BDD 无法消除的 partial redundancy 就能被消掉，而且一次递归可以跨过整个 field，而不是逐 bit 地往下走。

NDD 对应的做法，是在 per-field BDD 之上再包一层 decision diagram。外层按 field 分支，边上的标签是描述该 field 允许值的 BDD。随后，atoms 也不再按整个网络状态统一计算，而是按 field 分别计算。这样既保留了 BDD 在单个字段内部处理任意 bit pattern 的紧凑性，又避免了把所有字段硬塞进一个单体 bit-level structure 后出现的 cross-product explosion。

## 设计

NDD 是一个 rooted DAG，包含 `true` 与 `false` 两个 terminal 节点，以及按 field 而不是按单个 bit 编号的 non-terminal 节点。每个节点的出边在该 field 上两两互斥、合起来又覆盖全部取值；每条边携带一个 BDD predicate，并指向后继节点。它的 reduced ordered 形式在普通 ROBDD 的基础上再加一条规则：同一个 NDD 节点里，不允许两条边指向同一个 successor。这样一来，那些只在局部谓词上分叉、下游又重新汇合的结构就能被合并。论文还证明了在固定 field order 下 NDD 仍然是 canonical 的，因此相等性判断和 memoization 依旧成立。

核心算子是 `apply`，它推广了 BDD 里的 `and`、`or` 和 `diff`。不同于只在 low/high 分支上递归，NDD 会枚举所有标签有交集的边对，递归组合它们的 successors，再把终点相同的边通过对标签做 OR 合并起来。存在量词 `exist` 也类似：它通过把某个 field 上的所有出边 OR 起来来消去该 field。作者认为这种设计在实践里是可行的，因为经过 reduction 后，大多数 NDD 节点的出边数都不大。

第二个关键机制是 atomization。`atomize` 会按 field 收集所有边标签，为每个 field 单独计算 atoms，再把每条边上的 BDD 标签替换成它所覆盖的 atom 集合。完成 atomization 之后，很多验证器操作就从对整包头 BDD 的布尔运算，变成了对 field-local atoms 的集合交并。`update` 则负责增量变化：如果新谓词 `δ` 已知满足 `δ ⇒ a`，其中 `a` 是已有的 atomized NDD，那么库只需在可达路径上拆分那些真正与 `δ` 相交的 atoms，而不用全量重算。

实现上，作者没有把事情做得花哨。NDD 库是在 JDD 之上用大约 2K 行 Java 实现的，又加了一个很小的 JavaBDD factory，让 Batfish 这类工具也能切换。API 刻意保留了 `createVar`、`apply`、`not`、`exist` 这些 BDD 风格接口，只额外增加 `atomize` 与 `update` 两个 verifier-specific API。内部则使用按 field 划分的 hash-based unique table、operation cache，并显式删掉指向 `false` terminal 的边，因为这些边往往携带最重的 BDD 标签和最多的 atoms。

## 实验评估

评估覆盖了三类工作负载：带 packet transformers 的 virtualized datacenter networks、真实 WAN 与 campus networks，以及 fat-tree control-plane simulations。最有说服力的结果出现在 field 丰富的负载上。对基于 VXLAN 的 datacenter snapshots，APKeep(NDD) 是唯一能跑完从 6 个 leaf 到 500 个 leaf 全部七组数据的版本；APKeep(BDD) 与 KatraR(BDD) 要么在 24 小时后超时，要么耗尽 256 GB 以上内存。即便在最小的 6-leaf 数据集上，内存也从 4.36 GB 降到 0.01 GB，atom 数从 28,077 降到 112。

packet transformer 的实验给出同样结论。向 Purdue 注入 NAT 和 twice-NAT 规则后，APKeep(NDD) 在只有 4 条 NAT 规则时就已比 BDD 快约 10 倍，在 40 条时快约 100 倍。BDD 版本在 80 条 NAT 规则后就会 OOM，而 NDD 版本一直可以跑到 2000 条。控制平面部分，SRE 在 500-node fat tree、单链路失效场景下使用 BDD 会因为 BDD table overflow 中止，而改用 NDD 后可以完成验证。

论文对收益变小的情形也很坦诚。对 Stanford 和 Internet2，这些谓词大多实际只落在一个 field 上，因此 NDD 与 BDD 只是相当或略快。Batfish 的提升也比较有限，原因相同。这种结果反而增强了可信度：NDD 的优势恰好出现在 field locality 强的地方，而这正是论文一开始给出的前提。

## 创新性与影响

这篇论文的贡献不是为某一个任务再造一个专用 verifier，而是给整类 verifier 换了一层新的 symbolic substrate。作者把 AP Verifier、APT、APKeep、SRE 和 Batfish 都迁到了 NDD 上，代码改动相对很小，而且更多是在删掉原本自定义的 atom-handling 逻辑，而不是加入新的 verifier-specific machinery。这是 NDD 作为 drop-in replacement 最有说服力的证据。

和 MDD、IDD、CDD 这类 field-level structures 相比，NDD 并没有抛弃 BDD，而是把 BDD 保留在每个 field 内部，避免退化成“每个值一条边”或“大量区间/约束”那样的表示。真正的新意就在于 field-level structure 与 per-field BDD compactness 的组合。我认为它最可能影响的，是那些仍想保留 canonical symbolic reasoning、但已经承受不起 whole-state BDD 成本的后续网络验证工作。

## 局限性

NDD 的前提是 field locality。论文明确展示过：如果把越来越多 ACL 规则改写成同时匹配全部五个字段，那么 NDD 的优势会消失，BDD 甚至可能更好。因此，NDD 不是对所有 bit-level symbolic reasoning 的通用替代品，而是一种针对典型网络策略结构定制的表示。

论文也留下了一些泛化问题。对 packet headers 和 route attributes 来说，field 划分很自然；但对其他类型的 symbolic state，系统仍需要依赖启发式分组。控制平面的收益在 SRE 上很明显，在 Batfish 上则弱得多，这说明回报不仅取决于库本身，也取决于验证器的状态能否自然分解成多个 fields。作者还提出 NDD 可能帮助网络验证之外的问题，但这一点目前仍属于探索性的判断。

## 相关工作

- _Yang and Lam (ICNP '13)_ - `AP Verifier` 用基于 BDD 的 atomic predicates 做网络可达性验证，而 `NDD` 把 atoms 的计算内化到按字段划分的表示里，避开了同样的 whole-header atom explosion。
- _Zhang et al. (NSDI '20)_ - `APKeep` 在 BDD 之上专门工程化了增量 atom 维护，而 `NDD` 通过 `atomize` 和 `update` 把这部分复杂性下沉回库内部。
- _Beckett and Gupta (NSDI '22)_ - `Katra` 用 partial equivalence classes 缓解 multi-layer verification 的膨胀，而 `NDD` 则通过改变底层 symbolic representation 来攻击同一个扩展性痛点。
- _Zhang et al. (SIGCOMM '22)_ - `SRE` 使用 BDD 联合编码 failures 与 packet state 做控制平面推理，而这篇论文说明同类 verifier 在采用 field-partitioned decision diagram 后还能继续扩大规模。

## 我的笔记

<!-- 留空；由人工补充 -->
