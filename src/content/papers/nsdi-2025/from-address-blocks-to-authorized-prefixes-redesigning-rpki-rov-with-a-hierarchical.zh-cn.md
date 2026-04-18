---
title: "From Address Blocks to Authorized Prefixes: Redesigning RPKI ROV with a Hierarchical Hashing Scheme for Fast and Memory-Efficient Validation"
oneline: "h2 ROV 把 RPKI 路由源验证从 address block 检查改成前缀粒度授权位图匹配，在不改变判定结果的前提下同时提升速度并降低内存。"
authors:
  - "Zedong Ni"
  - "Yinbo Xu"
  - "Hui Zou"
  - "Yanbiao Li"
  - "Guang Cheng"
  - "Gaogang Xie"
affiliations:
  - "Computer Network Information Center, Chinese Academy of Sciences"
  - "School of Cyber Science & Engineering, Southeast University"
  - "University of Chinese Academy of Sciences"
  - "Purple Mountain Laboratories"
conference: nsdi-2025
category: security-and-privacy
code_url: "https://github.com/FIRLab-CNIC/h-2ROV"
tags:
  - networking
  - security
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文认为，RPKI Route Origin Validation 的主要瓶颈不只是数据结构选型，而是更底层的 address-block 验证模型本身。作者把规则单位从 address block 改成精确的 authorized prefix，并证明这种新模型与标准 AB 模型在判定结果上完全等价，再用分层位图哈希结构把它实现成 `h2 ROV`。在真实 ROA 与 BGP traces 上，这个设计把 IPv4 验证速度提升了 1.7 倍到 9.8 倍，把内存占用降低了 49.3% 到 86.6%，同时还减轻了更新突发时对路由收敛的拖累。

## 问题背景

ROV 是目前唯一被标准化、并且已经能在生产环境落地的 BGP 源起源劫持防御机制，但它的实际部署仍然不充分。论文给出的背景是：虽然已有超过 50% 的 BGP 前缀被 ROA 覆盖，真正主动执行 ROV 的 AS 只有大约 12%，而运维效率正是主要阻力之一。这个顾虑并不是抽象的。每条收到的路由都要与不断增长的 ROA 集合做比对，而一旦出现大规模 updates burst，验证路径会直接拖慢 BGP 收敛。如果验证太贵，运营者就会在路由安全和控制平面响应性之间被迫做交易。

作者认为，现有方案主要是在错误的层次上做优化。基于哈希的方法确实省内存，但为了判断 super-prefix 包含关系，仍然需要多次探测；基于 trie 的方法虽然查得更快，却带来明显更高的内存开销。两类方案都继承了同一个 AB 模型：每条规则写成 `(prefix, maxLength, ASN)`。对一条路由做判定时，路由器必须先找出所有覆盖它的 address blocks，再检查其中是否有规则同时满足前缀长度与 origin ASN。这样一来，随着 RPKI 部署增长，最常见的 valid 情况反而不会变得更便宜；覆盖规则更多时，现有方案的工作量还会继续上升。

## 核心洞察

论文的核心命题是：ROV 不应该围绕 address block 来表达，而应该围绕“哪些精确前缀被授权给哪个 ASN”来表达。如果某个 ROA 授权了 `pfx` 到 `maxLength`，那么路由器可以在概念上把它展开为一组具体的 authorized prefixes，并把规则记成 `(authorized-prefix, ASN)`。这样一来，验证自然被拆成两个问题：这个精确路由前缀是否被这个 ASN 授权；如果没有，它是否至少被某个已授权前缀覆盖。这个拆分会根本改变代价结构，因为 valid routes 现在可以通过一次直接匹配得到答案，而不必在 covering address blocks 之间反复搜索。

第二个洞察是，这种改写不是近似，而是严格等价。论文证明了 AP 模型和传统 AB 模型在来自同一组 ROAs 时，总会给出相同的 `valid`、`invalid` 与 `notFound` 结果。既然正确性不变，系统就可以围绕 exact match 重构 fast path，而不必担心语义漂移。作者的代价分析进一步说明了它的意义：随着 RPKI 部署提升，AP 模型会因为 valid routes 增多而越来越占优；而 AB 模型恰好相反，会因覆盖与有效路由数量增长而承担更重的验证负担。

## 设计

`h2 ROV` 用来自 Hanging ROA 的分层位图编码来实现 AP 模型。每条编码后的规则写成 `(id, bm, ASN)`，其中 `id` 标识某个 hanging level 上的子树，`bm` 标记这个子树内哪些前缀被授权。设计里有两张核心哈希表。Subtree-Origin Table (`SOT`) 以 `(subtree id, ASN)` 为键，负责回答“是否精确匹配”这个问题。对收到的路由 `(rp, ro)`，路由器先算出包含 `rp` 的子树，再算出 `rp` 在该子树里的位位置，然后检查 `SOT[id, ro]` 对应的 bit 是否为 1。若为 1，路由立即被判为 `valid`，查找复杂度是 O(1)。

如果 `SOT` 没命中，`h2 ROV` 就转向只按 subtree id 索引的 SubTree Table (`STT`)。`STT` 存的是同一子树内所有已授权前缀的位图并集，不区分 ASN，因此它回答的是“是否存在某个授权前缀覆盖这条路由”这个问题。算法先检查当前子树内是否存在覆盖关系；如果有，结果就是 `invalid`；如果没有，就沿着祖先子树逐级回溯，直到找到覆盖关系或走到根节点并返回 `notFound`。这就是整篇论文最关键的算法改造：matching 与 covering 被拆到两个不同的结构里，而不是继续在同一个 address-block 搜索过程中交织完成。

作者随后为 IPv4 和 IPv6 分别加了优化。对 IPv4，`h2 ROV` 在 hanging levels 5、10、15、20 上维护 Level Bitmap (`LB`)，标记哪些 subtree roots 已被覆盖。这样可以避开大部分 `STT` 回溯，对前缀长度不超过 24 的路由实现 O(1) 验证；更长的前缀在最坏情况下也只需要 3 次 `STT` 查询加 1 次 `LB` 访问。对 IPv6，则无法承受类似的稠密位图，所以系统引入 cover-flag 位，并在补齐缺失祖先子树后，对祖先路径做二分搜索，把最坏复杂度从 O(|rp|) 降到 O(log |rp|)。不过这条 fast path 仍明显弱于 IPv4。

实现层面还要处理异常宽的 ROAs。如果 `delta = maxLength - |prefix|` 很大，把一个 ROA 直接展开成所有 authorized prefixes 会生成过多规则。因此论文把这类 wide ROAs 单独放进 Wide ROA Trie (`WRT`)，而不是完全展开进主哈希表。完整系统被集成到 FRRouting 和 BIRD 中，做法是在现有 RTR/BGP 路径外增加 encoder 与 parser，并用 `h2 ROV` validator 替换原有的 origin validation 逻辑。

## 实验评估

评估使用了来自 RIPE NCC 的真实 ROAs，以及来自 RIPE RIS collectors 的真实 BGP updates，并与 LPFST (`RTRLib`)、`HT`、`HT+PT`（`BIRD`）和 Patricia（`BGP-SRx`）做对比。在 IPv4 场景下，`h2 ROV` 达到 8.1 到 12.9 million validations per second，相比 LPFST 快 6.8 倍到 9.8 倍，相比 `HT` 快 4.3 倍到 6.2 倍，相比 `HT+PT` 快 1.7 倍到 2.4 倍，相比 Patricia 快 2.2 倍到 2.9 倍。它的 IPv4 内存占用只有 8.5 MB，相比这些 baseline 降低了 49.3% 到 86.6%。这些结果支撑了论文的核心论点：真正改变实际规模区间中渐近行为的，不只是索引实现，而是验证模型本身。

IPv6 的结论则更复杂，论文对此也交代得比较诚实。`h2 ROV` 在 IPv6 上达到 3 到 5.96 million validations per second，能打败 LPFST、`HT` 和 `HT+PT`，但在多数 collectors 上仍略慢于 Patricia。它的 IPv6 内存占用为 12.6 MB，优于 `HT+PT` 和 Patricia，但不如 LPFST 与 `HT`。ROA 的插入与删除都能在 1 微秒以内完成，因此作者认为系统真正的瓶颈仍然是 route validation，而不是 ROA churn。

最有说服力的是系统级结果。把 `h2 ROV` 集成进 FRRouting 与 BIRD 后，在正常工作负载下，它带来的平均 decision-process delay 最低，分别是 FRRouting 的 19.8% 和 BIRD 的 5.9%。在一次回放的 34 万条 update burst 中，它的峰值处理延迟也是所有方案里最小的，相比其他方案在 FRRouting 上降低了 48.8% 到 83.2%，在 BIRD 上降低了 46.9% 到 70.9%。在 AS 拓扑仿真里，更新突发下的收敛时间膨胀被控制在 3.8% 到 8.5%，并把真实拓扑里的 ROV-induced convergence delay 再降低了 30.4% 到 64.7%。这些实验正面回答了论文真正关心的问题：更快的 validator 是否真的能在压力场景下保住收敛表现。

## 创新性与影响

最接近的技术前身是 _Li et al. (INFOCOM '22)_ 提出的 Hanging ROA，它提供了位图编码这种底层 primitive。但这篇论文的创新，在于把这种编码提升成新的验证模型，而不是仅仅用来更紧凑地表示旧模型。相较于 RTRlib、BIRD 的 hash/trie hybrid，以及 BGP-SRx 的 Patricia tree，`h2 ROV` 的关键变化是概念上的：先做 exact authorized-prefix match，再问是否存在 covering prefix。也正因为如此，当作者预期未来互联网会有更多 valid routes 时，它的性能会继续受益，而不是像 AB 模型那样继续恶化。

这项工作的影响更可能是实践层面的，而不只是理论层面的。它给运营者和路由器实现者提供了一个新的判断依据：ROV 不必天然意味着显著的控制平面惩罚。论文还给出了渐进式迁移路径。今天的软件控制平面就能通过本地编码采用 AP 模型，将来如果 RTR 协议能直接传递位图编码规则，额外编码步骤还可以继续消失。如果 ROV 部署确实部分卡在“路由器代价太高”这个顾虑上，这篇论文给出了一个具体、可测量、可集成的反例。

## 局限性

最明显的局限是 IPv6。论文里最强的优化只适用于 IPv4，因为稠密的 level bitmaps 在 IPv4 可行，但在稀疏的 128 位 IPv6 空间里不现实。cover-flag 与二分搜索确实改善了最坏情况，但仍没有完全追平最强的 trie baseline，论文也明确报告 Patricia 在一些 IPv6 设置里仍可能更快。

此外，这个方案也带来了部署与实现复杂度上的新代价。AP 模型需要规则展开、wide ROA 阈值调优、分别维护 `SOT`、`STT`、`LB` 与 `WRT`，ROA 更新逻辑也比传统 validator 更复杂。它的渐进式部署故事是合理的，但还不算彻底完成：只要 bitmap-encoded RTR PDUs 还不存在，路由器就仍然需要本地完成 ROA 编码。最后，证据最强的部分仍是软件路由器实现、回放式实验和仿真。这足以支撑论文的 systems claim，但还不等于已经在多样化硬件路由器上做过长期生产部署。

## 相关工作

- _Li et al. (INFOCOM '22)_ - `Hanging ROA` 提供了 `h2 ROV` 依赖的位图编码 primitive，但它本身并没有把 route validation 从 address blocks 重构为精确 authorized prefixes。
- _Wählisch et al. (CSET '13)_ - `RTRlib` 是论文重点比较的经典 RPKI 验证库；`h2 ROV` 超过它，主要不是因为把同一路线做得更细，而是因为改写了验证模型本身。
- _Li et al. (IMC '23)_ - `ROVista` 关注真实世界的 ROV enforcement 测量，说明路由器效率为何会影响部署，但它研究的是 adoption，而不是验证算法的加速。
- _Qin et al. (NDSS '24)_ - 这项部署研究指出 operators 会把效率视为启用 ROV 的实际障碍，而 `h2 ROV` 则试图用一个具体机制消除这类障碍。

## 我的笔记

<!-- 留空；由人工补充 -->
