---
title: "Ladder: A Convergence-based Structured DAG Blockchain for High Throughput and Low Latency"
oneline: "Ladder 用 lower-chain convergence step 统一排序并行产生的 PoW 区块，在保留有效 fork 的同时简化确认并减轻 balance attack 风险。"
authors:
  - "Dengcheng Hu"
  - "Jianrong Wang"
  - "Xiulong Liu"
  - "Hao Xu"
  - "Xujing Wu"
  - "Muhammad Shahzad"
  - "Guyue Liu"
  - "Keqiu Li"
affiliations:
  - "Tianjin University"
  - "Jd.Com, Inc"
  - "North Carolina State University"
  - "Peking University"
conference: nsdi-2025
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

Ladder 是一种 permissionless block-DAG 设计，它把“并行 PoW 出块”和“确定全局顺序”拆成两条链来处理。upper-chain 继续并行产出交易区块，lower-chain 的 convergence node 负责为每一轮发布权威排序；如果 lower-chain 缺失或出错，再由 HotStuff committee 生成 super block 接管。论文在 80 节点实验中报告，Ladder 相比 Conflux 把中位吞吐从 2823 TPS 提高到 4506 TPS，并把确认延迟从 43 秒降到 34 秒。

## 问题背景

论文抓住了 block-DAG 系统里的一个核心矛盾：允许更多并行区块进入账本，理论上能比单链更好地利用算力；但一旦这些并行区块都需要排序、确认和选主链，系统就会把大量算力花在“解释 DAG”而不是“推进账本”上。像 Conflux、PHANTOM 这样的系统虽然减少了有效工作被丢弃的比例，但每个节点依旧要独立排序竞争区块、维护自己的 DAG 视图，并推断哪条 pivot chain 才应当主导账本。

这会直接拖累确认过程。交易若分布在多个并行区块里，节点就必须通过附加引用、权重累计或递归排序来判断交易是否最终确定。DAG 越宽，这套确认逻辑越复杂；收敛越慢，确认越晚，节点之间对“哪一支更重要”的分歧空间也越大。

第三个问题是 balance attack。只要系统允许多条候选 pivot branch 长时间接近，攻击者就能有意识地维持这种接近平衡的状态，拖延网络收敛。现有方案要么依赖概率性的加权，要么让所有节点都承担更重的排序工作，但两者都没有同时解决排序开销、确认复杂度和抗 balance attack 这三个问题。Ladder 的目标正是把这三个问题绑在一起处理。

## 核心洞察

Ladder 的核心命题是：permissionless DAG 不需要让每个节点都持续、重复地“重新发现”并行区块的全局顺序。PoW 负责决定哪些 upper-chain 区块是合法候选块，而真正的轮次排序只需由一个 convergence node 在每轮明确写出来即可。一旦“收敛结果”变成协议中的显式产物，fork 处理和交易确认都会简单很多。

当然，这种思路只有在两个条件下才成立。第一，convergence node 不能是静态 leader，而必须从 PoW 过程自然生长出来；Ladder 让上一轮标准 upper-chain block 的出块者担任下一轮 lower-chain block 的生成者，因此排序权仍由普通挖矿结果驱动。第二，convergence node 不能成为单点故障；只要 lower-chain 缺失或写入错误，系统就启动 HotStuff-based super block 作为兜底。论文最值得记住的判断其实是：block-DAG 真正昂贵的部分不是并行出块，而是每个节点都重复做排序与收敛。把这件事压缩成“每轮一次、协议显式记录”的动作，性能收益就会非常明显。

## 设计

Ladder 是一个 twin-chain DAG。upper-chain 存放用 PoW 产生的交易区块；在同一轮里，多个合法 upper-chain block 可以同时出现，其中一个会被定为标准块，其余则作为 forked upper-chain block 保留，而不是像传统单链那样直接丢弃。lower-chain 每轮只有一个区块，由“上一轮标准 upper-chain block 的出块者”在无 PoW 的条件下生成。这个 lower-chain block 记录当前轮哪个 upper-chain block 被定为标准块、哪些块被视为 fork，以及这些块的序号信息，从而为所有节点给出统一的账本顺序。

这让账本生成过程从“每个节点各自递归排序 DAG”变成“沿两条链读取显式排序元数据”。标准 upper-chain block 拿到本轮偶数序号，lower-chain block 拿到紧随其后的奇数序号，而 forked upper-chain block 则共享本轮序号并附带下标。节点因此可以直接按 lower-chain 写下来的信息重建总序，而不必重新推理整张 DAG 的局部关系。论文把这一点视为降低排序成本、简化确认的关键。

lower-chain 的生成者不只是记账员。它会在一个等待窗口内收集 upper-chain block，剔除 faulty block，再依据 Hardest Chain Principle 选出标准块，并把其余合法块登记为 fork。这个 Hardest Chain Principle 相比 GHOST 一类的“看子树大小”，改为看累计难度。作者用这种方式减少“两个分支难度完全相等”的概率，从而让 balance attack 更难把系统长期困在两支接近平衡的候选链之间。

真正的安全兜底发生在 lower-chain 出问题时。如果节点发现 lower-chain 引用的 upper-chain block 含有冲突交易，或者在超时时间内迟迟收不到 lower-chain block，却已经看到了合法的 upper-chain block，那么最近若干标准块的出块者会组成 committee，使用 HotStuff 生成 super block。committee leader 通过 VRF 选择，super block 会替代本轮失效的 lower-chain 决策，同时保留 upper-chain 已经完成的工作。这样一来，即便排序路径退化到 BFT，upper-chain 的 PoW 也不必完全停摆。

## 实验评估

论文把 Ladder 与 GHOST、Inclusive、PHANTOM、Conflux 做了对比。实验平台是 80 个节点，每台机器配备 Intel i5-4590 和 8 GB 内存，每个节点约连接 10 个 peer，节点间时延设置为 80-120 ms；区块使用 PoW 难度 18，每块携带 1000 个约 300 字节的支付交易。为了和 Conflux 对齐，Ladder 也采用“后续再观察 6 个 upper-chain block 才确认”的规则。主实验明确是在无对抗者的环境里进行，因此主要反映协议 fast path 的性能。

核心结果很直接：Ladder 的中位吞吐达到 4506 TPS，确认延迟 34 秒；最强基线 Conflux 为 2823 TPS 和 43 秒，也就是论文报告的 59.6% 吞吐提升与 20.9% 延迟下降。进一步的参数扫描也基本支持作者的主张。区块大小从 1000 增加到 1750 笔交易时，Ladder 的吞吐大致维持在 4000-5300 TPS，直到区块大小到 2000 后才因传播开销明显下滑。网络规模从 10 个节点增至 80 个节点时，Ladder 吞吐从 1043 TPS 升到 4506 TPS，而中位确认延迟从 47 秒降到 34 秒，说明额外算力带来的并行出块收益大于额外传播成本。

难度扫描也呈现出一致趋势：PoW 难度越高，所有系统都更慢，但 Ladder 在每个难度点上都领先，并在 difficulty 10 时达到 5314 TPS。论文还做了两个额外扩展实验。在最高 12000 节点的仿真里，Ladder 的吞吐比 Conflux 高 34.2%。在 Alibaba Cloud 的异构 VM 环境中，吞吐从 10 Mbps 时的 2011 TPS 增加到 30 Mbps 时的 4652 TPS，之后瓶颈从网络转向 PoW 计算。最后，committee fallback 被单独测量：300 节点 committee、其中 99 个 Byzantine 节点时，HotStuff 平均耗时 3.25 秒。这个结果说明兜底路径是可行的，但也反过来证明正常的 lower-chain fast path 很重要，因为 fallback 明显比正常传播更贵。

## 创新性与影响

Ladder 的创新点不在于发明了新的密码学原语，而在于重新拆解了 permissionless block-DAG 的系统问题。相较于 Conflux，它把“所有节点都去排序和评估 DAG”改成“每轮由一个 PoW 选出的 convergence node 发布排序决定，失败时再由 committee 修复”。相较于 PHANTOM，它不再依赖整张 DAG 上的递归排序，而是把顺序增量地记录进 lower-chain。相较于 Prism，它继续让 upper-chain 承载交易，让 lower-chain 专门负责收敛信息。

因此，这篇论文更像一个很强的系统设计点。任何想在 permissionless blockchain 里同时获得总序、smart-contract 兼容性和更高并行利用率的设计者，都可以把 Ladder 当作一个清晰范例：不要把“收敛”当作节点本地反复推理出来的副产品，而要把它做成协议里的显式步骤。即便未来系统换掉 PoW 或替换掉 HotStuff，这个分层思路依然有参考价值。

## 局限性

Ladder 最大的局限在于它的安全性是双重概率性的。upper-chain 依赖 PoW 假设，而 lower-chain 的恢复路径又依赖 committee 中恶意节点比例低于 1/3。论文明确承认，这个条件无法在每一轮被绝对保证，只能在“攻击者算力低于 30% 且 committee 足够大”时以高概率成立。作者之所以选择 300 节点 committee，很大程度上就是因为小 committee 会让风险明显升高。

实验也没有真正打到系统最脆弱的那条线。主实验全部在 adversary-free 环境中完成，工作负载几乎都是 payment-style transaction，对比对象也主要是较早的 block-DAG 基线。committee path 虽然被测了延迟，但它是在独立环境里测量，而不是放进持续故障、持续攻击的端到端执行中。因此，论文非常有说服力地展示了 benign case 下的吞吐和确认延迟优势，却没有完整说明在频繁 fallback、针对 convergence timing 的攻击、或更复杂 smart-contract workload 下，系统到底会付出多少代价。

设计本身也带来一条新的权衡。Ladder 删除了全网范围的重复排序，但重新引入了“每轮一个特殊 convergence node”。如果这个节点变慢、诚实但来迟、或者被攻击，系统就必须支付 timeout 再加上 HotStuff 的额外成本。论文中的 3.25 秒 committee 开销说明这条路是可行的，但绝不是免费的，在更不稳定的网络中它可能会更频繁地显现出来。

## 相关工作

- _Li et al. (USENIX ATC '20)_ - `Conflux` 同样保留并行 PoW 区块，但它把 pivot-chain 评估与排序责任留给每个节点自己完成；`Ladder` 则把每轮收敛结果显式写入 lower-chain。
- _Sompolinsky et al. (AFT '21)_ - `PHANTOM GHOSTDAG` 通过递归排序为 block-DAG 给出总序，而 `Ladder` 用 designated convergence node 加 BFT fallback 来替代这套完全分布式的排序逻辑。
- _Bagaria et al. (CCS '19)_ - `Prism` 把投票块与交易块分离以逼近物理极限，而 `Ladder` 仍让 upper-chain 承载交易，只把 fork 的串行化与确认信息放到 lower-chain。
- _Yu et al. (IEEE S&P '20)_ - `OHIE` 用并行链提高吞吐，但每条链仍是线性的，合法区块仍可能被孤块化；`Ladder` 则利用 DAG upper-chain 保留同轮中未成为标准块的有效工作。

## 我的笔记

<!-- 留空；由人工补充 -->
