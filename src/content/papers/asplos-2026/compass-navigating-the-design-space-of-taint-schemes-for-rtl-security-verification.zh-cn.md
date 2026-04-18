---
title: "Compass: Navigating the Design Space of Taint Schemes for RTL Security Verification"
oneline: "把 CEGAR 用到 RTL taint analysis 上，只在证明特定安全性质所必需的硬件位置增加精度，从而降低验证开销。"
authors:
  - "Yuheng Yang"
  - "Qinhan Tan"
  - "Thomas Bourgeat"
  - "Sharad Malik"
  - "Mengjia Yan"
affiliations:
  - "Massachusetts Institute of Technology, Cambridge, Massachusetts, USA"
  - "Princeton University, Princeton, New Jersey, USA"
  - "École Polytechnique Fédérale de Lausanne, Lausanne, Switzerland"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790144"
code_url: "https://github.com/MATCHA-MIT/Compass"
tags:
  - security
  - hardware
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Compass 把 RTL taint scheme 设计变成一个 CEGAR 循环，而不是一次性做全局选型。它先从粗粒度 module-level abstraction 起步，再只细化那些会制造 spurious taint counterexample 的局部位置，最终得到针对具体安全性质的低开销 taint scheme。

## 问题背景

对 RTL 做硬件信息流跟踪的吸引力在于，它把原本需要两条轨迹比较的 non-interference 检查，压缩成单条轨迹上的 taint 检查。但现实中的 taint scheme 都依赖 over-approximation 才能跑得动：精度太高，验证工件会急剧膨胀；精度太低，就会制造 false taint 和 spurious counterexample。

论文的动机是，这种 precision-complexity tradeoff 在处理器内部并不均匀。branch predictor 也许只需要一个 summary taint bit 就能发现真实泄漏，而 ROB 往往必须更细，因为不同 entry 可以处在不同 taint 状态。GLIFT、RTLIFT、CellIFT 等工作各自提供了一个全局方案，但真正困难的是：如何针对一个具体 RTL 设计和一个具体安全性质，系统化地找到“足够精确但尽量便宜”的 scheme。

## 核心洞察

Compass 的关键洞察是：taint scheme 设计本质上是 abstraction refinement。一个粗粒度 scheme 是真实信息流的抽象；spurious taint counterexample 说明这个抽象在某个局部太粗；因此 refinement 不该全局升级，而应只落在制造这条假 taint 路径的局部硬件位置上。

这样一来，优化目标就变了。Compass 追求的不是一个普适的最精确 taint discipline，而是一个 property-specific scheme：只在已经被当前 proof attempt 证明不够精确的地方增加精度。

## 设计

Compass 先把 taint design space 组织成三个维度：unit level 可以是 gate、cell、module；taint-bit granularity 可以是 per-bit、per-word 或 grouped/module；logic complexity 可以是 naive、partially dynamic、fully dynamic。整个框架从这个空间里最便宜的点起步，也就是每个模块一个 taint bit、传播逻辑用 naive 规则。

把 RTL 加上 taint instrumentation 之后，Compass 用 model checker 去验证 secure-speculation 信息流性质。如果拿到 counterexample，它先判断相关信号是真 taint 还是 false taint。论文给出了一个精确的 bounded model-checking 判定方式，而实际实现里用更快的近似：在 simulation 中翻转 secret 输入，看该信号值会不会变。

对 falsely tainted sink，Compass 会在 taint propagation graph 上做 backward tracing，只沿着同时满足“falsely tainted”和“在当前 counterexample 下 observable”的 fan-in 往上走。这个 observable 过滤很关键，因为它避免了工具把时间花在未被选中的 MUX 输入之类的无效路径上。回溯停下来的地方，就被视作局部 imprecision 的来源。

接下来的 refinement 按固定顺序尝试：先增加 logic complexity，再细化 taint-bit granularity，最后才考虑需要人工参与的更高层 customization。每次成功 refinement 都等于在假 taint 路径上打一个 cut，然后重新仿真 counterexample 并再次做 model checking。Compass 探索的所有 scheme 都保持 sound，但它明确把 correlation-based imprecision 留给人工处理，而且最终在多个 candidate scheme 之间的选择仍未完全自动化。

## 实验评估

论文在四个开源 RISC-V 处理器上评估 Compass：Sodor、Rocket、BOOM-S 和 ProSpeCT-S。目标任务是 speculative execution 相关的信息流验证，形式上是 software-hardware contract，因此既安全关键，也非常考验 formal verification 的可扩展性。

和 CellIFT 相比，Compass 把平均 taint gate overhead 从 `293%` 降到 `46%`，把 taint register bit overhead 从 `100%` 降到 `15%`。在一组 RISC-V benchmark 上，平均 simulation overhead 从 `351%` 降到 `205%`。formal verification 的收益更关键：Sodor 的 proof 时间从 `1.6 hours` 降到最终 scheme 下的 `9.8 seconds`，把 refinement 算进去也只有 `5.2 minutes`；Rocket 的 bounded-proof 深度从 CellIFT 七天内的 `41` cycles 提升到 `25.3` 小时内的 `159` cycles；ProSpeCT-S 虽然仍是 `29` cycles，但达到这个 bound 的时间明显短于 CellIFT 和 self-composition。作者还在实验中发现并确认了 ProSpeCT 的两个 bug。

最有说服力的定性结果来自 Rocket 的事后分析。Compass 并不是把整颗设计一股脑细化，而是把精度集中花在 secret/public 边界上，比如 cache data array 和 selector 密集的数据通路，同时让纯 public 的 decode 逻辑继续保持粗粒度。

## 创新性与影响

和 _Solt et al. (USENIX Security '22)_ 相比，Compass 的新意不是提出一个更强的全局 taint scheme，而是提出一种导航不同 scheme 的方法，只在性质真正需要的地方购买精度。和 _Yang et al. (CAV '18)_ 相比，它把 CEGAR 风格的 taint refinement 真正落到了 RTL 硬件上，并用 false-taint backtracing 自动寻找 refinement site。和 _Tan et al. (ASPLOS '25)_ 相比，它为 secure-speculation contract 提供了更轻量的替代路径。

它的影响主要是方法论上的：把 taint-scheme 选型从专家试错，变成一个有反馈的工作流，并证明 property-specific tainting 的确能改善 simulation throughput 和 model-checking scalability。

## 局限性

Compass 还没有做到完全自动化。它能自动找 candidate refinement location，但最终在多个 candidate scheme 之间怎么选，当前实现仍需要人工按顺序尝试。它也明确不处理 correlation-based imprecision，所以某些 false taint 模式还是要依赖更高层的人工判断。

它的精度保证也有边界。论文只宣称：对已经检查到的性质、以及已经覆盖到的 cycle bound，生成出的 scheme 尽量精确；并不保证对所有未来性质或所有无界执行都同样没有 false positive。与此同时，Compass 仍依赖 model checker 先产出 spurious counterexample，而且循环过程中也可能积累后来会变得多余的 refinement。

## 相关工作

- _Solt et al. (USENIX Security '22)_ — CellIFT 是论文最主要的精确基线：cell-level、per-bit、并且大体 fully dynamic，但它仍然是全局统一 scheme，而不是 property-specific refinement。
- _Ardeshiricham et al. (DATE '17)_ — RTLIFT 提供了 operator-level 的 taint tracking 和有限的精度/复杂度调节，但不会利用 counterexample 去选择性细化不同 RTL 区域。
- _Yang et al. (CAV '18)_ — Lazy self-composition 是最接近的概念先驱，同样把 CEGAR 用在安全验证上，不过面向的是软件式 transition system，而不是 RTL taint design。
- _Tan et al. (ASPLOS '25)_ — Contract Shadow Logic 用 self-composition 验证 secure speculation；Compass 说明 taint refinement 在同一类 contract 上可以更具可扩展性。

## 我的笔记

<!-- empty; left for the human reader -->
