---
title: "Dynamic Sparsity in Large-Scale Video DiT Training"
oneline: "DSV 用低秩注意力预测器筛出动态关键 KV，再结合稀疏 kernel 与混合 context parallelism，加速大规模 Video DiT 训练。"
authors:
  - "Xin Tan"
  - "Yuetao Chen"
  - "Yimin Jiang"
  - "Xing Chen"
  - "Kun Yan"
  - "Nan Duan"
  - "Yibo Zhu"
  - "Daxin Jiang"
  - "Hong Xu"
affiliations:
  - "Computer Science and Engineering, The Chinese University of Hong Kong, Shatin, Hong Kong"
  - "Independent, Beijing, China"
  - "StepFun, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762216"
code_url: "https://github.com/NetX-lab/DSV"
tags:
  - ml-systems
  - gpu
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

DSV 通过利用作者实测到的一种性质来加速 Video Diffusion Transformer 训练：绝大多数注意力质量实际上集中在一小撮、而且会变化的 key-value 对上。它先学习低秩预测器来识别这些 KV，再用定制 kernel 执行稀疏注意力，并按每个 head 的稀疏度重构 context parallelism。在最多 `128` 张 H800、最长 `520k` token 的设置下，论文报告训练吞吐最高提升 `3.02x`，同时相对 full attention 没有明显质量损失。

## 问题背景

这篇论文瞄准的是现代视频生成里一个非常具体的瓶颈。Video DiT 越来越依赖跨时间和空间 token 的 3D full attention，因为更简单的 spatial-temporal 分解往往保不住细节；但当 latent video 长到几十万 token 时，二次复杂度的 attention 会吞掉整个训练循环。作者展示，在 `200k` token 下，1.3B 和 3B 模型的 self-attention 分别占前向与反向时间的 `92%` 和 `93%`。而且这个长度下单卡甚至放不下完整序列，所以瓶颈同时牵涉计算和跨卡通信。

固定稀疏模式也不是现成答案。作者发现，video DiT 的 attention 虽然稀疏，但并不具备稳定的局部规律：关键 KV 不会像很多 LLM 长上下文优化里那样围绕窗口或 sink token 出现，稀疏度还会随 block、head 和训练进程一起变化。在案例中，top `10%` 的 KV 就贡献了超过 `90%` 的注意力分数，但只有 `15.1%` 的关键 KV 落在 query 半径 5 个 token 内。真正的挑战因此是：怎样在不先付出 dense attention 全部代价的前提下，利用这种动态稀疏性，并把收益一路传递到 kernel 和多 GPU 并行层面。

## 核心洞察

论文的核心命题是：video DiT attention 足够稀疏，可以大幅裁剪，但前提是把稀疏性视为运行时属性，而不是固定 mask。DSV 不去硬编码 window、sink 或静态模式，而是学习一个廉价的低秩注意力近似器，在昂贵的 dense 计算发生之前，先把真正重要的 KV 挑出来。

之所以可行，依赖两个观察。第一，主导注意力质量的 KV 和长尾之间差距很大，所以近似器只要大致保持排序就足以完成筛选。第二，虽然重要 key 对 query 来说不具备空间局部性，但相邻 query 往往共享相似的关键 KV 集合。论文报告，在一个 `2x2x2` token 立方体内部，critical KV 重叠率超过 `92.4%`，跨 block 的平均重叠率约为 `80.1%`。这让 DSV 可以先预测一次稀疏结构，再在邻近 query 之间复用，把稀疏性真正变成 kernel 层面的收益。

## 设计

DSV 包含三个核心部分：稀疏预测器、稀疏 kernel，以及稀疏感知的 context parallelism。首先，profiler 会周期性地对 full attention 做采样，跟踪每个 head 的稀疏度。对每个 attention block，DSV 训练低秩 query/key 投影矩阵，使 `Q_lr K_lr^T` 逼近 `QK^T`；损失函数更强调保留分数排序而不是绝对值。作者默认低秩内部维度为 `16`，并报告对 3B 模型来说，额外预测器参数少于 `10M`。

训练分两个阶段。Stage 1 保持 dense attention，只训练预测器，直到平均近似误差低于 `0.01`；论文说这通常在约 `5k` iteration 内完成。Stage 2 继续微调预测器，但 operation dispatcher 只会在当前稀疏度足够高且显存允许时启用 sparse attention，否则仍回退到 full attention。

Kernel 设计是性能成立的关键。朴素稀疏路径需要先物化 `[H, S, S]` 分数张量再做 `top-k`，在 `H=16`、`S=100k` 时仅 BF16 存储就要约 `320 GB`。DSV 把低秩矩阵乘和 `top-k` 融合进一个 kernel，只维护运行中的最优候选，把空间复杂度从 `O(S^2)` 降到 `O(SK)`。它还引入 query grouping，让邻近 query 共享中心 query 预测出的 KV 集合，以恢复访存合并和 tensor core 利用率。

最后是并行层。标准 head-wise CP 会因为不同 head 稀疏度不同而失衡，标准 sequence-wise CP 又会继续交换所有远端 KV。DSV 因此引入 sparse HCP 来重新分配 head、降低最慢 GPU 的计算负担，再用 sparse SCP 只拉取预测为 critical 的远端 KV，并为每个 block 选出最优混合配置。

## 实验评估

作者在 UCF-101、WebVid-10M、VideoGen 和 OpenVid 上评估了 0.8B、2.7B 和 30B 的 video DiT，规模最高到 `128` 张 H800。相对 dense full attention 和 window-based attention，DSV 在 2.7B + VideoGen 上把训练吞吐提升到 `2.1x-3.02x`，并能扩展到 `520k` token；在 30B + OpenVid 上，相对 full attention 的提升是 `2.06x-2.53x`。kernel 细分实验显示，在 `90%` 稀疏度下，端到端 kernel 路径带来 `2.2x-5.7x` 的前向加速和 `3.3x-4.0x` 的反向加速。

质量方面也基本守住了。UCF-101 上 DSV 的 FVD 是 `438.02`，full attention 是 `440.32`；OpenVid 上是 `782.22` 对 `838.52`；WebVid 两者几乎持平。VBench 结果也类似，30 人盲测中 DSV 的归一化得分最高，为 `4.57`，高于 full attention 的 `4.25`。我的判断是，在论文覆盖的区间里，DSV 更像是一个保持质量的训练系统，而不只是更快的近似实现。最后这句话是我基于结果做出的推断，不是论文原文。

## 创新性与影响

和 _Dao et al. (NeurIPS '22)_ 相比，DSV 不是又一个 dense attention kernel 优化，而是希望在稀疏性可预测后直接避开大部分二次计算。和固定 window 的视频注意力相比，它最关键的一步是否定了“有效稀疏性一定局部且静态”这个假设。和已有 context-parallel 训练方案相比，它把稀疏性当成一等性质，让它同时改变通信量和 head 分配方式。

因此，这篇论文的价值并不只局限于某一个视频模型。它更可迁移的套路是：先测量训练中自然出现的稀疏性，再训练一个廉价预测器，最后把 kernel 和并行策略一起围绕这种结构重构。

## 局限性

DSV 不是零成本方案。它依赖离线 profiling 来决定 query group 大小、稀疏阈值以及计算/通信模型，其中一部分调参还与硬件相关。系统也引入了预测器 warm-up、持续 profiling、针对 dense attention 的随机 spot-check，以及 critical-KV 索引的 CPU offload，这些都会增加训练栈复杂度。论文还表明，过度激进的裁剪并不安全：如果 critical-KV 阈值只保留 `40%` 的注意力质量，收敛会变差。

这篇工作也有明确边界。最大模型只有 `30B`，所以还没有处理更大 DiT 所需的 pipeline parallelism 负载均衡；query-specific 的稀疏度分配被留到未来工作；而且它在训练场景中的分布式收益论证，明显比在推理场景里更充分。

## 相关工作

- _Peebles and Xie (ICCV '23)_ — DiT 把 diffusion transformer 确立为可扩展的生成模型骨干，而 DSV 关注的是如何让它的长视频训练成本变得可承受。
- _Dao et al. (NeurIPS '22)_ — FlashAttention 让 dense exact attention 变得更 IO-aware，而 DSV 通过学习稀疏性来直接跳过大量 score 与 value 计算。
- _Esser et al. (ICML '24)_ — rectified-flow transformer 的扩展展示了生成式 Transformer 持续做大的趋势，而 DSV 解决的是视频 token 数暴涨之后暴露出来的系统瓶颈。

## 我的笔记

<!-- 留空；由人工补充 -->
