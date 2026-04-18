---
title: "Taming the Long-Tail: Efficient Reasoning RL Training with Adaptive Drafter"
oneline: "TLT 把长尾 rollout 里空出来的 GPU 用来在线对齐轻量 drafter，并只在批量缩小到合适区间时开启 speculative decoding。"
authors:
  - "Qinghao Hu"
  - "Shang Yang"
  - "Junxian Guo"
  - "Xiaozhe Yao"
  - "Yujun Lin"
  - "Yuxian Gu"
  - "Han Cai"
  - "Chuang Gan"
  - "Ana Klimovic"
  - "Song Han"
affiliations:
  - "MIT, Cambridge, MA, USA"
  - "ETH Zurich, Zurich, Switzerland"
  - "NVIDIA, Cambridge, MA, USA"
  - "UMass Amherst, Cambridge, MA, USA"
  - "MIT, NVIDIA, Cambridge, MA, USA"
conference: asplos-2026
category: llm-training
doi_url: "https://doi.org/10.1145/3779212.3790231"
code_url: "https://github.com/mit-han-lab/fastrl"
tags:
  - llm-training
  - llm-inference
  - gpu
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

TLT 把 speculative decoding 引入推理型 RL 训练，但不改变训练算法，也不改变目标分布。它把长尾 rollout 中提前空出来的 GPU 和缓存特征回收起来在线训练一个极小的 drafter，并且只在活跃请求数缩小到合适区间时开启 speculation，从而把端到端训练吞吐提升到 VeRL 的约 `1.7x-2.1x`。

## 问题背景

这篇论文抓住了推理型 RL 中真正最贵的部分：拖慢训练的不是参数更新，而是 rollout。作者测到 rollout 大约占一个 RL step 时间的 `85%`，而且响应长度长期呈现重尾分布。论文引用的 ByteDance 32B 生产 trace 很典型：128 张 GPU 跑了 11 天只完成 385 个 step，因为总有少数响应一路打满最大长度，而大多数样本早就结束了。

这会产生两类浪费。其一，长尾阶段只剩少量请求继续生成，普通自回归 decoding 更加 memory-bound，GPU 利用率很差。其二，同步式 RL 会把这种尾部放大成全局等待：短样本不能释放后续 inference 和 training，整个流水线都要等最慢的那几个样本。VeRL 之类系统优化的是编排和放置，但没有消除 rollout 本身的瓶颈。常规 speculative decoding 也不能直接照搬，因为 RL 里的目标模型每一步都在变化，而活跃 batch 又会随着样本完成不断缩小。

## 核心洞察

论文最值得记住的命题是：长尾不只是坏现象，它本身就是可以回收利用的系统资源。因为大量 rollout worker 会先于最慢样本结束，所以在一个 RL step 尚未完成时，已经有 GPU 和 prefilling 产生的中间特征被释放出来。TLT 用这些 bubble 去持续训练一个轻量 drafter，避免 speculative decoding 随着目标模型更新而快速失效。

另一半洞察是 speculative decoding 不该全程开启。它最有价值的时候，恰恰是 rollout 已经进入小 batch 的尾部阶段。TLT 因此会等活跃请求数下降到阈值以下，再根据当前 batch 选择合适的 draft depth 和 verification budget。核心意思是，自适应 drafter 训练和自适应 speculation 必须一起设计。

## 设计

TLT 由两部分组成。Adaptive Drafter 是一个极小的草稿模型，只保留单个可训练 decoder layer，而 embedding 与 LM head 和目标模型共享。RL inference 时，系统缓存目标模型的 hidden states 和 embeddings，因此 drafter 训练不必重新做昂贵的 prefilling。训练框架本身可以支持 EAGLE、HASS、EAGLE-3 这类方案；论文默认选择 EAGLE，因为它在接受长度和训练开销之间折中最好。

Spot Trainer 让这个 drafter 能在线工作。TLT 用集中式 coordinator 跟踪每个 worker 的 `BUSY`、`IDLE`、`TRAINING` 状态，在长尾阶段把空闲 worker 提升为低优先级 drafter 训练任务，并在 rollout 结束时立即抢占回来。Online DataBuffer 会把当前 step 的部分样本和上一步的长序列一起用于训练，避免 drafter 只看到短样本；selective asynchronous checkpointing 与 sequence packing 则把这件事做得足够便宜。

Adaptive Rollout Engine 负责调度 speculation 本身。TLT 使用 tree-based drafting，然后用一个 Bucketed-Epsilon-Greedy 多臂老虎机根据最近的 accepted tokens 与 step latency，在不同策略之间做在线选择。为了让多策略不把显存吃光，系统会按 batch size 分桶 capture CUDAGraph，把 target 与 drafter 分开 capture，并合并兼容策略。学习型 drafter 尚未成熟时，系统还可以回退到基于 n-gram 检索的 model-free drafter。

## 实验评估

实验设置和论文中心论点是对齐的。作者把 TLT 实现在 VeRL 之上，运行在 64 张 H100 与一套独立的 A100 集群上，工作负载采用 GRPO、Eurus-2-RL 的数学和编程子集、`32K` 最大生成长度，以及 `7B-70B` 的四个目标模型。

端到端结果很强。相对 VeRL，TLT 的训练吞吐提升达到 `1.7x-2.1x`；H100 上几何平均为 `1.76x`，A100 上几何平均为 `1.79x`。在 H100 上，Qwen2.5-7B 和 Qwen2.5-32B 的相对吞吐分别达到 `2.12x` 和 `2.07x`。更重要的是 Figure 12：Qwen2.5-7B 与 Qwen2.5-32B 的平均 reward 曲线几乎和 VeRL 重合，这才真正支撑了“lossless training”的核心主张。

微观实验也能解释机制。对 Qwen2.5-7B、batch size 1 的 rollout，H100 上 speculative decoding 把吞吐从 `164.65` 提高到 `430.24` tokens/s，也就是 `2.61x`。即便 batch size 到了 `32`，Table 4 依然有 `1.70x-2.48x` 的收益，因此自适应开启比全程固定开启更合理。128 请求的 case study 进一步显示，系统在活跃请求数降到 `32` 以下后才开启 SD，最终取得 `2.44x` 的 rollout 加速。实现层面，Bucketed CUDAGraph capture 把 graph 显存占用从 `30.39 GB` 降到 `10.69 GB`，selective asynchronous checkpointing 把 checkpoint 延迟降低 `9.2x`，sequence packing 把 drafter 训练吞吐提高 `2.2x`。真正最有说服力的基线仍然是 VeRL。

## 创新性与影响

相对 _Sheng et al. (EuroSys '25)_，TLT 不是主要改进 RL 阶段摆放，而是直接处理 rollout 瓶颈。相对 _Leviathan et al. (ICML '23)_ 和 _Miao et al. (ASPLOS '24)_，它的新意不在 speculative decoding 本身，而在于让 speculation 能在目标模型持续更新、batch 持续缩小、worker 可抢占的 RL 环境里稳定工作。相对 _Li et al. (ICML '24)_，TLT 把 EAGLE 风格 drafter 变成更大 RL runtime 的一个组件，而不是独立的静态推理技巧。因此它更像是一种新的系统机制，而不是新的 RL 算法。

## 局限性

TLT 的收益仍然依赖特定工作负载形态。它最适合 rollout 很长、长度差异很大、并且会在尾部释放出空闲 GPU 的场景；训练早期也必须先依赖 model-free drafter 兜底。论文虽然覆盖了 H100、A100 以及部分消费级 GPU 的 rollout 实验，但大多数端到端证据仍集中在高端集群上的 GRPO 数学/代码推理训练，没有展示多模型训练、其他 RL 目标或低 bubble 场景。最后，即便用了优化后的 graph capture，文中一个配置下仍要付出 `10.69 GB` 的图内存开销。

## 相关工作

- _Sheng et al. (EuroSys '25)_ — VeRL 优化的是 RLHF 的端到端编排与共置，而 TLT 专门处理 reasoning RL 中真正主导时间的 rollout 阶段。
- _Leviathan et al. (ICML '23)_ — speculative decoding 提供了无损验证的理论基础，但默认目标模型固定，不涉及 RL 中每步漂移的 policy。
- _Miao et al. (ASPLOS '24)_ — SpecInfer 把 tree-based speculative verification 用于静态 serving；TLT 则把类似思想移植到动态 RL rollout，并加入在线策略选择。
- _Li et al. (ICML '24)_ — EAGLE 证明了单层 drafter 可以达到较高接受率，而 TLT 在此基础上增加了在线对齐与 spot training 机制。

## 我的笔记

<!-- 留空；由人工补充 -->
