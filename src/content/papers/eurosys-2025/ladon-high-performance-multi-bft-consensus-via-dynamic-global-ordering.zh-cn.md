---
title: "Ladon: High-Performance Multi-BFT Consensus via Dynamic Global Ordering"
oneline: "Ladon 用动态单调 rank 取代固定的跨实例槽位，让慢实例不再把整个 Multi-BFT 的全局确认链条拖住。"
authors:
  - "Hanzheng Lyu"
  - "Shaokang Xie"
  - "Jianyu Niu"
  - "Chen Feng"
  - "Yinqian Zhang"
  - "Ivan Beschastnikh"
affiliations:
  - "University of British Columbia (Okanagan campus)"
  - "Southern University of Science and Technology"
  - "University of British Columbia (Vancouver campus)"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3696102"
code_url: "https://github.com/eurosys2024ladon/ladon"
tags:
  - consensus
  - fault-tolerance
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Ladon 瞄准的是 Multi-BFT 最脆弱的一环：多个并行实例已经各自部分提交，但只要有一个实例变慢，传统方案的全局排序就会出现空洞，拖住所有人。它在提议阶段就给每个块分配带证明的单调 rank，再用一个本地可计算的确认阈值去决定哪些块可以全局确认，于是慢实例不再持续卡住快实例。

## 问题背景

Mir、ISS、RCC 这类 Multi-BFT 协议靠并行跑多个 leader-based 实例来摊薄 leader 瓶颈，但最后一步通常仍把 `(instance index, local sequence number)` 固定映射到全局位置。问题正出在这里。只要某个实例里的 leader 变成 straggler，它对应的全局位置就会留下 hole，别的实例即便已经 partial commit，也只能排队等着。论文给了一个直观分析：若 1 个慢实例每 `k` 轮才出 1 个块，剩下 `m-1` 个实例每轮都出块，那么 globally confirmed 的吞吐大约只剩理想情况的 `1/k`。作者用 ISS 做的 WAN 实验也说明了同样的事：16 个实例里出现 1 个和 3 个 straggler 时，峰值吞吐分别下降 89.7% 和 90.2%，延迟最高变成原来的 12 倍和 18 倍。固定排序还会破坏跨实例因果关系，因为慢实例里后提议的块，可能仍拿到更早的全局位置。

## 核心洞察

Ladon 的关键判断是：Multi-BFT 不该靠静态的实例编号和局部序号去决定全局顺序，而该根据系统当下已经被证明的进展来定。具体做法是在块被提议时就附上一个 monotonic rank。这个 rank 必须满足两个不变量：其一，同一个块在所有 honest replica 看来 rank 一致；其二，任何在某个已 partial commit 块之后生成的新块，rank 都必须更大。只要这两个条件成立，replica 就能各自在本地按 `(rank, instance index)` 排序，而不需要再跑一轮额外的全局共识。这样一来，straggler 实例不再因为占了逻辑槽位就拖住整个全局日志，后生成的块也不能借着固定映射插到前面去。

## 设计

在每次 leader 准备提议新块前，它会先从 replica 收集 `2f+1` 份带证明的 rank 报告，每份都表示该 replica 当前已知的最高 rank。leader 取其中最大的已认证 rank，加一后作为新块的 rank；若超过当前 epoch 的 `maxRank`，就截断在该上界。以 Ladon-PBFT 为例，leader 会把这个 rank 和对应 proof 放进 pre-prepare；backup 除了检查普通 PBFT 条件，还要检查这些 rank 证据是否自洽。块 commit 后，replica 会把自己当前最高的已认证 rank 反馈给下一轮，于是 rank 收集被塞进 commit 尾部，而不是额外插入一整轮通信。

全局确认算法则完全是本地、确定性的。每个 replica 先看每个实例当前最后一个已经形成连续 partial confirmation 的块，从这些块里找出 `(rank, instance index)` 最小的那个，据此算出一个 confirmation bar。所有还没 global confirm、但排序位置低于这个 bar 的块，都可以立即确认，因为未来再产生的块不可能拥有更早的位置。论文还补了两个关键工程化细节：epoch 切换靠 checkpoint 保证安全；优化版 `Ladon-opt` 用 aggregate signature 压缩 `2f+1` 份 rank 报告，把 pre-prepare 阶段的通信复杂度从 `O(n^2)` 拉回 `O(n)`。

## 实验评估

实验部署在 AWS `c5a.2xlarge` 上，规模为 8 到 128 个 replica，既测 LAN，也测分布在法国、美国、澳大利亚和东京四地的 WAN。事务大小 500B，batch size 4096，所有协议统一采用相同的总 block rate 限制。基线方面，ISS、RCC、Mir、DQBFT 都用统一配置去比。

没有 straggler 时，Ladon 的额外开销很小：在 WAN、128 个 replica 下，它的吞吐与 ISS、RCC 只差大约 1%，不过延迟比两者高 22.6% 和 18.5%。真正有区分度的是有 straggler 的场景。WAN、128 个 replica、1 个 honest straggler 时，Ladon 的吞吐分别是 ISS、RCC、Mir 的 9.1 倍、9.4 倍和 9.6 倍，而且延迟最低。若和自己无 straggler 时相比，Ladon 吞吐只下降 9.3%；ISS、RCC、Mir 则分别掉了 89.9%、90.1% 和 84.1%。在 16 个 replica 的 WAN 里，把 Byzantine straggler 从 1 个加到 5 个，Ladon 仍能保留与同数量 honest straggler 场景相比约 90% 的吞吐；5 个 Byzantine straggler 时，延迟只比 honest straggler 多 12.5%。论文还定义了 inter-block causal strength 指标，在所有测试的 straggler 数量和 proposal rate 下，Ladon 都保持 `1.0`。

## 创新性与影响

这篇论文的新意，不是简单地把多个 BFT 实例并行化，而是抓准了 Multi-BFT 真正卡脖子的地方其实是固定的跨实例合并规则。Ladon 用带证明的 monotonic rank 加上一个确定性的 confirmation bar，把这个合并规则整个换掉了。这不是参数调优，而是协议层的新机制。

## 局限性

Ladon 增强的是 inter-block causality，不是完整的 client-side fairness。Byzantine leader 仍然可以在 timeout 触发前拖延提议，优化版协议也更复杂：需要额外的 rank 证明、多把签名私钥，以及一个要按部署环境调参的 `K`。

实验层面，它证明了协议机制有效，但覆盖面还是偏窄。大多数结果来自单一 AWS 机型、固定 total block rate、固定 epoch 长度 64 的合成负载。论文也明确展示了一个代价：在没有 straggler 时，Ladon 的延迟略高于 ISS 和 RCC。更贴近真实应用的执行成本和长期运维复杂度，文中没有展开。

## 相关工作

- _Stathakopoulou et al. (JSys '22)_ - Mir-BFT 让多个 leader 并行出块，但最终还是靠固定的跨实例合并顺序。
- _Stathakopoulou et al. (EuroSys '22)_ - ISS 允许实例通过 `⊥` 独立前进，可全局确认阶段仍会被 hole 卡住。
- _Gupta et al. (ICDE '21)_ - RCC 的重点是并发共识和 wait-free 处理落后 leader，而 Ladon 直接改写了合并规则。
- _Arun and Ravindran (PVLDB '22)_ - DQBFT 用一个专门的 ordering instance 给并行实例输出排队，Ladon 则避免再造这个中心化瓶颈。

## 我的笔记

<!-- 留空；由人工补充 -->
