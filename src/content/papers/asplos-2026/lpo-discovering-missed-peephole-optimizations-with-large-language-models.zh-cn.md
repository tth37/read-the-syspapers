---
title: "LPO: Discovering Missed Peephole Optimizations with Large Language Models"
oneline: "LPO 从 LLVM IR 中抽取小片段交给 LLM 提议重写，再用 `opt`、`llvm-mca` 和 Alive2 过滤与纠错，持续挖出遗漏的 peephole 优化。"
authors:
  - "Zhenyang Xu"
  - "Hongxu Xu"
  - "Yongqiang Tian"
  - "Xintong Zhou"
  - "Chengnian Sun"
affiliations:
  - "Cheriton School of Computer Science, University of Waterloo, Waterloo, Canada"
  - "Department of Software Systems & Cybersecurity, Monash University, Melbourne, Australia"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790184"
code_url: "https://github.com/uw-pluverse/lpo-artifact"
tags:
  - compilers
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

LPO 把“发现遗漏的 peephole 优化”做成一个闭环：从 LLVM IR 中抽取小片段，让 LLM 提议 rewrite，再用 `opt`、`llvm-mca` 和 Alive2 过滤或纠错。实验显示，这个流程比 Souper 和 Minotaur 找到更多真实的 LLVM 漏优化，其中不少后来被上游确认或修复。

## 问题背景

LLVM 的 peephole 优化不是一个统一算法，而是一大堆持续增长的局部重写规则，所以“不完整”几乎是必然结果。人工检查还能继续找到 missed case，但成本高且不扩展。differential testing 很有用，却通常只能暴露“别处已经会做”的模式。superoptimizer 则能主动搜索新 rewrite，可它的搜索成本高、支持的指令范围也常常偏窄。

这在现代 LLVM IR 上尤其麻烦，因为真实漏掉的优化经常涉及向量、内存访问、浮点和各种 intrinsic，而这些正是 Souper 一类工具最容易失效的区域。于是问题变成：怎样在很宽的 IR 空间里搜索新 rewrite，同时又不去盲信一个本来就会 hallucinate 的生成器？

## 核心洞察

论文的核心主张是，LLM 和形式化验证在这个任务上刚好互补。LLM 足够灵活，能在开放搜索空间里提出看起来合理的 rewrite；但它不可靠，可能生成非法 IR、非 canonical 代码，甚至错误变换。Alive2 之类工具则相反：它们很擅长验证或反驳候选，却不会自己发明候选。

所以，LPO 把 LLM 放在“提案者”位置，而不是“可信优化器”位置。`opt` 的错误信息、canonicalization 结果，以及 Alive2 的反例都会被反馈给下一轮 prompt。这样一来，hallucination 只是多浪费几次尝试，而不再是正确性风险。

## 设计

LPO 有三个部件：extractor、LLM optimizer 和 verifier。extractor 会在每个 basic block 里逆序遍历指令，枚举依赖闭包形式的 instruction sequence，再把每个 sequence 包装成一个独立 LLVM 函数：未定义操作数变成参数，最后一个值变成返回值。之后有两个关键过滤步骤。第一，若这个包装后的函数单独拿出来还能被 `opt -O3` 继续优化，LPO 就直接丢掉，因为它不算真正的 missed case。第二，LPO 会按 opcode 和操作数结构做哈希去重。

对每个剩余序列，LLM 负责提出替代函数。LPO 先用 `opt` 做语法检查和 canonicalization，再做 interestingness check：若候选能减少指令数、降低指定 target/CPU 上的 `llvm-mca` 总周期，或者虽然成本相同但换了语法形态并可能解锁后续优化，就保留下来继续看。论文明确说这只是一个启发式分流步骤。

若候选仍然值得继续验证，Alive2 就检查原函数是否被新函数 refinement。若失败，LPO 把反例反馈给 LLM，再试一次；原型里 ATTEMPT_LIMIT 是 `2`。整个系统最重要的不变量很直接：LLM 可以乱提，但只有通过 LLVM 工具链和 Alive2 检验的候选才会被保留。

## 实验评估

实验首先在 `25` 个公开的 LLVM missed-optimization issue 上做受控评测，这些 issue 都创建于 2024 年 8 月之后，以尽量降低训练数据泄漏风险。LPO 的效果很依赖模型能力：Gemma3 最多只能抓到 `3/25`，而 Gemini2.0T 能抓到 `21/25`，`o4-mini` 能抓到 `18/25`。对比之下，Souper 即便开启枚举合成，总共也只发现 `15/25`，Minotaur 只有 `3/25`。论文给出的解释很合理：LPO 的优势主要来自覆盖范围更宽、搜索更灵活。

更重要的是长期搜索结果。作者在十五个真实项目的优化后 IR 上跑了十一个月的间歇实验，去重后搜索了大约 `800,000` 个唯一 instruction sequence，最终向 LLVM 报告了 `62` 个 missed peephole optimization，其中 `28` 个被确认，`13` 个已经修复。论文还显示，一些已修复模式在真实代码里出现得相当广，有的会影响到上千个 IR 文件。

但这篇论文对“收益”讲得非常克制。吞吐是可接受的：在 `5,000` 个抽样 case 上，Gemini2.5 API 平均每个 case `6.7` 秒，总成本约 `$5.4`；本地 Llama3.3 则是 `26.2` 秒。已接收 patch 的 compile-time 影响几乎可以忽略，不过 SPEC CPU2017 的运行时变化大多都在 `2%` 以内。所以这篇论文更像是在证明“这是一种持续维护 LLVM 长尾漏优化的可行工具”，而不是“单个 patch 会带来惊人的端到端加速”。

## 创新性与影响

LPO 的新意不在于更强的 verifier，也不在于更强的 superoptimizer，而在于工作流本身：让 LLM 探索更宽的 rewrite 空间，再用 `opt`、成本筛选和 Alive2 把可信性补回来。它更像是给 compiler maintainer 的工具，而不是给终端用户直接追某个 benchmark 数字的武器。对成熟编译器来说，这种“持续挖长尾漏优化”的思路很有现实意义。

## 局限性

LPO 的上限受整个闭环共同约束。只要 IR 特性超出 Alive2 或 `opt` 的支持范围，覆盖面就会被直接卡住；论文甚至报告了一个 Alive2 bug。interestingness check 也是启发式且 target-specific 的，因为 `llvm-mca` 只在某个指定 CPU 模型上评估周期。长期搜索之后，人仍然要做大量整理工作，因为模式泛化和真正提交到 LLVM 的工程实现依然是手工完成。最后，已接收 patch 在 SPEC CPU2017 上几乎都没有超出噪声级别的收益，所以“发现有效局部 rewrite”并不等于“证明有显著端到端性能提升”。

## 相关工作

- _Bansal and Aiken (ASPLOS '06)_ — 经典 peephole superoptimization 直接搜索最优 rewrite，而 LPO 把候选生成交给 LLM，再用验证去恢复可靠性。
- _Lopes et al. (PLDI '21)_ — Alive2 提供了 LPO 闭环里最关键的 translation validation 底座，使得系统可以安全地消费 LLM 生成的候选。
- _Liu et al. (OOPSLA '24)_ — Minotaur 把 LLVM superoptimization 扩展到更多 SIMD 整数与浮点代码，而 LPO 试图通过摆脱纯合成搜索来覆盖更宽的模式空间。
- _Theodoridis et al. (ASPLOS '22)_ — differential testing 可以通过语义差异暴露 missed optimization，而 LPO 直接从 IR 片段出发尝试发明新的有利 rewrite。

## 我的笔记

<!-- empty; left for the human reader -->
