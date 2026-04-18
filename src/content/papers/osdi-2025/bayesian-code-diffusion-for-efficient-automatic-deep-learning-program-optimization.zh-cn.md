---
title: "Bayesian Code Diffusion for Efficient Automatic Deep Learning Program Optimization"
oneline: "Bayesian Code Diffusion 为相似子图复用高质量 prior schedule 并扩散其参数，把 auto-tuning 时间最多缩短 3.31x。"
authors:
  - "Isu Jeong"
  - "Seulki Lee"
affiliations:
  - "Ulsan National Institute of Science and Technology (UNIST)"
conference: osdi-2025
code_url: "https://github.com/eai-lab/BayesianCodeDiffusion"
tags:
  - compilers
  - gpu
  - ml-systems
category: ml-compilers-and-gpu-kernels
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Bayesian Code Diffusion 通过把一个子图上已经优化好的 schedule 当作相似子图的 prior，再在其附近搜索，而不是每次都从随机 schedule 重新开始，从而加速 tensor program 的 auto-tuning。它集成在 Ansor 中后，最多把编译时间缩短 3.31x，同时通常还能保持，甚至略微改善最终程序的执行延迟。

## 问题背景

这篇论文解决的是 deep learning compiler 的一个现实瓶颈。TVM、Ansor 这类系统已经能自动搜索 tensor program 的 schedule，但搜索非常昂贵：每个子图几乎独立优化，候选程序常常从随机初始化开始，cost model 也只能根据当前搜索碰巧收集到的硬件测量在线学习。对于包含大量重复算子的模型，编译器会反复为相似问题支付相似成本。

作者把低效来源概括为三点：相似子图之间不复用调优结果，fine-tuning 从随机起点开始，cost model 又在早期看到过宽且重复的数据。已有工作能改善其中一部分，但通常带有一次性迁移、算子覆盖受限，或只能适用于 CPU 或 GPU 的限制。

## 核心洞察

论文的核心观点是，schedule search 应该把已经优化好的 schedule 当作 prior 来复用。某个子图找到的好参数，不只是这个子图自己的最终结果，也是在告诉我们相似子图的好参数大概率位于哪里。

这个想法成立的前提是，相似子图往往共享同一种 Ansor sketch，而且它们的最优参数彼此接近。于是系统不必重新搜索整个 schedule space，而是从 prior schedule 出发做受控的 code diffusion。相同的逻辑也用于学习过程：先用不同 clusters 的 priors 对 cost model 做 pre-training，再用各自的 posteriors 做 fine-tuning。

## 设计

实现分成三个阶段。第一步是按 sketch 聚类子图，而不是只按 operator 类型聚类，因为同一种 operator 仍可能导出不同的 optimization rules 和不同的搜索空间。第二步是在每个 cluster 中选择一个 prior 子图。论文把 tensor dimensions 连接成向量，用 cosine similarity 找出平均上最接近其他成员的子图，并为它分配更大的搜索预算。这也是 cost model 的 pre-training 阶段，因为来自不同 clusters 的 priors 会产生更丰富的测量数据。

第三步是通过 code diffusion 优化其余 posterior 子图。理论上，论文希望同时偏好低延迟和“靠近 prior distribution”的参数；工程上则把这个思想嵌进 Ansor 的 schedule rules。以 `InitFillTileSize` 为例，论文给出三种 diffusion 方式：loop extent 相同就直接复用 split factors；extent 不同就把 prior factors 映射到新 extent 上最接近的合法 divisors，或者按 extent 比例缩放；另外保留一条随机路径来维持多样性。扩散出来的 candidates 仍然会继续 fine-tuning。

cost model 本身没有换结构，系统依旧使用 Ansor 的 XGBoost predictor。真正的变化是训练顺序：先用分散的 priors 扩大覆盖面，再用 cluster 内的 posteriors 做更聚焦的 fine-tuning。

## 实验评估

原型实现建立在 TVM 的 Ansor 之上，实验平台包括 Intel Core i9-11900K CPU 和 NVIDIA A6000 GPU，评测模型覆盖 ResNet-18、MobileNet、BERT、VGG 和 EfficientNet 等。核心指标是：达到 Ansor 最佳程序延迟需要多少编译时间。

在这个指标上，Bayesian Code Diffusion 的结果很稳定。相对 Ansor，平均编译加速在 CPU 上是 2.52x，在 GPU 上是 2.00x，最大分别达到 3.31x 和 2.79x。程序质量没有因此变差。论文报告最终执行延迟最高还能比已有方法快 1.13x；而 first diffused programs 也已经很强，例如 GPU 上在 MXNet 上达到 1.65x、在 BERT 上达到 1.47x 的归一化速度提升。

这些实验也解释了收益来源。subgraph-cluster 的单独实验显示，相比 Ansor，平均优化加速为 2.11x。另一组实验只改变 cost model 的训练顺序，也能比 Ansor 更快到达低延迟程序。sparsity 分析进一步表明：在 CPU 上，speedup 与 sketch sparsity 的相关性更强；在 GPU 上，speedup 与 operator sparsity 的相关性更强。这与论文的解释一致：CPU 上 prior propagation 更关键，GPU 上 cost model 的学习顺序更关键。

## 创新性与影响

相对于 _Zheng et al. (OSDI '20)_，这篇论文改变了“可复用对象”的定义：调好的 schedule 和测量结果会成为其他子图的 prior。相对于 _Gibson and Cano (PACT '22)_，它是在当前模型内部在线完成复用，而不依赖外部 donor model。相对于 _Li et al. (ICPP '23)_，它迁移的不只是 cost-model specialization，还有 schedule parameters 本身。

它留下来的重要想法很直接：重复子图不该对应彼此独立的搜索空间。对后续 auto-tuners 和 tensor compilers 来说，这是一种很容易继承的机制。

## 局限性

论文明确承认，它的 Bayesian formulation 仍有相当一部分停留在概念层面。最优 schedule parameters 的真实 prior distribution 并不知道，当前实现只是用人工设计的 diffusion rules 去近似它，而且这些规则主要围绕 Ansor 展开，迁移到其他编译器未必直接成立。

prior selection 也只是启发式。系统根据 tensor-shape similarity 选 prior，但作者指出有时仍存在更好的 prior。收益还依赖于模型内部的重复度：如果 sketch sparsity 很高，或者 clusters 很小，可复用机会就会减少。最后，cost model 仍然是 Ansor 原本的 XGBoost，因此还有不少 headroom 不在本文的设计之内。

## 相关工作

- _Zheng et al. (OSDI '20)_ - Ansor 能自动生成 sketches 并完成高质量调优，但每个子图基本仍然要独立承担一次完整搜索。
- _Gibson and Cano (PACT '22)_ - Transfer-Tuning 从另一个已经预编译好的模型里复用 schedules，而 Bayesian Code Diffusion 在当前模型内部在线复用 priors，并同时支持 CPU 和 GPU。
- _Zheng et al. (MLSys '22)_ - DietCode 通过统一的 GPU-oriented search space 降低 dynamic tensor program 的搜索成本，但它支持的算子范围比本文更窄。
- _Li et al. (ICPP '23)_ - FamilySeer 通过对子图分组来改进 cost model 训练，而 Bayesian Code Diffusion 还会在这些子图之间扩散 schedule parameters。

## 我的笔记

<!-- 留空；由人工补充 -->
