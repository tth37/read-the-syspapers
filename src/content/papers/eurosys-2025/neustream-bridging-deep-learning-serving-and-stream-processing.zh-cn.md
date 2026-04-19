---
title: "NeuStream: Bridging Deep Learning Serving and Stream Processing"
oneline: "NeuStream 把动态 DNN 推理改写成流式模块图，在模块粒度做批处理并按 SLO 重分配细粒度 GPU 资源，从而提高满足时延要求的 goodput。"
authors:
  - "Haochen Yuan"
  - "Yuanqing Wang"
  - "Wenhao Xie"
  - "Yu Cheng"
  - "Ziming Miao"
  - "Lingxiao Ma"
  - "Jilong Xue"
  - "Zhi Yang"
affiliations:
  - "Peking University"
  - "Peking University, Microsoft Research"
  - "Microsoft Research"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717489"
code_url: "https://github.com/Fjallraven-hc/NeuStream-AE"
tags:
  - ml-systems
  - scheduling
  - gpu
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

NeuStream 认为，带循环和分支的 DNN 推理不该再被当成一个不可拆分的大模型，而该被视作持续流动的模块图。它把执行拆成可复用的 stream module，在模块边界上做批处理，再按 partial SLO 分配 GPU 资源。论文报告在 diffusion 上相对 Clockwork 最高提升 5.26x goodput，在 OPT 服务上相对 vLLM 最高提升 69.31x。

## 问题背景

现代 serving 系统默认请求沿固定计算图前进，但 LLM decode、diffusion denoise、SkipNet 分支和 multi-agent 工作流都不是这样。请求会在不同时间进入不同阶段，还会反复回到同一个大模块。GPU 利用率却依赖 batching，所以一旦请求不同步，单体式 scheduler 就抓不住这些重汇合点。

论文还指出，不同阶段的 batching 曲线差异很大。CLIP、UNet、VAE 与 prefill、decode 都有各自拐点。超过阈值后，批次继续变大几乎不再提升吞吐，却会明显拉长等待时间。因此系统既要拆阶段，也要按阶段选 batch size 和资源份额。

## 核心洞察

NeuStream 的关键判断是，真正该调度的不是完整请求，而是那些会被反复执行的控制流「主体」。两个请求的全局路径可以不同，但它们常常会在不同时间重新汇合到同一个大模块上，例如 UNet 或 decode。只要把这些主体提升成 stream module，系统就能在模块边界重新聚合请求，而不必要求它们从头到尾走同一路径。

一旦端到端 SLO 被拆成模块级 partial SLO，调度问题也随之分层：模块内部只需决定该批多大，模块之间只需决定 GPU 资源怎么分，才能不让最慢环节卡住整条 pipeline。

## 设计

编程模型上，NeuStream 暴露 `stream` 和 `stream module`。后者包含 `gather`、`compute`、`scatter` 三个接口：先从输入流取一批消息，再运行普通 tensor 代码，最后把结果路由到下游流。于是原先写在 Python 控制流里的分支和循环，被改写成显式数据流；若阶段本身要迭代，例如 diffusion 或 LLM decode，模块可以把输出重新送回自己的输入流。

运行时把程序执行成一个 stream graph。前端接收请求，每个模块有一个 worker，循环执行 `gather-compute-scatter`。为了避免大 tensor 复制，stream 里主要传元数据和引用。模块也能维护跨消息状态；论文在 LLM 上把 decode 的 KVCache 当成模块状态，按 PagedAttention 的思路切成 block 存储，请求退出循环后再清理。

调度分两层。Intra-module scheduler 用 `L_i(b, a_i)` 和 partial SLO 算出允许的最大 batch size，只接纳仍有剩余预算的请求。Inter-module scheduler 引入 SPU，把 GPU 当成细粒度资源池，在总资源和显存约束下最大化最慢模块的 normalized goodput，再把 SPU 映射到真实 GPU 上，必要时做跨设备切分或 co-location。SPU 主要是调度抽象，不是硬件硬切；系统用 Earliest Finish Time First 把空间共享改写成时间复用，以避免 MPS 的不确定性。

## 实验评估

实验覆盖 diffusion、OPT-6.7B/13B/30B/66B 和 MatPlotAgent，硬件包括 RTX 4090、RTX A6000、H100，指标是满足 SLO 的 goodput。Diffusion 结果最能说明模块级 batching 的价值：在 RTX 4090 上生成 256x256 图像时，NeuStream 相对 Clockwork 在 DiT-S/2 的 4 requests/s 下达到 5.26x，在 CV=4 时领先 1.37x-4.04x，在 SLO scale 为 1.2 时最高领先 3.13x。论文给出的 batch trace 也对得上机制解释：DiT 的平均 batch size 在异质迭代数场景下是 Clockwork 的 5.35x，即便去掉这类差异仍有 1.67x。

LLM 结果更强，也更直接体现出分阶段调度的作用。A6000 上，NeuStream 在 OPT-13B 的 2 requests/s 时比 vLLM 高 1.53x，在 4 requests/s 时高 37.21x；扩展到四卡 OPT-66B，最高达到 69.31x。到 H100 上，峰值优势仍有 11.44x。论文把 vLLM 的失速归因于 decode 饥饿和 prefill 拥塞，这与设计主张一致。不过主实验没有把 DistServe、Splitwise 这类 phase-disaggregated 系统作为 baseline，因此更稳妥的读法是：NeuStream 明显优于单体式 serving。

## 创新性与影响

Clockwork 假设单体、可预测请求，vLLM 是 LLM 专用系统，BrainStorm 和 Cocktailer 更关注单请求内部的动态执行。NeuStream 的新意在于把 DNN serving 和 stream processing 真正接起来：让模块成为 batching 和资源分配边界，再把循环状态、GPU 资源切分和 SLO 调度一并落地。对以后包含更多循环、分支和多子模型的推理流水线，这个抽象很可能比单体式 serving 更贴切。

## 局限性

NeuStream 需要手动改写代码，把控制流搬到 `scatter`；即便论文称 Stable Diffusion 的改写不到 7% LOC，这仍是额外工程成本。它也依赖稳定的 profiling 和合理的 partial SLO 分配，论文没有深入分析漂移和误配会造成多大影响。除此之外，它在静态路径、阶段同质，或者单请求已经打满 GPU 的场景里收益有限；跨节点状态迁移和更强的 LLM baseline 仍留待后续工作。

## 相关工作

- _Gujarati et al. (OSDI '20)_ - Clockwork 也做基于时延预测的 SLO-aware serving，但它默认请求是单体式 DNN 执行，而不是会分解成动态模块图。
- _Kwon et al. (SOSP '23)_ - vLLM 通过 PagedAttention 和 continuous batching 优化 LLM serving；NeuStream 则把阶段拆分和资源均衡推广到更通用的动态 DNN 场景。
- _Cui et al. (OSDI '23)_ - BrainStorm 重点挖掘单个输入内部的动态性，NeuStream 关注的是多个请求在共享模块上的重聚合与批处理机会。
- _Zhang et al. (OSDI '23)_ - Cocktailer 从编译器视角分析动态控制流，而 NeuStream 处理的是部署后的运行时调度、SLO 管理和资源分配。

## 我的笔记

<!-- 留空；由人工补充 -->
