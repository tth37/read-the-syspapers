---
title: "Compositional AI Beyond LLMs: System Implications of Neuro-Symbolic-Probabilistic Architectures"
oneline: "把 neuro-symbolic-probabilistic AI 当作系统工作负载剖析，指出符号与概率核为何卡在现有 CPU/GPU 上，并给出调度、映射与压缩优化。"
authors:
  - "Zishen Wan"
  - "Hanchen Yang"
  - "Jiayi Qian"
  - "Ritik Raj"
  - "Joongun Park"
  - "Chenyu Wang"
  - "Arijit Raychowdhury"
  - "Tushar Krishna"
affiliations:
  - "Georgia Institute of Technology, Atlanta, GA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762235"
tags:
  - ml-systems
  - gpu
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文把 neuro-symbolic-probabilistic AI 当成一类独立的系统工作负载，而不是“LLM 外加一点胶水逻辑”。作者表明，真正拖慢端到端性能的往往是 symbolic 与 probabilistic 阶段，并据此给出覆盖调度、映射、电路优化、压缩和精度控制的优化工具箱。

## 问题背景

论文关注的核心矛盾是：算法已经从单体 LLM 走向组合式推理，但机器仍然按稠密张量工作负载来设计。AlphaGeometry、R2-Guard、BTProp、Ctrl-G、CoELA、COMBO、ReST-MCTS 这类系统把 LLM 与 symbolic solver、逻辑约束、tree search、hidden Markov model、probabilistic circuit 或 Monte Carlo 推断拼在一起，常常能换来更高准确率、更强鲁棒性和更好的数据效率。问题在于，GPU 擅长 `MatMul` 与 attention，却不擅长不规则 tree traversal、first-order logic、稀疏概率更新和多阶段控制流编排。此前缺少的正是针对这类 neuro-symbolic-probabilistic 工作负载的系统级回答：一旦推理超出单个 dense model，真正的瓶颈到底在哪里？

## 核心洞察

论文最重要的洞察是：compositional AI 的关键路径是异构的，而真正拖后腿的通常不是 neural throughput，而是 symbolic/probabilistic 行为。也正是这些让系统更可解释、更省数据的组件，引入了低 arithmetic intensity、差 cache locality、串行控制流和昂贵的 CPU-GPU 往返。只要它们落在关键路径上，端到端性能就主要受编排方式和数据移动支配，而不是受张量吞吐支配。

## 设计

这项工作的“设计”其实是一套 characterization + optimization 框架。论文先定义五种组合形式，从流水式 `LLM|Symbolic|Probabilistic` 到反复调用 LLM 的 tree-search 系统都覆盖在内。随后，作者在 H100/H200 GPU 与 Sapphire Rapids CPU 上，对七个代表性工作负载做 profiling，观察 latency breakdown、operator mix、roofline、cache、DRAM 带宽、dataflow dependency、memory trace 和多节点扩展性。结论很稳定：neural kernel 仍大体落在现有硬件的高效区，symbolic/probabilistic kernel 则主要由 element-wise 操作、稀疏状态更新、分支控制和数据搬运构成。

与这些瓶颈对应，论文提出六类优化。parallel node expansion 解决串行的 LLM orchestration；flexible LLM mapping 把简单模块路由到本地 LoRA 小模型；pipeline scheduling 用自适应 batching 让 LLM 阶段与 symbolic/probabilistic 阶段重叠；probabilistic circuit optimization 对 sum-product expression 做 factorization 和 deduplication；model compression 用量化加剪枝压缩 HMM 一类大模型；mixed-precision symbolic sampling 则降低 MCMC 式辅助模块的代价。

## 实验评估

实验首先解释了为什么这些工作负载值得优化。在 scaling study 中，compositional 系统在多个推理任务族上优于 monolithic LLM；以 AlphaGeometry 为例，作者报告它在更难的 IMO 风格题目上，相比 RL-based chain-of-thought 推理能做到 `2-3x` 更低延迟、能耗更低。这个部分有些结果来自文献汇总而不是统一 benchmark harness，但足以支撑论文动机。

更有说服力的是系统刻画本身。symbolic 与 probabilistic 阶段虽然 FLOPs 不高，却经常占据很大的 wall-clock 时间。以 BTProp 为例，它们在 H100 上分别占总 runtime 的 `29%` 与 `24%`，但只贡献 `13%` 与 `15%` 的 FLOPs。Ctrl-G 做一个 text-infilling 任务仍要 `89s`，BTProp 做一次 hallucination detection 需要 `91s`，说明单独加速 LLM 并不能解决用户感知到的时延。Roofline、cache 与带宽分析也一致表明，这些 kernel 普遍是 memory-bound 的。

优化结果很强，但明显是针对具体瓶颈逐项出手。parallel node expansion 让 ReST-MCTS 提速 `1.47x`。flexible model mapping 在 CoELA 和 BTProp 上把延迟分别降到 `3.7x` 与 `2.9x`，准确率损失低于 `1%`。pipeline scheduling 在 AlphaGeometry 和 Ctrl-G 上把吞吐提升 `2.7x` 与 `3.3x`。probabilistic circuit optimization 在 R2-Guard、BTProp、Ctrl-G 上带来 `18.8x`、`23.4x`、`20.3x` 加速。compression 让 Ctrl-G 的 HMM 缩小 `52.6x`，准确率仅降 `1%`；mixed-precision symbolic sampling 额外带来 `2.4x-3.8x` 提速，最大准确率损失只有 `0.4%`。若把适用技术组合起来，端到端延迟可下降 `50-70%`，例如 AlphaGeometry 从 `34s` 降到 `11s`，R2-Guard 从 `121s` 降到 `39s`。

## 创新性与影响

相对过去的 profiling 论文，这篇工作的创新在于给出了 compositional neuro-symbolic-probabilistic 系统的跨层视角，把 taxonomy、测量和优化建议连成了一体。相对 CogSys 这类 accelerator 论文，它提供的是“哪些 kernel 值得被硬件加速”的证据。相对 Lobster、Dolphin 这样的软件系统，它又更宽，不绑定某一种 runtime。它最重要的影响，是提醒架构师和 ML 系统研究者：symbolic/probabilistic 阶段必须被当成一等性能对象，而不是默认 LLM 会压倒一切。

## 局限性

这篇论文的主要局限也来自它的覆盖面。七个工作负载只是代表样本，不是全集，而且其中不少还是研究原型。它与 monolithic LLM 的对比部分有赖于文献结果整合，因此更像方向性证据，而不是完全受控的一对一 benchmark。优化工具箱也偏手工：每种技术都解决一个局部瓶颈，但论文没有给出一个能自动决定何时 pipeline、何时 remap、何时 compress 或 offload 的统一 runtime。多节点部分同样更偏诊断，而不是完整解法。

## 相关工作

- _Wan et al. (ISPASS '24)_ — 研究的是 neuro-symbolic AI 工作负载表征，而这篇论文把范围扩展到 neuro-symbolic-probabilistic 系统，并加入了更完整的优化工具箱。
- _Naik et al. (arXiv '24)_ — Dolphin 关注 neurosymbolic learning 的 CPU/GPU 分工；这篇论文则把 placement 问题推广到多种组合模式与工作负载类型。
- _Biberstein et al. (arXiv '25)_ — Lobster 加速的是某一类 neurosymbolic programming 栈，而这篇论文更像跨工作负载的测量与归纳研究，不是单一语言 runtime。
- _Wan et al. (HPCA '25)_ — CogSys 通过软硬件协同设计提升 neurosymbolic cognition 效率，而这篇论文提供了促成这类协同设计所需的工作负载证据与瓶颈分析。

## 我的笔记

<!-- 留空；由人工补充 -->
