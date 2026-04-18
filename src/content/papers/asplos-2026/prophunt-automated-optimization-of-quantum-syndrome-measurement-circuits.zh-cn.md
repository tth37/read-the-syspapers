---
title: "PropHunt: Automated Optimization of Quantum Syndrome Measurement Circuits"
oneline: "PropHunt 通过定位含歧义的 hook-error 子图并重写 CNOT 顺序，迭代消除 syndrome-measurement 电路中的逻辑故障路径。"
authors:
  - "Joshua Viszlai"
  - "Satvik Maurya"
  - "Swamit Tannu"
  - "Margaret Martonosi"
  - "Frederic T. Chong"
affiliations:
  - "University of Chicago, Department of Computer Science, Chicago, IL, USA"
  - "University of Wisconsin-Madison, Department of Computer Sciences, Madison, WI, USA"
  - "Princeton University, Department of Computer Science, Princeton, NJ, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790205"
code_url: "https://github.com/jviszlai/PropHunt"
project_url: "https://doi.org/10.5281/zenodo.17945386"
tags:
  - hardware
  - compilers
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PropHunt 把坏的 syndrome-measurement 电路看成 decoding ambiguity 问题，而不是单纯的 depth 问题。它从 circuit-level decoding graph 中采样含歧义的子图，在子图里求最小权重逻辑故障，再通过局部重写 CNOT 顺序去消除这些歧义。论文显示，它既能自动恢复 surface code 的手工优良 schedule，也能把 LP 和 RQT 代码的逻辑错误率降低 `2.5x-4x`，并进一步把这些中间电路拿来做 Hook-ZNE，使偏差相对 DS-ZNE 降低 `3x-6x`。

## 问题背景

这篇论文讨论的是一个只有在容错量子计算真正走向系统实现时才会变得尖锐的问题。对 CSS 码来说，光有 parity-check matrix 还不够，系统还必须把它编译成反复执行的 syndrome-measurement 电路。在这个过程中，错误不是“尽量不要发生”的偶发事件，而是测量流程内部预期会发生的一部分。于是，CNOT 的具体执行顺序会决定 ancilla fault 如何传播成 hook error，进而决定哪些物理错误能够被发现、哪些能够被纠正，以及代码最终呈现出什么逻辑错误率。

这也解释了为什么传统优化目标并不对路。NISQ 时代的电路优化工具主要最小化 gate count 或 circuit depth，因为它们假设目标是降低“任何错误发生的概率”。而在 syndrome measurement 里，错误本来就会发生，真正重要的是电路如何塑造这些错误的传播结构。论文用 surface code 说明，circuit depth 和 effective code distance 都是不完备的代理指标。两个电路即便 depth 或 `d_eff` 一样，逻辑错误率也可能显著不同；甚至一个最小深度 schedule 也可能比更合理的 CNOT 排序差约 `10x`。现有方案同样有明显缺口：手工 schedule 太依赖专家经验且难以迁移，brute-force 搜索只能处理被强烈参数化后的缩小设计空间，而已有综合工具仍然围绕这些不完美代理指标打转。论文真正要解决的问题是，怎样在不依赖每种 QEC 码都有人手写几何技巧的前提下，直接为逻辑可靠性优化完整的 syndrome-measurement 电路。

## 核心洞察

论文最重要的洞察是，syndrome-measurement 电路中的逻辑故障可以理解成 ambiguity。也就是，两组不同的故障模式可能翻转完全相同的 syndrome bit，却对应不同的 logical outcome。此时 decoder 没有足够信息区分两者，最终失败概率就由这两种竞争性解释里较不可能的那一方控制。用论文的符号说，就是两组错误在 `H` 上的像相同，但在 `L` 上的像不同。

这个视角的关键价值在于，ambiguity 不是只由 code 决定的。circuit-level 的 `H` 和 `L` 会随着 CNOT 排序以及 syndrome qubit 在共享 data qubit 上的相对时序而改变。只要一个局部电路改动能让相关子图从“可歧义”变成“不可歧义”，就等于消掉了一条逻辑故障路径，而 stabilizer code 本身并没有改变。所以 PropHunt 并不试图从零开始全局重构整个电路，而是反复寻找局部含歧义的子图并逐个修补。论文中 surface code 的例子很直观：一个糟糕 schedule 会因为 hook error 的两种解释在 decoder 看来完全等价，从而形成 reduced-distance 的逻辑故障；而一个小的 CNOT 顺序调整就足以让某个 syndrome bit 重新带来判别力。

## 设计

PropHunt 的工作对象是 circuit-level decoding graph。这是一个二部图，一侧是 gate fault 对应的 error node，另一侧是这些故障会翻转的 syndrome bit，对应 syndrome node。整个优化循环分五步。第一步，从随机 error node 出发向外扩展子图，直到当前连通子图满足 `L' notin rowsp(H')`，这说明子图内部确实存在 ambiguity。论文特意限制只在连通子图上扩展，因为不连通分量之间不可能共同构成同一个含歧义的逻辑故障。

第二步，在找到含歧义子图之后，PropHunt 用 MaxSAT 在子图内部求一个最小权重的 logical error。它把 syndrome parity 与 logical observable 都编码成 error variable 上的硬 XOR 约束，再加入“该错误模式对 stabilizer 不可见、但至少翻转一个 logical observable”的硬约束，并用软约束最小化被选中的故障数。实现上先用 `Z3` 做简化和 CNF 转换，再用 `Loandra` 求解。为了避免朴素 XOR 转 CNF 带来的指数膨胀，作者引入了辅助变量构造树状分解。

第三步，PropHunt 把这些故障映射回源头 CNOT，并枚举局部改写。reordering change 会调整同一个 stabilizer 内 data qubit 的交互顺序，让 hook error 落到不同的一组 qubit 上；rescheduling change 则交换两个 syndrome qubit 在共享 data qubit 上的相对先后，使故障被检测到的时间发生变化。为处理后者，系统使用一个关于 syndrome qubit 的有向多重图来跟踪相对次序与 commutation 约束。

第四步是剪枝。候选改写必须仍然对应一个合法、可调度的 syndrome-measurement 电路；同时更新后的局部 `H'` 与 `L'` 必须证明原先的 ambiguity 已被消除，而不是把同一批错误重新变成另一条 logical fault。最后，系统把所有彼此兼容且已验证的改写一并应用；若多种改写互相冲突，则以最短 circuit depth 作为二级目标来打破平局。换句话说，PropHunt 真正优化的不是 depth 或 distance 本身，而是会在 decoder 里制造真实逻辑失败的 ambiguity。

## 实验评估

实验设计对论文的核心问题是有说服力的。作者从 Tremblay 等人的 coloration circuit 出发，把它当作通用 CSS baseline，然后让 PropHunt 最多运行 `25` 轮、每轮采样 `500` 个子图，并用 `48` 个 Intel Xeon Silver 4116 核心并行做 ambiguous-subgraph finding。逻辑错误率通过 `Stim` 在标准 circuit-level 噪声模型下模拟 `d` 轮 syndrome measurement；surface code 用 `PyMatching` 解码，LP 与 RQT 代码则用 `BP-LSD`。 

在 `[[9,1,3]]` 到 `[[81,1,9]]` 的 surface code、一个 LP 码和三个 RQT 码上，PropHunt 相对 baseline 全部都有改进。对 surface code 来说，它最终达到了经典手工 schedule 的性能，这很重要，因为这说明搜索过程确实自动找回了人类专家过去总结出的结构规律。对 LP 和 RQT 这类此前没有成熟优良 schedule 的代码，PropHunt 在物理错误率 `0.1%` 时把逻辑错误率降低了 `2.5x-4x`。另外，从三种不同随机 coloration circuit 开始的鲁棒性实验也显示它不是只在某一个幸运起点上有效。

求解器层面的分析也很关键，因为它解释了为什么论文要走“子图求解”这条路。以 `[[49,1,7]]` 为例，全局 MaxSAT 公式需要 `45050` 个变量，求解时间达到 `1 hr 55 min`；而 ambiguous-subgraph 版本只有 `340` 个变量，求解时间 `1.28 s`。在 `[[60,2,6]]` 上，全局求解甚至直接超时，但子图版本仍只需约 `1.39 s`。idle-error study 也是很有价值的补充。PropHunt 有时会让电路更深，但在相当宽的 idle-error 强度范围内，逻辑错误率的改进仍足以盖过这部分代价，尤其是在 neutral atom 这种 measurement 明显慢于两比特门的体系里。最后，Hook-ZNE 利用优化过程中的中间电路，在固定 distance 下构造更细粒度的逻辑噪声缩放；在论文的 randomized benchmarking 与 `20,000` shots 设置下，它比 DS-ZNE 的偏差低 `3x-6x`。这部分证据比主线 QEC 结果更窄，但足以支撑“PropHunt 还能暴露出一条有用的逻辑噪声连续谱”这一附加主张。

## 创新性与影响

相较 surface code 上那类手工设计的 `N-Z` schedule，PropHunt 的核心贡献是把这类经验技巧自动化，并推广到多个 code family，而不是再为某一类晶格写一个新的人工策略。相较 bivariate bicycle 或 color code 上的 brute-force 参数化搜索，它的关键变化是围绕含歧义的局部子图做搜索，而不是枚举一个缩小后的全局设计空间。相较 QECC-Synth 一类工作，它优化的是 syndrome extraction 的内部顺序，而不是 code 到硬件拓扑的兼容布局。

因此，这篇论文对容错量子体系结构、QEC 编译以及 decoder-aware 电路综合这几个方向都很重要。它既不是单纯的测量论文，也不是单纯的 solver 工程论文，而是提出了一个新的优化目标，也就是 ambiguity minimization，并把这个目标落实成了能产出更好 syndrome-measurement 电路和 Hook-ZNE 应用的实际工具链。

## 局限性

论文的适用范围是明确收紧过的，而不是“优化所有 QEC 电路”。PropHunt 目前面向 CSS codes，实验也集中在 surface、LP 和 RQT 这几类上。优化过程本身计算代价不低，需要反复做子图采样、MaxSAT 求解和并行 CPU 执行，因此它更像离线综合工具，而不是可以塞进编译器关键路径里的轻量级 pass。由于搜索是局部且带随机性的，论文也没有声称能达到全局最优。

实验证据完全来自仿真。这在容错 QEC 研究里并不奇怪，但也意味着结果会依赖论文采用的噪声模型、decoder 选择以及 baseline 电路家族。idle-error 分析虽然提供了一些现实感，但更具体的硬件约束，如 routing、校准漂移和平台专属门集，基本都留给了未来工作。Hook-ZNE 的证据则更初步，它是在合成的逻辑噪声缩放与 randomized benchmarking 电路上评估的，并不是端到端实际应用工作负载。

## 相关工作

- _Tomita and Svore (PRA '14)_ — 给出了经典的手工 surface-code schedule，而 PropHunt 的价值在于自动恢复这类结构，而不是把它当作先验输入。
- _Tremblay et al. (PRL '22)_ — 提供了通用 CSS coloration-circuit baseline，PropHunt 则在不改变 code 本身的前提下，通过修改错误传播去系统性超越它。
- _Shutty and Chamberland (Physical Review Applied '22)_ — 同样使用 solver 支撑 fault-tolerant 电路综合，但依赖 flag-based 构造；PropHunt 不增加额外 ancilla，而是直接重写标准 syndrome-measurement 电路。
- _Yin et al. (ASPLOS '25)_ — QECC-Synth 研究的是稀疏硬件上的 QEC layout synthesis，而 PropHunt 固定硬件兼容性，把优化焦点放在 syndrome extraction 的内部次序。

## 我的笔记

<!-- 留空；由人工补充 -->
