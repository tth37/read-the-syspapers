---
title: "DeltaZip: Efficient Serving of Multiple Full-Model-Tuned LLMs"
oneline: "DeltaZip 把 full-model tuning 产生的 model delta 压成稀疏低比特更新，并把 base model 与 delta 分开执行，让共享底座的长尾 LLM 变体也能高效合批服务。"
authors:
  - "Xiaozhe Yao"
  - "Qinghao Hu"
  - "Ana Klimovic"
affiliations:
  - "ETH Zurich"
  - "MIT"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717468"
code_url: "https://github.com/eth-easl/deltazip"
tags:
  - llm-inference
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DeltaZip 把 full-model-tuned variant 看成 base model 加一份压缩后的 delta。它把 base 路径与 delta 路径分开执行，让共享底座的不同变体还能一起 batching。论文报告相对整模型换入换出基线，吞吐提升 2x-12x，同时质量接近 FP16。

## 问题背景

论文讨论的是托管平台里的长尾问题。很多 fine-tuned variants 共享同一个 base model，但调用模式既突发又偏斜。给每个变体单独配 GPU 会让利用率很差；在较小 GPU 池里换入换出整模型，请求又会把时间花在 model load 上，而且每个变体都很难攒出像样的 batch。

现有多租户方案主要服务 LoRA 这类 PEFT。可作者认为更难的 code、math 任务上，FMT 仍然有精度优势，所以平台真正缺的是一条面向 FMT 的 serving 路径。

## 核心洞察

核心洞察有两层。第一，FMT 虽然更新了全部参数，但相对 base model 的 delta 往往幅度更小、近零值更多，所以比整模型更适合做 aggressive compression。第二，只要运行时把 `W_base X` 与 `ΔX` 分开算，共享同一底座的不同变体就还能走同一条 base-model 执行路径。

难点在压缩校准。作者指出，每层都必须把压缩后的 delta 加回 base weight，再生成下一层输入；如果直接拿纯 delta 往后传，深层 activation 会衰减，后续层的压缩决策就会失真。

## 设计

系统分成离线的 ΔCompress 和在线 serving。ΔCompress 先做 delta extraction，再施加 2:4 structured pruning、2-bit 或 4-bit quantization，必要时再做 lossless compression。2:4 的选择是硬件导向的，因为它直接对应 GPU 的稀疏矩阵加速。压缩过程按层进行，每层都会在校准后重建 `W_base + Q ⊙ M`；论文说 256 条 calibration samples 已经够用，而压一个 7B 模型大约需要 30 分钟。

在线时，base model 常驻 GPU，compressed deltas 在磁盘、CPU 内存和 GPU 内存之间分层放置。每个 linear layer 都拆成共享的 FP16 base GEMM 与稀疏低精度 delta matmul，再在 nonlinearity 前合并结果；tensor parallelism 也同步扩展到 delta。

真正支撑吞吐的是 SBMM。调度器先按 delta 聚合请求，减少随机访存，再用一个 kernel 处理多个 deltas，而不是反复发很多小 kernel。连续批处理每次只允许最多 `N` 个驻留 GPU 的 deltas 参与，并用一个简单的 preemption 规则避免热门 delta 长期插队。

## 实验评估

实验要点有两个。第一，压 delta 比压整模型更稳。Llama 13B 上，DeltaZip 的 2-bit 加 50% structured sparsity 达到 11.83x compression，而 BoolQ/TruthfulQA/LogiQA 仍是 84.95/42.54/27.65，对比 FP16 的 85.29/43.00/27.04 只差很小。Llama 70B 上，同样配置达到 13.96x compression；而把 SparseGPT 风格压缩直接用在完整权重上，掉点明显更大。

第二，shared-base batching 确实改善了 long-tail serving。论文在 4 路 tensor parallel 的 A800 集群上，用 32 个 model variants 和 LMSys 风格 traces 评估，相对整模型换入换出的 vLLM-SCB，DeltaZip 把吞吐提高 2x-12x，把平均端到端延迟降低 1.6x-16x，TTFT 改善更大。收益在偏斜分布下最明显；若负载很高且模型热度接近均匀，瓶颈会重新落到 prompt processing 上。作者还用 Llama-7B GSM8K 说明 compressed FMT 的意义：FMT 为 34.79，LoRA 为 29.49，DeltaZip 压缩后的 FMT 仍有 34.95。

## 创新性与影响

这篇论文的新意在于把 compression 与 runtime 一起围绕 FMT delta 重做。Punica、S-LoRA 解决的是 adapter serving，SparseGPT、AWQ 解决的是整模型压缩；DeltaZip 则把目标换成 FMT delta，并且避免在请求路径上回拼完整 checkpoint。这样一来，full-parameter tuning 第一次在系统层面变得接近 adapters 一样可交换、可合批。

## 局限性

它的边界也很清楚。若变体数量不多，而且都能直接放进 GPU，保留完整 checkpoint 可能更快；DeltaZip 也没有减少 prefill 成本，所以高负载、均匀热门的场景仍会被 prompt processing 卡住。调度器为了 batching 会重排请求，因此缺少严格的单模型 SLO 保证；LoRA 与 FMT 也还不能同批混跑。

## 相关工作

- _Chen et al. (MLSys '24)_ - Punica 证明了共享 base model 的 LoRA 多租户 serving 很有效，而 DeltaZip 把这条思路扩展到了 full-model-tuned variants。
- _Sheng et al. (arXiv '23)_ - S-LoRA 关注的是大规模 adapter serving 与统一分页管理，但默认对象仍是 PEFT adapter，不是压缩后的 FMT delta。
- _Frantar and Alistarh (arXiv '23)_ - SparseGPT 直接压整模型权重；DeltaZip 则改为压 delta，并在校准时逐层重建权重来避免显著质量损失。
- _Fu et al. (arXiv '24)_ - ServerlessLLM 主要把模型当作黑盒来优化加载与迁移，而 DeltaZip 进一步利用不同变体共享同一 base 这一 lineage 信息来实现跨变体 batching。

## 我的笔记

<!-- 留空；由人工补充 -->
