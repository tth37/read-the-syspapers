---
title: "Highly Automated Verification of Security Properties for Unmodified System Software"
oneline: "Spoq2 把未修改系统软件的安全验证拆成许多小型 SMT 检查，并用影响锥剪枝与指针抽象压低证明复杂度。"
authors:
  - "Ganxiang Yang"
  - "Wei Qiang"
  - "Yi Rong"
  - "Xuheng Li"
  - "Fanqi Yu"
  - "Jason Nieh"
  - "Ronghui Gu"
affiliations:
  - "Columbia University, New York, NY, USA"
  - "CertiK, New York, NY, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790171"
code_url: "https://github.com/VeriGu/spoq3"
tags:
  - verification
  - formal-methods
  - security
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Spoq2 是一个面向未修改内核、固件和 hypervisor 的安全验证框架，目标是在不再手写大段 Coq 安全证明的前提下，自动证明 confidentiality、integrity 和 noninterference 一类性质。它的关键做法是把安全证明拆成过渡级别的归纳检查，再用 per-transition cone-of-influence、pointer abstraction 和 Z3 cache 把每个检查压缩到 SMT 求解器能承受的规模。

## 问题背景

这篇论文瞄准的是系统验证里一个长期存在但一直很难真正落地的问题：我们并不缺少“如何形式化表达安全性质”的理论，但缺少一种能直接作用在真实发布版系统代码上的低成本证明流程。真实 system software 同时包含 C、汇编、复杂指针、并发、硬件状态和大量条件分支。只要把这些因素放进同一个证明里，不管是人工 Coq 推理还是自动 SMT 求解，复杂度都会迅速失控。

作者把现有方法分成两个都不太理想的方向。第一类是高保证但高度人工的方法，可以证明很强的 confidentiality 或 integrity 性质，但代价往往是几千行证明脚本和长期的专家投入。第二类是更自动的框架，比如 Serval，能减轻证明负担，却难以处理 released system software 里常见的 overloaded pointers、page-table entries 和并发执行。于是，即便目标性质本身并不抽象，例如“Realm 的私有状态永不泄露”，验证仍会卡在 path explosion 和 solver explosion 上。

因此，这篇论文的问题定义很明确：不要先把系统改写成 verification-friendly 的版本，而是直接验证 unmodified code，并把证明改造成一批足够小、足够局部、足够可判定的义务，让 SMT 求解器能真正跑完。

## 核心洞察

论文最重要的洞察是：很多系统安全性质都可以化约成 transition system 上的归纳不变量，而且自动化真正成立的前提不是“更强的求解器”，而是“把证明局部化到单个 transition”。Spoq2 不直接对整段执行证明 relational security theorem，而是先证明某个 invariant 在初始态成立，并被每个 atomic transition 保持；若是 information-flow 性质，则在 composed system 里对两次执行的 transition 对做同样的检查。

一旦证明目标变成“这个 transition 是否保持这个 invariant”，很多原本太粗的优化就突然有效了。Spoq2 可以只针对这一条 transition 计算 cone of influence，删去和目标性质无关的状态字段，提前剪掉不可能成立的 path pair，并去掉那些已经被依赖分析保证成立的关系子句。与此同时，pointer abstraction 把 page-table entry 这类位级操作密集的结构重写成带 `id`、`ofs`、`valid` 等属性的记录，让 Z3 更多使用线性整数算术，而不是沉重的 bit-vector 推理。真正值得记住的是：Spoq2 把 relational security proof 变成了许多已经被裁剪过的小型 checks。

## 设计

Spoq2 的工作流分成六步。它先用 Clang 把未修改的 C 编译到 LLVM IR，再接收用户提供的 machine configuration 来定义抽象机器状态，随后把 LLVM IR 和支持的汇编翻译成 Coq representation，并通过已经证明正确的 transformation rules 化简成自包含的 transition functions。用户仍要用 Coq 写出目标安全性质；如果有循环，还需要提供 loop invariant 和 ranking function。Spoq2 会先用 Z3 检查这些循环条件，然后为初始态和各条 transition 路径自动生成 proof goals。

真正决定可扩展性的，是 per-transition cone-of-influence 分析。给定一个性质，Spoq2 只在当前 transition 范围内计算哪些变量真的可能影响它，然后删除无关状态更新，简化 Coq representation，并在 relational proof 中去掉无需显式检查的关系子句。这比传统 whole-system COI 有效得多，因为后者常常会把大半个机器状态都保留下来。

第二个核心机制是 pointer abstraction。用户只需要为关键的 overloaded pointer 写轻量配置，描述 bit layout、使用位置和必要的 memory layout 假设。Spoq2 随后把常见指针模式映射成结构化属性和抽象操作，让 page-table entry 暴露 `addr`、`valid` 之类的字段，而不是把 mask 和 shift 全都丢给 Z3 做 bit-vector 推理。最后，系统还缓存 Z3 表达式和整条查询结果，避免重复求解相同的 symbolic conditions。

## 实验评估

这篇论文的实验最有说服力的一点，是它没有用为了工具量身定制的小 benchmark，而是直接验证 release 版、未修改的系统代码。作者选择了四个目标：Arm CCA 的 TF-RMM v0.3.0（`5.5K` LoC）、TF-A v2.13 的 EL3 runtime firmware（`10.0K` LoC）、Linux 6.1 上的 SeKVM（`4.0K` LoC），以及 Komodo（`1.5K` LoC）。在这些代码上，Spoq2 证明了 Realm confidentiality / integrity、VM confidentiality / integrity，以及 enclave noninterference 等性质。

最重要的结果同时覆盖人工成本和运行时间。相对已有基线，Spoq2 把 RMM 的人工工作量降低了 `80%`，把 SeKVM 的人工工作量降低了 `78%`；而此前从未被验证过的 TF-A，总手工输入也只有 `1.6K` 行。端到端运行时间方面，RMM 为 `255` 分钟，TF-A 为 `83` 分钟，SeKVM 为 `48` 分钟，Komodo 只要 `40` 秒。更关键的是，工具确实抓到了真实 bug：作者在 Linux 6.1 版 SeKVM 里发现了两个此前未知的问题，一个是 vCPU identifier 使用不一致，另一个是 `GRANT` hypercall 缺失 page-table lock 获取。

Ablation study 也很好地支撑了论文的技术论点。启用全部优化后，Spoq2 在 RMM、TF-A、SeKVM、Komodo 上分别减少了 `73%`、`85%`、`82%`、`92%` 的 proof goals，并把端到端时间分别压低 `71%`、`86%`、`77%`、`97%`。而且不同系统最受益的优化并不一样：RMM 更吃 state simplification，TF-A 更依赖 path pruning，Komodo 则最受益于 Z3 caching。这组结果足以支持论文的核心主张，不过离“完全自动、安全验证通用解法”还有距离，因为框架仍要求用户提供 invariants 与配置。

## 创新性与影响

和 _Li et al. (OSDI '23)_ 相比，Spoq2 的新意不在 LLVM-to-Coq translator 本身，而在于把那条面向 functional verification 的基础设施转成了 automated security proof 的工作流。和 _Nelson et al. (SOSP '19)_ 相比，论文最重要的一步是补上 pointer-heavy、concurrent system code 这一现实门槛，使得 TF-A 和 SeKVM 这样的目标首次进入自动化验证射程。和 _Li et al. (OSDI '22)_ 这类手工密集的 confidential-computing 验证相比，Spoq2 的意义在于把“只有专家团队能做一次”的证明，推进到“代码持续演化时也能重复做”。

## 局限性

Spoq2 是 highly automated，而不是 fully automatic。用户仍需要给出 security property、machine configuration、pointer configuration、loop invariant 和 ranking function，而论文也明确承认，定义安全性质对应的 inductive invariants 仍是最费脑力的部分。它的覆盖范围也有限：denial-of-service 这类 availability property 通常无法化约成 inductive invariants，因此不在适用范围内；当前实现的 assembly-to-Coq translator 也只支持 ARMv8 汇编。系统的 soundness 还信任用户配置、translator、proof checker 和 Z3。

另外，论文验证的四个系统虽然都很实在，但仍集中在安全监控器、固件和 hypervisor。若遇到当前 pointer abstraction 没覆盖的新指针习惯用法，或者更复杂的并发模式，用户依然需要补充新的配置甚至新的抽象规则。

## 相关工作

- _Li et al. (OSDI '23)_ — Spoq 解决的是真实 C 系统代码的 LLVM-to-Coq 翻译与功能正确性验证扩展性问题，而 Spoq2 在这条基础线上进一步自动化了安全性质证明。
- _Nelson et al. (SOSP '19)_ — Serval 证明了符号化方法可以自动验证系统安全性质，但 Spoq2 面向的是 Serval 难以直接处理的、带复杂指针和并发的未修改系统软件。
- _Li et al. (OSDI '22)_ — VIA 手工验证了 Arm CCA 与早期 RMM 原型，Spoq2 则把相近的安全目标推进到了发布版 TF-RMM，并显著压低人工证明成本。
- _Lattuada et al. (SOSP '24)_ — Verus 为 Rust 系统程序提供了实用的验证基础，而 Spoq2 的重点是现有 C 和汇编系统软件上的低层安全推理。

## 我的笔记

<!-- 留空；由人工补充 -->
