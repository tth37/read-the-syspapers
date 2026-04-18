---
title: "VEP: A Two-stage Verification Toolchain for Full eBPF Programmability"
oneline: "VEP 把 eBPF 的证明搜索放到用户态带注释 C 上，再把证明编译进字节码，让内核只保留一个小型 proof checker。"
authors:
  - "Xiwei Wu"
  - "Yueyang Feng"
  - "Tianyi Huang"
  - "Xiaoyang Lu"
  - "Shengkai Lin"
  - "Lihan Xie"
  - "Shizhen Zhao"
  - "Qinxiang Cao"
affiliations:
  - "Shanghai Jiao Tong University"
conference: nsdi-2025
code_url: "https://github.com/yashen32768/NSDI25-VEP-535"
tags:
  - ebpf
  - kernel
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

VEP 把 eBPF 验证改造成一条 proof-carrying pipeline。开发者先在 eBPF 风格的 C 程序里写规格和 loop invariant，`VEP-C` 在用户态完成最重的 symbolic execution 和 SMT 推理，`VEP-compiler` 把代码、断言和证明一起下沉到 bytecode，`VEP-eBPF` 则让内核里只保留一个小型 proof checker。对 41 个程序，原型系统接受了全部带充分注释的安全程序，并拒绝了全部不安全程序，而现有自动 verifier 仍会误拒很多安全案例。

## 问题背景

eBPF 真正有价值的时候，程序往往并不简单：循环会遍历 packet state 或 map，helper 会获取和释放 kernel resource，安全性取决于 aliasing、边界检查和 acquire-release discipline。现有 verifier 为了保护内核，通常只能保守。Linux verifier 依赖寄存器值跟踪来沿路径模拟执行，因此必须限制程序长度和循环复杂度来压住 path explosion。PREVAIL 用 abstract interpretation 合并状态，但论文指出，一旦循环退出条件或内存行为依赖运行时数据，它的精度仍然不够。

几个看似直接的修补办法都不适合真正的部署路径。把更强的 SMT solver 或 theorem prover 放进内核，会同时放大资源开销和 trusted computing base。只相信用户态 C verifier 也不够，因为那样开发者还得顺带相信 compiler 一定保留了已验证语义。反过来，如果只在 bytecode 层验证，优化后的程序和源代码已经相距很远，开发者几乎拿不到可读的调试反馈。于是论文要同时满足三个约束：在给出足够注释时接受任意安全 eBPF 程序，把内核里的可信部件压到最小，并让开发者仍在 C 源码层面工作。

## 核心洞察

论文的核心判断是把 proof search 和 proof checking 分开。证明搜索昂贵、启发式强、依赖求解器，应该放在用户态的带注释 C 上完成。证明检查则应落在真正要加载的 bytecode 边界，只做简单 symbolic execution 和 proof replay，这样内核只需要信任一个紧凑的 checker。

这种拆分把注释变成了可编程性的出口。系统不再强迫 verifier 自动推断所有 loop invariant、memory-disjointness 事实和 helper protocol，而是允许程序员把这些关键性质显式写出来。随后，VEP 再把机器可检查的证明一路携带到最终加载的 eBPF 工件上。

## 设计

VEP 由三个部件组成。`VEP-C` 用一阶逻辑加 separation logic 来验证带注释的 C 程序。函数规格使用 `With`、`Require` 和 `Ensure`，loop invariant 描述每轮迭代边界必须满足的性质。其断言语言可以表达数组和指针权限、互不重叠的内存区域、helper 获取的资源、acquire-release discipline，以及超出 memory safety 的 functional property。`VEP-C` 对程序做 symbolic execution，计算 strongest postcondition，用内置 SMT solver 检查 entailment，并记录 proof term。论文特别强调的一点是：即便后端 compiler 可能碰巧生成看起来安全的 bytecode，带 undefined behavior 的 C 程序也要在这一层尽早被拒绝。

`VEP-compiler` 不是普通的代码生成器。它必须在 IR lowering、BPF calling convention、frame layout、spill 和 register allocation 之后，继续让断言和证明与编译后的程序保持一致。论文里一个很关键的细节是，当源变量在分配后已经不再存活时，相应断言不会被直接丢掉，而是改写成 existential logic variable 来保留事实。helper function 的 specification 也会一起下沉，这样 bytecode 层仍然知道某次调用到底获取或释放了什么资源。

`VEP-eBPF` 是加载路径上唯一需要信任的组件。它会重新对 annotated bytecode 做 symbolic execution，复查安全条件，并验证从上游传下来的证明，而不是再调用一次 SMT solver。separation logic 的空间部分用简单的 derivation rule 检查，纯命题部分则用一种受 cvc5 启发的 proof language 检查。因为 checker 只负责重放证明，而不是现场搜索证明，所以内核侧 verifier 能比通用自动验证器小得多。

## 实验评估

评估共包含 41 个程序：10 个 Linux kernel samples、10 个 PREVAIL samples、10 个 C `StringLib` 函数、10 个 unsafe programs，以及 1 个较大的 `Key_Connection` case study。三种工具都能拒绝 10 个不安全程序。差别主要出现在安全程序的接受率上。VEP 对三类安全程序都达到 `10/10`，并成功验证 `Key_Connection`。Linux verifier 对 Linux samples 是 `9/10`，对 PREVAIL samples 是 `6/10`，对 `StringLib` 只有 `3/10`，并且无法处理 `Key_Connection`。PREVAIL 在 Linux samples 上达到 `10/10`，在自家样例上是 `8/10`，但在 `StringLib` 上只剩 `1/10`，同样无法完成 `Key_Connection`。

性能数字基本支撑了两阶段设计的论点，不过它们更像研究原型，而不是生产快路径。Linux verifier 仍然是最便宜的 baseline，平均不到 1 ms，内存低于 5.2 MB。`VEP-C` 因为要在源码层完成 solver-backed verification，所以明显更重，例如在 Linux samples 上平均 39.46 ms、32.6 MB。compiler 阶段开销很小。内核侧的 `VEP-eBPF` checker 要轻得多：在 Linux samples 上平均 8.42 ms、8.0 MB，在 PREVAIL samples 上是 2.76 ms、3.0 MB，在 `StringLib` 上是 2.63 ms、3.0 MB。这说明最昂贵的推理确实被推出了内核，同时又保留了最终的内核内复查。

真正的代价在 annotation。对 618 行 Linux sample 代码，用户只写了 76 条 assertion，但 VEP 生成了 64,840 行 proof。63 行的 `Key_Connection` 例子则膨胀成 350 行 annotated bytecode 和 5,800 行 proof。也就是说，VEP 并不是 annotation-free，而是在主张少量高层注释可以驱动大量自动证明生成。

## 创新性与影响

这篇论文的新意在于把整条链路拼完整。已有 eBPF verifier 要么完全自动但相当保守，要么能力更强，却把用户暴露在 bytecode 或 theorem prover 层。VEP 则给出一个源码级 annotation interface、一个 annotation-aware compiler，以及一个能放在 kernel loading path 上的 proof-carrying bytecode checker。相比“直接给今天的 verifier 再塞一个更强 solver”，这是一个更接近部署现实的 full programmability 答案。

如果这条路线继续成熟，它的影响会很直接。eBPF 开发者将能写出更复杂的循环、更细致的 helper-resource protocol，甚至加入当前自动 verifier 很难证明的 functional-correctness property。`Key_Connection` case study 也提示了它的实际意义：一些更复杂的 L7 logic 之所以被迫外移到代理进程，不是因为 eBPF 不能表达，而是因为验证能力还不够。

## 局限性

VEP 最强的结论依赖用户提供注释。论文写得很明确：任意安全程序能够通过，前提是用户给出了足够的 precondition、postcondition 和 loop invariant。这是一笔真实的人力成本，尤其当验证目标从 memory safety 进一步走向 functional correctness 时更是如此。

当前原型在工程范围上也比较有限。compiler 故意只实现了少量 optimization pass，因此生成的 bytecode 并不是以最优为目标。helper specification 也是内建的，而不是自动发现的。评估虽然足够说明可行性，但仍主要停留在 benchmark 规模：Linux samples、教学风格的 `StringLib` 例子，再加一个较大的 case study，还不能等同于大型、持续演进的生产 eBPF 代码库。最后，`VEP-eBPF` 检查的是 bytecode 是否符合给定 annotation 和 proof，而不是这些 annotation 是否真正表达了程序员的意图。

## 相关工作

- _Gershuni et al. (PLDI '19)_ - `PREVAIL` 通过 abstract interpretation 保持 eBPF 验证的完全自动化，而 `VEP` 用用户注释换取对复杂但安全程序更少的误拒绝。
- _Nelson et al. (LPC '21)_ - `ExoBPF` 也探索 proof-carrying 的 eBPF 内核验证，但它要求用户直接在 bytecode 层思考，而 `VEP` 把注释入口放在 C 层，再把证明工件向下编译。
- _Nelson et al. (SOSP '19)_ - `Serval` 关注 systems code 的 scalable symbolic evaluation，而 `VEP` 把这类思路专门落到 source-to-eBPF pipeline 上，并把最终 trust point 收缩到内核中的 checker。
- _Necula (POPL '97)_ - Proof-Carrying Code 提供了 producer/checker 分离的基本框架，`VEP` 则把它具体化到 Linux 的 eBPF loading path。

## 我的笔记

<!-- 留空；由人工补充 -->
