---
title: "Borrowing Dirty Qubits in Quantum Programs"
oneline: "QBorrow 把 dirty-qubit borrowing 形式化为语言构造，并把 X/MCX 类电路的 safe uncomputation 检查化简成只需 `|0⟩` 与 `|+⟩` 两种情形的 SAT 问题。"
authors:
  - "Bonan Su"
  - "Li Zhou"
  - "Yuan Feng"
  - "Mingsheng Ying"
affiliations:
  - "Tsinghua University, Beijing, China"
  - "Institute of Software, Chinese Academy of Sciences, Beijing, China"
  - "University of Technology Sydney, Sydney, Australia"
conference: asplos-2026
category: quantum
doi_url: "https://doi.org/10.1145/3779212.3790134"
code_url: "https://github.com/SugarSBN/QBorrow"
tags:
  - quantum
  - hardware
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文提出了 QBorrow，把 dirty qubit 的借用从“电路技巧”提升成显式的 `borrow ... release` 语言构造。它的核心贡献是把 safe uncomputation 定义成“程序对被借 qubit 的作用等价于恒等映射”，并针对 `X` 与多控 `NOT` 电路给出一个可扩展的 SAT 化验证器。

## 问题背景

dirty qubit 之所以重要，是因为它允许程序复用暂时空闲的 qubit，而不必额外申请初始化为 `|0⟩` 的 clean ancilla。在 NISQ 时代，这直接关系到电路宽度和可运行规模。难点在于，dirty qubit 的正确性要求比 clean ancilla 更强：计算既不能依赖它未知的初始状态，也必须在结束后把它原本的状态，连同和外部系统的纠缠，一起恢复回来。论文指出，现有 dirty-ancilla 技巧大多停留在电路层，缺少语言层面对借用生命周期和安全归还的明确表达。更关键的是，最直觉的 basis-state 检查并不充分；论文的反例表明，一个电路即使能恢复 `0` 和 `1`，也仍可能在 `|+⟩` 上失败。因此，真正的问题是：如何为带控制流和 nondeterministic borrowing 的量子程序定义 safe dirty-qubit reuse，并让这一性质可验证。

## 核心洞察

这篇论文最核心的判断是：safe uncomputation 应该被定义成一种“恒等作用”的可观察等价性，而不是狭义的 basis-state 恢复规则。若程序的每次执行都等价于 `I_q ⊗ E'`，那么外界就无法分辨这个 dirty qubit 是否被借用过。这样一来，三个直觉就统一了：恢复任意纯态、保持外部纠缠不变、以及消除“到底借了哪个空闲 qubit”带来的非确定性。更重要的是，在只由 `X` 和多控 `NOT` 构成的经典可逆电路里，这个量子安全性条件可以只检查 `|0⟩` 和 `|+⟩` 两种初态，再化成 SAT 问题。

## 设计

QBorrow 在 QWhile 上加入 `borrow a; S; release a`，其中 `a` 是占位符，运行时会从语法定义的 `idle(S)` 集合中 nondeterministically 实例化为某个空闲 qubit。于是，程序语义不再是单个量子操作，而是一组量子操作；borrow 就是其中的非确定性来源。这个设计也自然支持嵌套 borrow，以及同一个物理 qubit 在两个不重叠生命周期里被先后复用。

在此基础上，论文把 safe uncomputation 定义为按 qubit 的性质：若 `S` 的每个可能执行都可写成 `I_q ⊗ E'`，则 `q` 被安全 uncompute。作者证明，这等价于恢复 `q` 的任意纯初态，也等价于保持 `q` 与外部假想系统的任意纠缠。为了做自动化验证，论文把语义条件先收缩到有限状态基，再专门处理由 `X` 和多控 `NOT` 构成的经典可逆电路。做法是给每个 qubit 维护布尔公式来跟踪其 basis 值的变化；恢复 `|0⟩` 与恢复 `|+⟩` 最终分别对应两个不可满足性检查，再交给 CVC5 或 Bitwuzla 求解。

## 实验评估

实验问题很聚焦：这个专用验证器在真正使用 dirty ancilla 的电路上能扩展到多大规模。实现使用 C++ 与 ANTLR4，`g++ -O3` 编译，运行在 8 核 Apple M3、`24 GB` 内存的 MacBook Air 上；基准是来自 Gidney 的 MCX 电路和来自 Häner 等人的 constant adder。论文说明，布尔公式构造本身在 `1s` 内完成，因此主要成本来自 CVC5 或 Bitwuzla。

结果很强。对 MCX，CVC5 从规模 `500` 的不足 `1s` 增长到规模 `3500` 的 `19s`，Bitwuzla 则从 `3s` 增长到 `189s`。对 adder，工具验证到 Adder-200，Bitwuzla 达到 `303s`，CVC5 达到 `1079s`。和 AutoQ 的对比更关键：AutoQ 在 MCX-500 时是 `32s`，到 MCX-3500 时上升到 `3065s`；在 adder 上，即使只验证一个 dirty qubit、只检查 `|+⟩` 条件，也全部 overrun。相比之下，本文方法验证的是所有 dirty qubit 对 `|0⟩` 与 `|+⟩` 的恢复，因此论文的主张是成立的：一旦专门利用 dirty-qubit safety 的结构，验证扩展性会显著提高。

## 创新性与影响

相对于 _Svore et al. (RWDSL '18)_，这篇论文的新意不在 `borrow` 这个关键词本身，而在于它第一次给 dirty-qubit borrowing 配上了严格语义，并明确说明何谓安全归还。相对于 _Bichsel et al. (PLDI '20)_ 这样的 clean-ancilla 工作，它说明 dirty ancilla 需要的是 identity-preservation，而不是简单回到 `|0⟩`。相对于 AutoQ，它的方法论价值在于找到一个重要而结构化的子域，把量子验证问题降成 SAT。它更像量子 PL、编译器和验证基础设施，而不是新的体系结构机制。

## 局限性

最大的局限是范围。论文的语义框架覆盖完整 QBorrow 程序，但高效验证器只处理由 `X` 和多控 `NOT` 组成、实现经典函数的电路；这足以覆盖 MCX 和 constant adder，却还不能推广到一般量子子程序。实验也主要集中在两类基准上，衡量的是求解器代价，而不是完整编译链路。最后，`idle(S)` 仍是语法性的，因此 discussion 里提到的、更激进的编译器自动发现空闲 qubit 机会，目前还没有真正实现。

## 相关工作

- _Svore et al. (RWDSL '18)_ — Q# 已经提供了 `borrow` 构造，但没有像 QBorrow 这样形式化并验证 dirty qubit 的 safe uncomputation。
- _Bichsel et al. (PLDI '20)_ — Silq 处理的是 clean ancilla 的 safe uncomputation，而本文说明 dirty ancilla 需要保持状态与纠缠的恒等式语义，不能简化为重新初始化。
- _Paradis et al. (PLDI '21)_ — Unqomp 自动综合 clean-ancilla 电路中的 uncomputation；QBorrow 则关注 borrowed dirty qubit 何时算被安全归还。
- _Abdulla et al. (POPL '25)_ — AutoQ 是通用量子电路验证器，而本文通过专门的 SAT reduction 放弃一部分通用性，换来了 dirty-qubit safety 上显著更好的扩展性。

## 我的笔记

<!-- 留空；由人工补充 -->
