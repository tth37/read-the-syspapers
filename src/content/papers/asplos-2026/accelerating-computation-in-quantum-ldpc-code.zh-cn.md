---
title: "Accelerating Computation in Quantum LDPC Code"
oneline: "ACQC 用专用 pivot 模块加速 qLDPC 中的 Pauli product measurement 分解，再用 qLDPC 内部的 magic-state distillation 把额外 qubit 开销压回去。"
authors:
  - "Jungmin Cho"
  - "Hyeonseong Jeong"
  - "Junpyo Kim"
  - "Junhyuk Choi"
  - "Juwon Hong"
  - "Jangwoo Kim"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790122"
tags:
  - hardware
  - compilers
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

ACQC 讨论的是一个很关键的问题：qLDPC code 能不能不只是当低开销量子内存，而是真正承担 fault-tolerant quantum computing 里的计算工作。论文的回答是，先用专门的 pivot module 把 Pauli product measurement 的分解开销大幅压低，再通过共享 pivot 和 qLDPC 内部的 magic-state distillation，把这一步带来的额外 qubit 成本大部分拿回来。按论文的模拟结果，这让 qLDPC 计算从原先估计的 `40-70` 天缩短到 `11-17` 天，同时仍然保住它相比 surface code 最有吸引力的低 qubit 开销。

## 问题背景

这篇论文切中的矛盾很典型。Surface code 的优点是工程接口简单，因为它几乎可以直接执行任意的 Pauli product measurement；但代价也同样明显，物理 qubit 开销非常大。qLDPC code，尤其是论文聚焦的 Bivariate Bicycle code，则在编码率上更有吸引力，作者给出的量级是相对 surface code 能节省一个数量级左右的物理 qubit。

问题在于，qLDPC 的“便宜”来自更受限的操作集。一个 qLDPC module 只能通过它的 ancilla system 执行有限集合的 native PPM，因此程序里需要的任意 PPM 都必须先被分解成一长串 native PPM。真正卡住 qLDPC 实用性的，不是单个门慢，而是这层分解把所有执行时间放大了。论文引用的 state-of-the-art baseline 会带来平均 `17.4x` 的执行时间膨胀，使得原本只需几天的 chemistry 和 factoring 应用，在 qLDPC 上分别被拉长到约 `47.4` 天和 `76.8` 天。

已有方案都只能顾一头。Complex ancilla system 可以原生支持任意 PPM，但它同时推高 connectivity degree 和 qubit 数量；HetEC 这类 qLDPC-as-a-memory 方案把 qLDPC 当内存、surface code 当计算层，虽然减少了分解开销，却又把 load/store 传输和 surface-code patch 的成本带了回来。于是，论文真正要解决的是：能不能在维持最小 connectivity 和低 qubit 开销的前提下，让“在 qLDPC code 内直接计算”变得足够快。

## 核心洞察

ACQC 最关键的洞察是，传统 one-pivot 分解慢，不是因为任意 PPM 天生就必须慢，而是因为 baseline 为了复用单个 pivot，把整个过程强行串行化了。这样做的后果是，同样的 native PPM 会被重复执行两遍。论文观察到，如果把 surface-code lattice surgery 看成一个可以逐步展开的过程，而不是一次性整体完成的操作，那么任意 PPM 就可以重写成一串不同 pivot 依次参与的步骤。这样一来，就不必再为了“复用一个 pivot”而反复测量相同的 native PPM。

第二个洞察是，多 pivot 带来的 qubit 开销并不是不可控的。Pivot 不必和 program logical qubit 放在同一个 module 里；而 magic-state distillation 只会用到非常窄的一类测量模式。一旦接受这两点，系统就可以把 qubit 花在真正能换来延迟收益的地方，再通过共享 pivot 布局和面向 qLDPC 特性的 distillation 设计，把这部分 qubit 重新省回来。换句话说，论文认为 qLDPC 的瓶颈并不是“没有快的计算原语”，而是之前的 decomposition 和 factory 组织方式不对。

## 设计

ACQC 的设计由三部分连起来。第一部分是 fast PPM decomposition。论文把 baseline 的单 pivot、每轮需要六个 native PPM 的分解方式，替换成 direct decomposition 加 pivot-decoupled layout。Program logical qubit 留在 program module 里，pivot 被挪到单独的 pivot module；同时，pivot module 里的 physical data qubit 可以直接测量，因此 pivot 的初始化和读出不再被单一 ancilla path 串行化。更重要的是，编译器不再只搜索“一个程序 qubit 加一个 pivot”的 native PPM，而是可以利用整个 code 提供的 native PPM 组合。论文报告，在 gross code 上，任意 PPM 的平均分解长度从 `17.4` 个 native PPM 降到 `3.76` 个，对应分解本身大约 `4.6x` 的加速。

第二部分是 qubit-efficient PPM decomposition。Fast decomposition 很省时间，但会消耗更多 pivot，于是作者又设计了 pivot-module-sharing layout，让两个 program module 共享一个 pivot module：方法是利用 unprimed / primed block 分别走不同 ancilla system 的结构特性。与此同时，论文引入 hybrid decomposition policy。对绝大多数只需要少量 rounds 的 PPM，仍使用快但更耗 pivot 的方法；对那一小部分需要很多 rounds 的尾部 PPM，则改用更慢但更省 pivot 的递归分解。以 gross code 为例，这一步把 pivot 上限限制在三个，执行时间额外代价只有 `0.03%`，但 pivot 相关开销基本减半。

第三部分是 qubit-efficient distillation。前两步把执行变快之后，系统会更快地消耗 magic state；如果继续依赖大量 surface-code factory，整个 qLDPC 的 qubit 优势就会被吞掉。ACQC 因此把 distillation 也搬到 qLDPC module 内部。这里有两个优化。其一是 in-module parallel distillation：在一个 gross code 的 unprimed 和 primed 两半上并行跑两条 distillation sequence，从而把每条序列分摊到的 ancilla overhead 压低。其二是 decomposition-free distillation：利用那些会测到“未使用 logical qubit”的 native I/Z PPM，并先把这些未使用 qubit 初始化到 Z basis，使额外的 Z operator 变成无害项。这样 distillation 就能完全去掉 pivot module，同时把 distillation latency 再降 `42.4%`。

## 实验评估

由于当前还没有真正能实现整套 qLDPC 设计的硬件，论文主要依赖自研 simulator。Benchmark 来自 QASMBench 和 MQT Bench，包括 `adder`、`ising`、`multiplier`、`qft`、`qpe`、`qram` 和 `square_root`。对比对象并不弱：既有 all-surface-code 的 `PBC` 和 `EDPC`，也有 serial / parallel 两种 compute-in-qLDPC baseline，以及 HetEC 风格的 qLDPC-as-a-memory 配置。作者同时报告了 logical error rate、qubit 数量和执行时间，因此不是只挑单一指标。

最重要的结果是，ACQC 并不是单纯沿着原有 tradeoff 曲线移动，而是把整条 Pareto frontier 往更好的方向推。相对 baseline 的 compute-in-qLDPC，ACQC 在 serial 配置上带来 `4.4x` 加速，在 parallel 配置上带来 `5.2x` 加速，而 qubit 只分别增加 `4.7%` 和 `35.5%`。相对 `PBC`，它则能把 qubit 数量压低 `8.2x` 和 `5.8x`，代价只是执行时间分别慢 `3.6x` 和 `2.0x`。拆开看也很清楚：fast decomposition 主要增加的是 pivot module 和 distillation 的 qubit；共享 pivot 再把总 qubit 拉回 `12.3%` 和 `8.6%`；面向 qLDPC 的 distillation 优化继续减少 `32.2%` 和 `41.9%`。

论文在泛化性上的证据也比较扎实。对多种 qLDPC code，fast decomposition 平均能把 native PPM 数量降低 `4.58x`；而新的 distillation 设计在所评估的序列上把 magic-state 的 space-time cost 再压低 `61.0%`。更偏应用层的 extrapolation 虽然没有直接端到端跑出来，但仍然有参考价值：将测得的平均加速带回已有 chemistry 和 factoring 估计后，执行时间从约 `40` 天和 `70` 天下降到 `11` 天和 `17` 天。论文还在 IBM Heron 上做了一个小规模硬件实验，虽然因为当前物理错误率太高而无法验证正确性，但时间趋势和模拟一致，硬件实测平均加速 `5.04x`，模拟则是 `4.85x`。

## 创新性与影响

和 _Stein et al. (ASPLOS '25)_ 相比，ACQC 最重要的一步是拒绝退回到“qLDPC 负责存、surface code 负责算”的折中方案。它把受限的 native measurement 集视为编译器和布局问题，再反过来重构系统架构，使更快的 decomposition 不会因为 qubit 爆炸而失去意义。和 _Cohen et al. (Science Advances '22)_ 这类 complex-ancilla 方案相比，它的价值则在于坚持最小 connectivity 目标，同时仍然追回大部分性能收益。

因此，这篇论文对量子系统方向的价值，不是提出了新的 qLDPC code family，而是给出了一套“如何把现有 qLDPC 真正组织成可计算 substrate”的方法论。假如未来 qLDPC 硬件成熟，这篇论文很可能会同时被架构研究者和编译器研究者引用，因为它把模块布局、测量分解和 magic-state factory 这些原本分散的问题绑成了一个统一设计。

## 局限性

最显眼、也最不能回避的局限，是论文几乎全部结论都来自模拟，因为目标 qLDPC 硬件目前并不存在。真实硬件实验只是在低 connectivity 处理器上通过重映射执行 ESM 电路，用来验证速度趋势；作者明确说明，这个实验在当前物理错误率下无法验证功能正确性。Benchmark 规模也刻意控制得较小，因为今天的小 code-distance qLDPC 还支撑不了真正的大型应用；文中关于 chemistry 和 factoring 的 `11-17` 天结果，本质上是用平均加速乘回已有估计，而不是直接跑完的端到端数据。

设计上也有几个边界。ACQC 的 distillation 优化强依赖 distillation sequence 主要由 I/Z PPM 构成，作者也明确说第三个优化不适用于 cultivation-style magic-state factory。`⟦98, 6, 12⟧` pivot module 的 error-rate 建模采用了和 gross code 相同的保守假设，而不是直接测得数据。更一般地说，整套方案默认编译器能为所选 code family 暴力搜索到高效的 native PPM 组合；论文证明这对测试过的 BB 风格 qLDPC 成立，但并没有声称它自动适用于未来所有 qLDPC 构造。

## 相关工作

- _Bravyi et al. (Nature '24)_ — 证明了低开销 qLDPC memory 的可行性，但没有解决如何在 code 内高效执行通用计算。
- _Stein et al. (ASPLOS '25)_ — HetEC 把 qLDPC 当内存、把 surface code 当主动计算层，而 ACQC 试图把存储和计算都留在 qLDPC module 内。
- _Litinski (Quantum '19)_ — surface-code lattice surgery 提供了“任意 PPM 足够便宜”的参照系，ACQC 通过展开并重组 decomposition，去逼近这种性质。
- _Gidney and Fowler (Quantum '19)_ — 高效的 surface-code magic-state factory 构成了 qubit 与延迟上的基线，ACQC 的 qLDPC-native distillation 正是针对这条基线重新设计。

## 我的笔记

<!-- 留空；由人工补充 -->
