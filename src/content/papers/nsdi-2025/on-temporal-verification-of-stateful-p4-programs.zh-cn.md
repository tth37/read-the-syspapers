---
title: "On Temporal Verification of Stateful P4 Programs"
oneline: "p4tv 把 P4 交换机建模成无限包处理循环，用 P4LTL 描述跨包性质，再用保留寄存器历史的 Büchi transaction 做检查。"
authors:
  - "Delong Zhang"
  - "Chong Ye"
  - "Fei He"
affiliations:
  - "School of Software, BNRist, Tsinghua University, Beijing 100084, China"
  - "Key Laboratory for Information System Security, MoE, China"
conference: nsdi-2025
project_url: "https://thufv.github.io/research/p4tv"
tags:
  - networking
  - smartnic
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`p4tv` 在 packet-processing 粒度上验证 stateful P4 程序的时序性质。它让寄存器在多个包之间持续保存，用 `P4LTL` 表达跨包性质，再用一种只在单个包处理结束时推进时序自动机的 `Büchi transaction` 来检查反式。在 9 个 benchmark 和 19 个任务上，它验证了 14 个，并把其余任务定位成真实违规。

## 问题背景

论文指出，stateful P4 的真实语义与现有 verifier 的建模方式存在根本错位。很多 P4 程序依赖寄存器和本地状态来做 failover、队列控制、NDN 式匹配和协议逻辑，但现有工具大多按单个包推理，并在每次包处理开始前把寄存器设成 nondeterministic。这样做虽然降低了求解难度，却把“状态为何有意义”这一点直接抹掉了。

P4NIS 的例子很典型。若 verifier 允许任意初始寄存器值，它就可能报告端口超出合法范围；但在程序预期的初始化和更新逻辑下，这个寄存器实际上会一直保持有界。对 liveness 性质更是如此，比如“某类包持续到达时，每个合法输出端口都应被无限次使用”，这类性质根本无法自然降成单包断言。所以真正的问题是：如何在一个框架里同时表达不受限制的包环境、跨包持久化的寄存器状态，以及可选的控制平面假设。

## 核心洞察

核心洞察是把时间粒度改成“大步语义”：一个时间步表示“一个包处理完成”，而不是“执行了一条语句”。只有这样，时序算子描述的才是网络行为真正关心的观测点，寄存器跨包保存也才会进入语义本身。

这带来两个直接设计。第一，把交换机建模成一个无限循环，每轮接收一个 nondeterministic 包并保留寄存器状态。第二，不再使用标准的 Büchi program product，因为它会在每条语句上推进时序自动机，生成大量与 packet-level 性质无关的 trace。论文提出的 `Büchi transaction` 只在一次包处理事务返回时推进时序自动机。

## 设计

`p4tv` 的第一层是环境模型。寄存器声明在无限循环之外，因此会跨包保持；每轮开始时，包字段是 nondeterministic，metadata 按 P4-16 初始化；若没有额外假设，table application 被建模成 nondeterministic 的 action choice。若某个性质只在特定规则集下有意义，用户可以通过 CPI 去约束 table hit、key 和 action 的关系。

第二层是 `P4LTL`。它在 LTL 上加入了 P4 感知的 term 和 predicate，可以引用 headers、metadata、registers、table keys、action parameters，以及 ingress 起点的 `old(...)` 值；predicate 则描述 `drop`、`fwd(port)`、表命中和 action 调用等事件。因为语义落在包边界上，所以 `next`、`always`、`eventually` 和 `until` 都是在描述包序列，而不是语句轨迹。

第三层是验证流水线。工具先把 P4 翻译到 Boogie，再用 ghost variable 跟踪 `P4LTL` 观测量；之后对目标性质取反，转换成 Büchi automaton，并与 P4 控制流自动机构造 `Büchi transaction`。接着它用 Ultimate Automizer 搜索 fair 且 feasible 的 trace；若找到就给出真实 counterexample，否则性质被证明成立。

## 实验评估

作者收集了 9 个 stateful P4 benchmark，包括 failover 方案、CoDel、NDN、P4NIS 和 P4xos acceptor/learner 变体，并构造了 19 个时序验证任务。`p4tv` 成功验证其中 14 个，对另外 5 个返回 counterexample。重要的是，这些反例并不是由过度近似制造出来的伪结果：工具找到了 P4NIS 中缺失的寄存器初始化假设、P4sp 中 heartbeat 相关的错误更新，以及 CPI 与代码里的注入 bug。

开销方面，运行时间约 10 秒到 21 分钟，中位数 51 秒，平均 181 秒；内存约 201 MB 到 6.1 GB。论文还把 assertion verification 与 bf4、p4v 做了比较。`p4tv` 在 stateless assertion 上更慢，因为它坚持使用 multi-packet model；但在 stateful assertion 上更精确，旧工具可能因为忘掉目标寄存器配置而报告伪 counterexample。可扩展性实验也很坦诚：程序和规范一复杂，验证时间就会迅速上涨。

## 创新性与影响

这不是给已有 verifier 换一个 P4 前端而已。论文同时贡献了包序列级执行模型、P4 专用时序逻辑，以及让 model-checking 语义与 packet-processing 语义一致的 `Büchi transaction`。因此，它真正把验证范围从“单个包”推进到了“多个包之间的状态演化”。

这对依赖历史状态的 programmable switch 逻辑很有价值，例如 failover、content-centric forwarding 和 Paxos 风格控制路径。`p4tv` 让这些设计可以直接对照它们真正的时序契约来验证，而不是先被迫弱化成单包性质。

## 局限性

原型完整支持 V1Model，但对 TNA 和 PSA 只提供有限支持。`P4LTL` 只观察包边界状态，因此不覆盖只在 pipeline 中途短暂出现的违规。方法本身也没有摆脱 model checking 的 state explosion，论文自己的曲线已经显示程序或公式一旦变大，求解时间就会急剧上升。最后，有些性质只在特定 table rule 下成立，所以用户往往需要补充 CPI，而不是假设完全开放的控制平面。

## 相关工作

- _Liu et al. (SIGCOMM '18)_ - `p4v` 用 SMT 求解验证较真实的 P4 语义，但它在每个包前都重置寄存器状态，因此无法证明跨包的时序性质。
- _Stoenescu et al. (SIGCOMM '18)_ - Vera 把 symbolic execution 和 NetCTL 风格的推理带到 P4，但它关注的仍是单包处理，而 `p4tv` 把时间模型提升到了多包 trace。
- _Tian et al. (SIGCOMM '21)_ - Aquila 把 P4 验证推进到更接近生产规模的场景，但仍然停留在 per-packet verification，而不是跨包的状态演化。
- _Kang et al. (ASPLOS '21)_ - P4wn 同样把 stateful P4 程序视为重复执行的循环，不过它是做 adversarial profiling 的 probabilistic testing 工具，不是时序模型检查器。

## 我的笔记

<!-- empty; left for the human reader -->
