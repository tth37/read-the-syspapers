---
title: "Mugi: Value Level Parallelism For Efficient LLMs"
oneline: "Mugi 把 value-level parallelism 从 GEMM 扩展到 nonlinear 与 BF16-INT4 小批量 LLM 推理，让同一阵列覆盖完整执行路径。"
authors:
  - "Daniel Price"
  - "Prabhu Vellaisamy"
  - "John P. Shen"
  - "Di Wu"
affiliations:
  - "University of Central Florida, Department of ECE, Orlando, FL, USA"
  - "Carnegie Mellon University, Department of ECE, Pittsburgh, PA, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790189"
tags:
  - llm-inference
  - hardware
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Mugi 的核心主张是，value-level parallelism (VLP) 不该只用于低精度 GEMM。论文把 VLP 推广到 softmax、SiLU、GELU 等 nonlinear 操作，并针对 BF16-INT4、小批量、带 GQA 的 LLM 推理重新设计 GEMM 映射，使同一套阵列就能覆盖完整推理路径。结果是 nonlinear 部分获得极大提速，端到端 LLM 也拿到稳定收益，同时降低 operational carbon 和 embodied carbon。

## 问题背景

Carat 这一类早期 VLP 工作面向的是比 LLM 简单得多的场景：大批量、对称低精度的 GEMM。现代 transformer 推理则至少有四个不同点。第一，运行时间不只花在 GEMM 上，softmax、SiLU、GELU 这些 nonlinear 操作如果不优化，开销并不小。第二，LLM 推理越来越依赖非对称量化，例如 BF16 activation 配 INT4 weight，或者 BF16 配 INT4 KV cache，而先前 VLP 设计更偏向 FP8-FP8 这类对称格式。第三，在线推理为了控制延迟往往采用小 batch，这与依赖大 batch 才能把复用收益摊开的架构天然冲突。第四，很多 AI 加速器会给 nonlinear 和 GEMM 分别配独立硬件，这会推高芯片面积，也就推高制造阶段的 embodied carbon。

一个自然但并不理想的做法，是继续沿用传统 GEMM 加速器，同时给 nonlinear 单独加 Taylor-series 或 piecewise-linear 近似单元。论文的问题意识在于，这种拆分同时错过了两类复用机会：一类是 nonlinear 仍被当成旁路问题，另一类是 GEMM 部分与 LLM 实际采用的量化格式和 batching 形态不匹配。因此，这篇论文真正要解决的不是“某个 kernel 如何更快”，而是“能否设计一套面向完整 LLM 推理路径的统一高效架构”。

## 核心洞察

论文最重要的洞察是：只要把输入拆成合适的字段，并把查表过程重写成可共享的时间过程，VLP 就可以从乘法推广到函数近似。对 nonlinear 函数来说，Mugi 把浮点输入拆成 sign、mantissa 和 exponent，不再像常见近似硬件那样对输出做近似，而是先对输入做近似，再通过两次 temporal subscription 取回最终查表结果。这样一来，精度预算就可以优先投到真正重要的值域，而不是平均撒在整个输入空间上。

另一半洞察落在 GEMM。只要把映射方向翻转，LLM 常见的非对称 BF16-INT4 GEMM 也能变得适合 VLP：INT4 的 weight 或 KV value 放到行上，BF16 的 activation 或 query token 放到列上。这样既能贴合 batch size 8，也能贴合 grouped-query attention (GQA) 的 group size 8。把这两个洞察拼起来，论文才有资格声称它优化的是“完整 LLM 推理路径”，而不是只优化其中一个局部算子。

## 设计

在 nonlinear 路径上，Mugi 把一次查表重写成四个阶段：input-field split、value reuse、mantissa temporal subscription，以及 exponent temporal subscription。系统先把输入 mantissa 近似到更小表示，然后读取一整行共享同一 sign-mantissa 模式的预计算结果，最后用时间脉冲把正确元素“订阅”出来。整体延迟等于 mantissa 与 exponent 两次 subscription 的时间和。对 softmax 来说，Mugi 先用这套流程计算 `exp`，同时把所有 `exp` 结果累加到 output accumulator，再把总和写回，最后用一个小 vector 单元把每个 `exp` 乘上倒数。

它在精度上的关键技巧是 value-centric approximation。作者先 profile softmax、SiLU、GELU 的 exponent 分布，发现真正重要的值往往集中在远小于完整可表示空间的一段范围内。于是 Mugi 只为这些重要 exponent 保留一个可滑动的 LUT window，而不是均匀覆盖全空间。与此同时，它还会激进地缩减 mantissa，例如示例中把 mantissa magnitude 近似到 3 bit，因为作者观察到输入近似带来的误差分布相对均匀，但 temporal signal 长度却能明显缩短。这个设计追求的不是“全域最精确”，而是“在工作负载最常出现、也最影响结果的区域最精确”。

在 GEMM 路径上，Mugi 相对 Carat 做了两件很务实的事。第一是 format customization：行上承载 INT4 weight 或量化 KV cache，列上承载 BF16 activation 或 query token。这样才能和 weight-only quantization (WOQ)、KV-cache quantization (KVQ)、以及 GQA 的实际使用方式对齐，而不是强迫 BF16 值走最不合适的 temporally encoded 维度。第二是 buffer minimization。通过 broadcasting 和论文所谓的 output-buffer leaning，Mugi 把此前 VLP 设计里非常重的 FIFO 成本压缩了 `4.5x`。

从整体结构看，Mugi 把 `M-proc`、`E-proc`、作为 LUT 的 `iSRAM`、temporal converter、processing element、post-processing block、output accumulator、以及 vector unit 组合进同一套体系。nonlinear 和 GEMM 共享主要阵列资源，扩展到多节点时再用 2D mesh NoC 做 output-stationary 数据流和跨节点累加。整篇论文最重要的不变量，其实就是这件事：nonlinear 不是外挂单元，GEMM 也不是单独优化的孤岛。

## 实验评估

实验同时覆盖 workload-level accuracy 和 architecture-level performance。工作负载侧，作者 profile 了 Llama 2 `7B/13B/70B`、Whisper Tiny/Large、SwinV2 Tiny/Large 与 ViViT，并基于 HuggingFace 实现对每个模型跑 100 次推理。硬件侧，作者在 `45nm`、`400 MHz`、`256 GB/s` HBM 带宽下做体系结构模拟，对基础模块进行了综合，并对单个 8x8 Mugi 节点做了 place-and-route。这个设置足以检验论文的中心论点，也就是同一架构能否同时覆盖 nonlinear 和 LLM GEMM；但绝对 carbon 数字更应被视为模型化结果，而不是 silicon 实测，这是我根据方法学做出的推断。

nonlinear 部分的结果很强。论文显示，Mugi 在大多数模型上的端到端 perplexity 或 loss 都能追平甚至超过 Taylor-series、piecewise-linear、partial approximation 等基线，Llama 2 是主要例外，因为它不同 layer 的 softmax 分布差异更大，需要额外做 per-layer tuning。性能数字则更亮眼：nonlinear 操作最高可获得 `45x` 吞吐和 `667.85x` 能效提升；仅看 softmax 的 iso-area 对比，Mugi 相对 precise vector array 也有 `45x` 吞吐和 `481.07x` 能效提升。对论文的 value-centric approximation 主张来说，这组结果是相当有说服力的。

端到端 LLM 推理的收益没有 nonlinear 那么夸张，但更重要。在 Llama 2 70B with GQA、batch size `8`、sequence length `4096` 的单节点比较里，`Mugi (256)` 相对 16-high systolic baseline 的吞吐、能效、功效比分别提升 `2.07x`、`3.11x` 和 `1.50x`；同时 operational carbon 与 embodied carbon 分别下降 `1.45x` 与 `1.48x`。多节点 NoC 结果保持了相同的定性趋势。一个值得注意的细节是，Table 3 里 Mugi 与 Carat 的端到端吞吐几乎打平，但 Mugi 的能效明显更高。这恰好说明论文真正的贡献不是“把 GEMM 再压榨快一点”，而是把 nonlinear 也纳入同一复用底座，并让整体架构更贴合 LLM 推理的工作形态。

## 创新性与影响

和 _Pan et al. (ASPLOS '24)_ 相比，Mugi 的新意并不只是“又一个 VLP accelerator”。它把 VLP 从 multiplier-free GEMM 推广到了 nonlinear approximation，并且为非对称 BF16-INT4、小 batch、带 GQA 的 LLM 推理重新设计了 GEMM 映射。和传统 Taylor 或 PWL nonlinear 单元相比，它的创新也不只是某个近似公式更好，而是把 nonlinear 工作真正折叠回主阵列共享的数据复用框架中。

因此，这篇论文会同时吸引两类读者。对 accelerator architect 来说，它提供了一个很具体的论据：面向 AI 工作负载做算术复用时，应该围绕 value distribution 设计，而不只是围绕算子表面形式设计。对 LLM 系统研究者来说，它也提醒我们，量化格式、KV cache 表示、以及 GQA 并不只是软件优化选项，它们会反过来决定什么样的硬件映射才合理。

## 局限性

论文对局限性写得比较直接。Mugi 还不能完整覆盖所有 LLM 操作：layer normalization 需要交给 vector unit，rotary positional embedding (RoPE) 则要么单独近似，要么继续外包给外部硬件。作者还认为该设计应能推广到 mixture-of-experts 和 multimodal 模型，但论文没有给出直接验证。

另一个限制是它依赖离线构建 LUT，并依赖事先 profile 到的值分布。sliding-window 机制确实能缓解 workload drift，论文也指出 KV cache 和 FFN 的量化值通常足够稳定，但系统并没有提供在线重调 LUT 内容的机制。一个偏 reviewer 视角的担忧是，carbon 结论会受到 `45nm` 建模前提影响，因此更适合作为方向性比较而非绝对部署数字；这同样是我基于实验设置做出的推断，不是论文原文直接声称的内容。

## 相关工作

- _Pan et al. (ASPLOS '24)_ — Carat 首次把 VLP 用到 multiplier-free GEMM，而 Mugi 把这条路线扩展到了 nonlinear approximation 和面向 LLM 的非对称 GEMM。
- _Wu et al. (ISLPED '21)_ — UNO 用专门的近似硬件统一 nonlinear 操作；Mugi 则把 nonlinear 与 GEMM 一起放进共享的 VLP 主阵列。
- _Zhao et al. (ISCA '24)_ — ALISA 通过 sparsity-aware KV caching 加速 LLM 推理，而 Mugi 更强调一种兼容 KVQ 与 GQA 的通用执行底座。
- _Qin et al. (ISCA '25)_ — MECLA 通过 memory-compute co-optimization 和 sub-matrix partition 改善 LLM accelerator；Mugi 的杠杆点则是 value reuse 与 nonlinear/GEMM 硬件共享。

## 我的笔记

<!-- empty; left for the human reader -->
