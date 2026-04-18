---
title: "TetriServe: Efficiently Serving Mixed DiT Workloads"
oneline: "TetriServe 把 DiT 的 sequence parallelism 下沉到单步调度，再按轮次打包请求，在共享 GPU 上提升混合分辨率生成任务的 deadline 命中率。"
authors:
  - "Runyu Lu"
  - "Shiqi He"
  - "Wenxuan Tan"
  - "Shenggui Li"
  - "Ruofan Wu"
  - "Jeff J. Ma"
  - "Ang Chen"
  - "Mosharaf Chowdhury"
affiliations:
  - "University of Michigan, Ann Arbor, Michigan, USA"
  - "University of Wisconsin-Madison, Madison, Wisconsin, USA"
  - "Nanyang Technological University, Singapore, Singapore"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790233"
code_url: "https://github.com/DiT-Serving/TetriServe"
tags:
  - ml-systems
  - gpu
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TetriServe 不再把 DiT serving 看成“给每个请求固定一个 sequence parallelism 配置”的问题，而是把它改写成 diffusion step 级别的 GPU 调度问题。系统先离线建模不同分辨率的扩展曲线，再在线按轮次选择刚好够用的并行度。论文在 FLUX 和 SD3 上报告，相比固定并行度基线，SLO Attainment Ratio 最高可提升 32%。

## 问题背景

这篇论文抓住了 DiT serving 和现有推理引擎之间的一个结构性错配。DiT 请求的差异主要来自输出分辨率，因此 256x256 和 2048x2048 请求在计算量上完全不在一个量级。但像 xDiT 这样的系统，仍然要求每个请求从头到尾绑定一个固定的 sequence parallelism 度数。并行度太低时，小图效率高但大图太慢；并行度太高时，大图能加速，小图却要承担额外通信和 GPU 浪费。更麻烦的是，请求一旦启动就很难中途改配，错误的起始选择会把后面的请求一起拖进 head-of-line blocking。论文在 Uniform workload 下展示了结果：在较紧的 SLO 下，没有任何固定策略的 SLO Attainment Ratio 能超过大约 0.6。真正的问题因此是，如何让固定 GPU 池在混合分辨率请求上动态选择并行度，从而尽量提高 deadline 命中率。

## 核心洞察

论文最重要的洞察是：DiT inference 足够可预测，因此可以在 diffusion step 粒度上做调度。和 LLM serving 不同，DiT 是无状态、计算绑定的；作者测得在不同分辨率与不同 sequence parallelism 度数下，单步执行时间的变异系数都低于 0.7%。这让离线 profiling 成本模型变得可信。既然 step 延迟可预测，调度器就可以把问题改写成两个判断：某个请求最少需要多少 GPU 才还能赶上 deadline？当前这一轮的 GPU 预算又该怎么分配，才能让最少的请求在下一轮变成“definitely late”？这样的表述把全局调度压缩成每轮可解的打包问题。

## 设计

TetriServe 由 request tracker、round-based scheduler、execution engine 和 latent manager 组成。论文先把 DiT serving 形式化为带 deadline 的 step-level GPU scheduling，并证明哪怕只看单步的简化版本，问题也是 NP-hard，因此在线全局最优并不可行。

第一个关键启发式是 deadline-aware GPU allocation。TetriServe 先离线 profile 不同 GPU 数量下的单步执行时间，再在运行时选出“仍能满足 deadline 且 GPU-hour 最小”的那档并行度。第二个关键启发式是 round-based request packing。系统把时间切成长度为 `tau` 的固定轮次；对每个请求，调度器计算本轮哪些分配能推进多少 step，并判断如果本轮不推进，它到下一轮开始时是否已经不可能按时完成。于是每轮决策变成一个 group-knapsack：每个请求至多选一个选项，在总 GPU 容量约束下，最大化“下一轮仍可挽回”的请求数量。

为了让算法真正落地，作者又加了两个工程机制。GPU placement preservation 尽量让请求在相邻轮次继续待在同一组 GPU 上，减少 remapping 停顿；elastic scale-up 则把剩余空闲 GPU 临时给那些确实能从更高并行度中受益的请求。除此之外，TetriServe 只在兼容的小分辨率请求之间做 selective continuous batching，并把 VAE decoder 设计为串行执行，以控制显存峰值。整套实现共 5,033 行 Python 和 C++。

## 实验评估

实验覆盖两个集群和两个代表性模型：8xH100 上的 FLUX.1-dev，以及 4xA40 上的 Stable Diffusion 3 Medium。默认工作负载从 DiffusionDB 采样 300 条 prompt，以泊松过程按每分钟 12 个请求到达，分辨率覆盖 256x256 到 2048x2048 四档。基线包括固定 `SP=1/2/4/8` 的 xDiT，以及更强的静态基线 RSSP，它会为每种分辨率离线挑选最优固定并行度。

核心结果很直接：TetriServe 在各种 SLO scale 下都得到最高的 SLO Attainment Ratio。按平均值看，它在 Uniform mix 上比最好的固定策略高 10%，在 Skewed mix 上高 15%；在更紧的点上优势更大，例如 Uniform mix 的 `1.1x` SLO scale 下高 28%，Skewed mix 的 `1.2x` 下高 32%。分辨率拆分图也说明了原因：固定并行度基线总是在自己擅长的分辨率上表现不错，但跨分辨率就会失衡；只有 TetriServe 能在整个分辨率范围上都保持较高 SAR。配套实验同样支持其机制解释。随着到达率从每分钟 6 个升到 18 个，它退化更平滑；在 bursty traffic 下更稳定；在 homogeneous workload 中仍然获胜；step granularity 分析则表明大约五步一轮在高负载下最平衡。论文还测得 latent transfer overhead 始终低于 step 延迟的 0.05%，并在 ablation 中显示 placement preservation 与 elastic scale-up 都能同时改善 SAR 和平均延迟。

## 创新性与影响

相较于 _Fang et al. (arXiv '24)_，TetriServe 的新意不在于提出 sequence parallelism，而在于把“并行度是多少”从固定运行时配置，变成每个 diffusion step 都可以重算的调度变量。相较于 _Huang et al. (arXiv '25)_，它更明确地围绕 per-request deadline 与 SLO attainment 组织问题，而不是只追求吞吐。相较于 _Agarwal et al. (NSDI '24)_ 这样的缓存系统，它解决的是正交问题：缓存之后剩余的 denoising work 应该如何调度。因此，这篇论文更像是为新兴工作负载提出的一种调度机制，而不是新的模型结构。

## 局限性

TetriServe 依赖针对具体模型、硬件平台和 GPU 数量做离线 profiling，因此可移植性并不免费。它的动作空间也主要围绕 2 的幂次 GPU 分配和少量离散分辨率来设计，这很符合论文目标部署，但对更杂乱的真实负载，证据仍然有限。round-based 抽象本身也带来调参张力：轮次过细时调度开销放大，轮次过粗时系统又来不及在 deadline 滑落前做反应。最后，实验聚焦于共享 GPU 上的单模型服务，没有处理多模型路由、跨 fleet 的 admission control，或与其他租户共存时的资源竞争。

## 相关工作

- _Fang et al. (arXiv '24)_ — xDiT 提供了固定 sequence-parallel 配置的 DiT inference engine，而 TetriServe 在其之上加入了 deadline-aware 的单步并行度选择。
- _Huang et al. (arXiv '25)_ — DDiT 也研究 diffusion 模型的动态资源分配，但 TetriServe 更聚焦于 mixed online workload 下的 SLO attainment，而不是以吞吐为中心的 serving。
- _Agarwal et al. (NSDI '24)_ — Nirvana 通过 approximate caching 减少 diffusion 计算量，而 TetriServe 更有效地调度剩余计算，两者可以自然组合。

## 我的笔记

<!-- 留空；由人工补充 -->
