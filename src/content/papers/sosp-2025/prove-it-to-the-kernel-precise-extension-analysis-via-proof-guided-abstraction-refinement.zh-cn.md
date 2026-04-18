---
title: "Prove It to the Kernel: Precise Extension Analysis via Proof-Guided Abstraction Refinement"
oneline: "BCF 让 eBPF verifier 在内核内保持简单分析，把困难的 refinement 证明交给用户态，再用线性 proof check 收回 403 个误拒程序。"
authors:
  - "Hao Sun"
  - "Zhendong Su"
affiliations:
  - "ETH Zurich"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764796"
code_url: "https://github.com/SunHao-0/BCF/tree/artifact-evaluation"
tags:
  - ebpf
  - kernel
  - verification
  - formal-methods
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

BCF 给 Linux eBPF verifier 加了一条 proof-guided 慢路径：当 verifier 因为抽象状态过粗而准备拒绝程序时，它会把“更紧的抽象是否仍然 sound”这个问题交给用户态求证，再在内核里用线性时间检查证明。这样，内核仍然可以保留廉价的 interval 和 bit-level 分析作为常规路径，同时在少数卡住的位置借到接近 symbolic reasoning 的精度。在 512 个“实际上安全但原本会被误拒”的 eBPF 对象上，BCF 成功放行了其中 403 个。

## 问题背景

Linux eBPF verifier 的难点在于，它既必须挡住所有可能破坏 memory safety、termination 或 kernel calling discipline 的扩展，又必须运行在内核里，因而复杂度、延迟和 attack surface 都受到严格约束。为此，当前 verifier 主要依赖成本很低的抽象域，核心是 interval 和 tristate bit information。这些抽象很快，但它们恰好会丢掉真实 eBPF 程序最常依赖的事实：寄存器之间的关系、算术恒等式，以及某条控制流路径下才成立的约束。

结果就是持续出现 false rejection。程序本身是安全的，但 verifier 因为把 pointer range 放得过宽、忘记两个值本来相等，或者把不可达路径当成可达路径来分析，于是错误地报出非法访问。开发者只能围着 verifier 写代码，例如把 buffer 平白加倍、插入多余检查，甚至写 inline assembly 来“哄过” verifier。已有工作通常试图把更强的静态分析直接塞进内核 verifier，但更强的 abstract domain 也意味着更高的内核复杂度和运行时成本。论文真正想解决的是：能不能让 verifier 在内核里继续保持简单，却在需要时获得接近 symbolic execution 的精度？

## 核心洞察

论文的核心主张是，不应把 verifier 卡住看成“立即拒绝”，而应看成一次 refinement 机会。当现有抽象已经粗到无法证明安全时，内核其实不需要亲自做困难推理。它只需要恢复出和失败检查相关的精确 symbolic state，构造出“若要采用更紧抽象，哪些条件必须成立”这一 refinement condition，然后在用户态给出证明后做一次高效检查。

这个分工之所以成立，是因为 proof search 和 proof checking 的成本结构完全不同。判断一个 bit-vector 条件是否对所有赋值都成立，往往需要 solver 级别的搜索；但一旦证明已经给出，检查它通常只是一些局部规则的顺序应用。BCF 正是利用这一点：把昂贵搜索留在用户态，把内核侧工作压缩成确定性的 bookkeeping 和线性 proof check，从而在不引入隐藏信任的前提下换取高精度。

## 设计

BCF 不是重写 verifier，而是在现有 verifier 的基础上插入一条按需触发的 refinement 路径。正常情况下，verifier 仍按原来的方式运行，直到它在某个点上因为抽象过粗而认为程序不安全，例如推导出一个过宽的 pointer offset 区间，从而无法证明内存访问在界内。此时 BCF 先在当前分析路径上做 backward analysis，找到定义目标寄存器以及所有传递依赖寄存器的最短后缀。这样后续 symbolic tracking 不必覆盖整个程序，只需盯住真正相关的一小段代码；论文测得这个后缀平均只有 102 条指令。

接下来，BCF 会沿着 verifier 已经走过的那条分支历史，对这段后缀进行 symbolic replay。它不再只维护 interval，而是为相关寄存器构造精确的 bit-vector expression，并记录 path constraint。与此同时，它还复用 verifier 已有信息来简化表达式，例如当 verifier 已知某值一直处在 `u32` 范围时，就把 symbolic variable 缩成 32 位；纯常量计算也可直接折叠。拿到精确 symbolic state 后，BCF 再从失败的安全检查反推出“允许分析继续所需的 refined abstraction”。以 memory access 为例，verifier 需要 pointer offset 落在一个安全区间内，BCF 于是生成 refinement condition，要求 symbolic offset expression 的所有可能值都被这个更紧的区间包含。

这个条件会被编码成紧凑的二进制格式，通过共享缓冲区和恢复式 `bpf()` load 流程交给用户态，而不是新发明一条 syscall。loader 将条件翻译成 cvc5 可处理的 bit-vector logic，要求 solver 给出 counterexample 或 proof，然后把 proof 回传给内核。内核中的 proof checker 支持 45 条 primitive rule，按顺序扫描证明、重算每一步结论，并最终检查结论是否正好对应 verifier 先前保存的 refinement condition。只有 proof 通过后，verifier 才会在同一条指令上使用 refined abstraction 继续分析；否则程序被拒绝。

## 实验评估

这篇论文的评估很扎实，因为作者不是拿几个 toy case 演示，而是专门构造了一个真实数据集。它从 Cilium、Calico、BCC 和 xdp-project 等项目里收集 106 个真实 eBPF source program，再用 Clang 13 到 21、优化级别 `-O1` 到 `-O3` 反复编译，去重字节码后，再加入 9 个人工收集到的 rejection case。最终得到 512 个不同对象：它们之所以被视为“安全”，是因为同一源程序在某些 compiler configuration 下可以成功加载；而当前测试的那份对象只是因为 verifier 精度不足而被错误拒绝。

在这个数据集上，BCF 放行了 512 个对象中的 403 个，也就是 78.7%，并且让 106 个源程序中的 75 个在其所有编译变体上都完全通过。论文还提到 PREVAIL 作为对照，但由于其 Windows-oriented 设计带来兼容性问题，能成功加载的程序不到 1%。对剩余 109 个失败样本，作者也给出了解释：4 个样本是因为 BCF 还没有插桩到对应的 rejection site，所以根本没触发 refinement；82 个样本是当前实现限制导致 refinement condition 过弱或不成立，例如 stack tracking 还不完整；另有 23 个样本则撞上了 verifier 的一百万条指令上限，多见于 loop-heavy 的程序。

性能数据支持论文的关键系统结论：高精度并没有把内核路径拖重。平均 proof 只有 541 字节，99.4% 的 proof 小于 4 KiB，平均 proof check 时间仅 48.5 微秒。单个程序的总分析时间平均为 9.0 秒，其中 79.3% 花在内核侧分析，用户态推理占 20.7%。虽然某些程序会触发很多次 refinement，但从整体看它仍然是一条罕见慢路径：平均只有不到 0.1% 的已处理指令会触发 refinement。

## 创新性与影响

BCF 的真正创新，不是单纯“把 verifier 做得更准”，而是重新安排了“精度究竟放在哪里”。它没有把更强的 abstract domain 直接嵌进 verifier，而是把 verifier 保持成一个廉价前端，只在必要时请求 proof-backed precision。这和 PREVAIL 那类重新设计 verifier 抽象域的路线不同，也和要求代码提供者为整个扩展生成完整证明的 proof-carrying-code 路线不同。BCF 里的 proof 只为局部 refinement 兜底，因此常规路径仍是熟悉的 Linux verifier，proof 体积和生产者负担也都更小。

这种设计对几个方向都有影响。对 eBPF 开发者而言，它提供了一条减少“为了 verifier 改写程序”这种扭曲工程实践的路径。对 kernel research 而言，它展示了如何在不把重量级 theorem proving 塞进内核的前提下提高 extensibility。对 formal-methods 社区而言，它给出了一个很具体的 systems case：proof search 在用户态进行，而内核里只保留一个小型 proof checker。它既是一种新机制，也是一种新的系统分工方式。

## 局限性

最大限制仍然是实现覆盖面。BCF 的 symbolic tracking 已经很好地支持了 ALU 和 branch operation，但对 stack state 的支持还不完整，尤其是小于整寄存器大小的 spill。遇到这些模式时，生成出来的 refinement condition 可能过弱，solver 只能给出 counterexample，于是安全程序仍会被拒绝。除此之外，BCF 目前也没有接入所有 verifier failure site，这解释了少数“根本没机会 refinement”的失败。

load-time 开销也不是零。如果某个程序需要非平凡的用户态推理，它的加载时间一定会比今天纯 verifier 路径更长。作者认为 proof cache 可以显著缓解这一点，因为 verifier 是确定性的，同一扩展重复加载时会请求同一批 condition；但论文没有真正实现并评估这类缓存。最后，loop-heavy 程序仍可能触发一百万指令上限，而 BCF 目前并没有解决这个更普遍的 verifier termination 问题。

## 相关工作

- _Vishwanathan et al. (CGO '22)_ - 该工作在内核内部改进 verifier 的 tristate reasoning，而 BCF 保持常规抽象域简单，只在卡住时引入 proof-backed refinement。
- _Gershuni et al. (PLDI '19)_ - PREVAIL 通过 Zone abstract domain 提升精度；BCF 则跳出“选一个更强内核抽象域”的框架，按需证明更紧的抽象即可。
- _Dwivedi et al. (SOSP '24)_ - KFlex 将 kernel-interface compliance 与 extension correctness 分开处理，但前者仍依赖 verifier；BCF 恰恰增强了这部分 verifier 能力。
- _Necula and Lee (OSDI '96)_ - 面向安全 kernel extension 的 proof-carrying code 需要为整个程序提供证明，而 BCF 只为局部 abstraction refinement 提供证明，因此 proof 更小、接入门槛也更低。

## 我的笔记

<!-- 留空；由人工补充 -->
