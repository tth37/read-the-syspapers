---
title: "eBPF Misbehavior Detection: Fuzzing with a Specification-Based Oracle"
oneline: "Veritas 用 Dafny 规格 oracle 直接比对 Linux eBPF verifier 的语义结果，从而同时抓到误放行的不安全程序和被误拒的安全程序。"
authors:
  - "Tao Lyu"
  - "Kumar Kartikeya Dwivedi"
  - "Thomas Bourgeat"
  - "Mathias Payer"
  - "Meng Xu"
  - "Sanidhya Kashyap"
affiliations:
  - "EPFL"
  - "University of Waterloo"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764797"
code_url: "https://github.com/rs3lab/veritas"
tags:
  - ebpf
  - kernel
  - security
  - fuzzing
  - formal-methods
category: verification-and-reliability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Veritas 把 generator 与 SpecCheck 结合起来；SpecCheck 用 Dafny 建模 eBPF 指令语义和安全性质，并把任何与 Linux verifier 的分歧都视为 bug。这样一来，它既能抓到不安全程序被误放行，也能抓到安全程序被误拒绝；作者最终报告了 13 个核心 verifier 语义差错和 15 个总 bug。

## 问题背景

Linux eBPF verifier 是进入 kernel 执行前的最后一道门槛，因此 verifier bug 会同时造成可用性和安全性问题。把安全程序拒掉，会让开发者浪费大量时间理解 verifier 的隐含规则；把不安全程序放进去，则可能导致信息泄漏、kernel hang，甚至 privilege escalation。论文强调，这两类问题都已经很现实，因为 eBPF 已被广泛用于 tracing、networking 和 policy enforcement。

现有方法各自遗漏了一块。形式化验证大多只覆盖局部组件，例如 range analysis；alternative verifier 如 Prevail 语义更整洁，但要持续跟上生产实现并不容易。已有 fuzzing 工作虽然能很好地探索路径，但 oracle 通常依赖 KASAN、UBSAN 或运行时状态差异，所以主要擅长抓执行后才显形的 bug，不擅长解释 verifier 自身的语义错误，更难发现“安全程序被误拒绝”。作者把这些漏网问题归纳为四类根因：抽象不精确（RC1）、安全规则不一致（RC2）、实现错误（RC3）和优化逻辑出错（RC4）。

## 核心洞察

核心洞察是把“这段具体 eBPF 程序到底安不安全”直接写成 SMT 可判定的约束，而不是等运行后再看有没有 crash。为此，SpecCheck 直接建模 eBPF VM 的动态类型，包括未初始化值、scalar、非空指针、可空指针、region 身份和 offset，而不是复用 verifier 自己的近似抽象。

另一半工作是把 verifier 想保证的安全边界显式写出来。论文总结出五个性质：control-flow safety、memory safety、resource safety、VM integrity 和 data safety。只要这些规则按指令编码完成，Linux verifier 与规格的分歧就会变得有信息量：它要么误放行了不安全程序，要么错杀了安全程序，要么连 culprit instruction 都判断错了。

## 设计

SpecCheck 先构造一个 eBPF VM 语义层：寄存器和内存槽中的值可能是 `Uninit`、`Scalar`、`PtrType` 或 `PtrOrNullType`，而 stack、context、packet、map 等 memory region 被分开建模。alignment 和 field boundary 也被纳入规则，因此部分 pointer load/store 会被直接识别为语义违规，而不是含糊地留给实现细节处理。这一点很重要，因为不少 verifier bug 就藏在 stack layout、pointer typing 和粗粒度抽象之间的缝隙里。

在其上，作者按 confidentiality、integrity 和 availability 的目标定义安全规格。control-flow safety 要求有限步内显式退出；memory safety 约束非空、越界和权限，并跟踪分配状态；resource safety 要求退出前释放内存和锁；VM integrity 禁止写 `r10`；data safety 则阻止未初始化数据读取、pointer 经由 map/helper 泄露，以及 pointer 被静默转换成可公开 scalar。

编码方式也刻意保持模块化。每条指令对应一个 Dafny 纯函数，precondition 表示安全规则，函数体计算新的 immutable VM state。Veritas 再把生成出的 eBPF 程序 shallow-embed 成 Dafny，交给 Dafny 和 Z3 检查，并与真实 verifier 的结果比较。为了让 solver 可承受，系统偏向生成小程序，在 patch 过的 kernel 中采样 verifier state 以便从靠近 culprit instruction 的状态开始检查，并把 oracle 检查异步并行化。

## 实验评估

实验基本支持了论文的中心论点：精确的 specification oracle 确实能把 bug 覆盖面扩展到传统 runtime-oriented oracle 很难碰到的区域。作者在三个月内共找到 15 个 bug，其中 13 个是本文真正关心的 verifier 语义差错：3 个不安全程序被接受、9 个安全程序被拒绝，以及 1 个对 local memory 使用 atomic operation 却被错误放行的案例。到写作时，12 个报告被确认，8 个被修复；另外两个计入总数的 bug 则是 verifier 自身的 KASAN / UBSAN 问题。

这些发现既包括 privilege escalation、kernel pointer 泄露这类严重安全问题，也包括让开发者花数小时调试的 usability 问题。出错的 culprit instruction 横跨 arithmetic、data movement、memory operation 和 control flow，说明这个规格并不局限于单一局部组件。

与已有工作的对比尤其有力。SpecCheck 复现了此前 fuzzers 报告的 14 个 verifier bug。反过来，即便把精确的 proof-of-concept 直接交给现有开源 fuzzers，它们仍然抓不到 Veritas 的新 bug，因为原有 oracle 依赖运行时症状。性能则足够支持 testing-time 使用：在 224-core 服务器上，Veritas 达到每秒 23 到 25 个测试，平均每个样例约 10 秒，timeout 约 0.2%；通过采样 verifier state，在 40 小时实验中又节省了 754 CPU-core hours。32% 的 branch coverage 对 crash fuzzing 也许不算高，但对 semantic mismatch oracle 已经足够有效。

## 创新性与影响

这篇论文真正新的地方，在于把 verifier 的预期语义和安全政策都写成可执行规格，再把这份规格当作生产 verifier 的外部 oracle。于是 Veritas 获得了多数 eBPF fuzzers 过去没有的能力：系统性发现 safe reject 和 policy inconsistency，而不只是等待 unsafe accept 在运行后出错。对 maintainer 来说，这是一种实用的回归守卫；对研究者来说，它也是一份未来可继续复用的规格资产。

## 局限性

覆盖面是最明显的限制。SpecCheck 虽然建模了 RFC 中全部 171 个 ISA opcode，但 455 个 helper / kernel function 里只覆盖了最常用的 50 个，因此通过 helper 触达的未建模内存行为明确不在范围内。系统还依赖 bounded loop unrolling，默认很多关键 bug 都能由小程序触发，并接受少量 SMT timeout 来换取整体吞吐。

此外，想高效检查还需要一个带 verifier-state sampling patch 的 kernel。JIT bug、helper 实现 bug，以及 speculative-execution mitigation 本身，也都不是这篇论文打算解决的问题。

## 相关工作

- _Gershuni et al. (PLDI '19)_ — Prevail 试图用更干净的 abstract-interpretation 基础重建 eBPF 安全检查；Veritas 则保持生产 verifier 不变，只把规格放在外部充当 oracle。
- _Vishwanathan et al. (CAV '23)_ — Agni 验证的是 verifier 的 range-analysis 组件；本文则通过完整的指令语义和安全约束规格，把测试覆盖面扩展到更广的 bug 类型。
- _Sun and Su (OSDI '24)_ — SEV 通过 state embedding 验证 eBPF verifier，但它仍偏向运行时证据，天然不擅长解释或发现那些被 verifier 误拒绝的安全程序。
- _Sun et al. (EuroSys '24)_ — structured and sanitized-program fuzzing 改进了 eBPF verifier 测试，但其 oracle 仍依赖运行时表现；Veritas 则能在程序真正执行前就标记静默的语义不一致。

## 我的笔记

<!-- 留空；由人工补充 -->
