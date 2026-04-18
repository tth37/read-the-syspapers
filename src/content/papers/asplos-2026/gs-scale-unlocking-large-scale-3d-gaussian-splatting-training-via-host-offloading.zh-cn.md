---
title: "GS-Scale: Unlocking Large-Scale 3D Gaussian Splatting Training via Host Offloading"
oneline: "GS-Scale 把大部分 3DGS 训练状态放到主机内存，只把几何常驻 GPU 并流水化转发更新，让消费级 GPU 也能训练大得多的场景。"
authors:
  - "Donghyun Lee"
  - "Dawoon Jeong"
  - "Jae W. Lee"
  - "Hongil Yoon"
affiliations:
  - "Seoul National University, Seoul, Republic of Korea"
  - "Google, Mountain View, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790167"
code_url: "https://github.com/SNU-ARC/GS-Scale.git"
tags:
  - gpu
  - memory
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

GS-Scale 追问的是一个很直接的问题：能不能把大场景 3D Gaussian Splatting 训练里的 GPU 显存当成缓存，而不是当成全部训练状态的唯一存放位置。它的回答是，把全部 Gaussian 参数和 Adam 状态都放到主机内存里，每轮只把当前可见子集搬到 GPU，再用几何参数常驻、参数转发流水线和延迟优化器更新把性能损失补回来。结果是峰值 GPU 显存降低 `3.3x-5.6x`，而训练吞吐仍然接近纯 GPU 方案。

## 问题背景

论文讨论的是 3DGS 训练里一个很尖锐的扩展性瓶颈：想要更好的场景质量，通常就得用更多 Gaussian；而 3DGS 的显式表示在进入训练阶段后，显存开销会被进一步放大。每个 Gaussian 有 59 个可训练参数，训练时还要再为梯度、优化器状态和激活留空间。作者测得，在常见的 `1K-4K` 训练分辨率下，和 Gaussian 相关的状态占了大约 `90%` 的 GPU 内存，激活只占约 `10%`。像 Rubble 这样的场景，如果想达到最高质量，大约需要 `4000` 万个 Gaussian，对应约 `53 GB` 显存，单张消费级 GPU 根本装不下。

一种自然思路是改用多 GPU 分布式训练，论文也点名了几篇这样做的近期工作。但作者认为，这并不适合作为默认答案，因为很多 3DGS 用户恰恰是希望在笔记本或台式机上，用自己采集的图像重建个人空间或工作场景。Host offloading 之所以值得尝试，是因为每轮真正参与渲染和反向传播的，只是当前视锥里的 Gaussian。作者的 profiling 显示，大场景里平均只有 `8.28%` 的 Gaussian 会在一轮训练中变成 active。问题在于，剩下那两个必须“看全局”的步骤，也就是 frustum culling 和 Adam 更新，如果全搬到 CPU，就会立刻成为瓶颈。

## 核心洞察

这篇论文最值得记住的命题是：3DGS 的 host offloading 只有在系统能保留“活跃集稀疏”这个好处、同时把 CPU 上全模型参与的关键路径拆掉时，才真正成立。换句话说，重点不只是“把不活跃的 Gaussian 挪到主机内存”，而是要按访问模式切分训练状态。几何参数之所以特殊，是因为每轮 culling 都需要它们；而很多非几何参数又恰好相反，它们经常拿到零梯度，因此可以延迟更新，稍后再无损恢复。

一旦把问题这样重述，GS-Scale 的整体结构就顺理成章了。GPU 内存只保留必须保持热态的部分：全部 Gaussian 的几何属性，以及当前可见子集的其他参数。CPU 内存承担剩下的大头。论文真正新颖的地方，是把 3DGS 训练理解成“每轮都有稀疏工作集”的内存层级问题，并围绕这个工作集去组织流水线。

## 设计

基线版设计很直白：所有参数和优化器状态都在主机内存；CPU 先做 frustum culling 找出可见 Gaussian 的 ID；把这些参数通过 PCIe 传到 GPU；GPU 做前向和反向；梯度传回 CPU；最后 CPU 执行 Adam。这样当然能省显存，但论文显示，在 RTX 4070 Mobile 笔记本上，它比纯 GPU 训练慢大约 `4x`，因为 CPU 上的 culling 和 optimizer update 太重，而且 GPU 会长时间空转等待。

GS-Scale 在此基础上加了三个关键优化。第一是 selective offloading：把所有 Gaussian 的几何属性，也就是 `mean`、`scale` 和 `quaternion`，始终放在 GPU 上。因为 frustum culling 只需要这些字段，所以这一步把最贵的 culling 操作重新拉回 GPU。代价只是每个 Gaussian 的 59 个参数里保留 10 个，约 `17%` 的额外显存占用；但其余 `83%` 的非几何属性以及对应优化器状态仍然可以放在主机侧。

第二是 parameter forwarding，它用来打断“CPU 必须先把所有参数更新完，GPU 下一轮才能开始”的依赖链。做完 culling 后，系统已经知道下一轮会用到哪些 Gaussian。CPU 于是只提前更新这些即将用到的非几何参数，并把它们按 `32 MB` 分块转发到 GPU；其他参数则在 CPU 上懒更新，与 GPU 的前向和反向并行进行。与此同时，几何参数及其优化器状态一直常驻 GPU，所以每轮结束后就能立刻更新。这样训练循环就从串行步骤改成了流水线。

第三是 deferred optimizer update。作者抓住了 Adam 在零梯度下的一个性质：若某个 Gaussian 这一轮根本没参与计算，那么它的动量和方差只是在按固定系数衰减。因此 GS-Scale 不会立刻去碰这些权重和优化器状态，而是只递增一个 `4-bit` 的 defer counter；等到该 Gaussian 再次 active，或者计数达到 15 时，再用预计算好的缩放因子把 momentum、variance 和 weight 恢复出来。论文报告，在 Rubble 上只有 `2.29%` 的 Gaussian 会碰到最大延迟计数，平均延迟次数是 `5.03`，这意味着大量本来纯属浪费的 CPU 内存访问都被省掉了。

论文还处理了另一个独立问题：哪怕平均 active 比例很低，只要有一张覆盖范围特别大的训练图像，峰值显存仍可能被它决定。为此 GS-Scale 加入了 balance-aware image splitting。当 active/total 比例超过阈值时，把图像分成两个子区域分别渲染和反传，再在 CPU 上汇总梯度并执行一次优化器更新。作者还在训练前用一次二分搜索去寻找更均衡的分割点，而不是简单地按面积对半切。

## 实验评估

实验基本证明了论文的核心主张：host offloading 确实可以显著省显存，而且不会把训练速度拖到不可用。GS-Scale 基于 `gsplat` 实现，在六个大场景上相对纯 GPU 训练取得了 `3.98x` 的几何平均峰值显存下降，单场景降幅落在 `3.3x-5.6x`。Aerial 是最能说明问题的例子：不用 offloading 时它需要超过 `50 GB` 显存，而 GS-Scale 把这个需求压低了 `5.5x`，从而让 RTX 4080 Super 这样的单卡也能训练它。

吞吐结果更细一些，但整体仍然很强。相对最朴素的 host-offloaded 基线，完整 GS-Scale 在笔记本和台式机上分别带来 `4.47x` 和 `4.57x` 的吞吐提升。若和纯 GPU 训练相比，在排除 OOM 情况后，它达到笔记本 `1.22x`、台式机 `0.84x` 的几何平均性能。这个呈现方式是合理的，因为很多更大规模的配置里，纯 GPU 根本跑不起来。论文还单独检查了训练质量：六个场景上的 PSNR、SSIM 和 LPIPS 与原始训练流程几乎一致，说明 deferred update 更像是系统实现层面的优化，而不是会明显改变收敛结果的近似。

真正的收益体现在“能训多大”上。在 RTX 4070 Mobile 上，GS-Scale 把可训练 Gaussian 数量从 `400` 万提升到 `1800` 万；在 RTX 4080 Super 上，则从 `900` 万提升到 `4000` 万。更大的模型也确实转化成了更好的重建质量：论文报告笔记本平台上的 LPIPS 几何平均下降 `28.7%`，台式机上下降 `30.5%`。

## 创新性与影响

和 _Zhao et al. (ICLR '25)_ 的 Grendel 相比，GS-Scale 追求的是同一个目标，即在不改原始 3DGS 训练语义的前提下扩展规模，但它走的是单 GPU 加 host offloading 的路线，而不是多 GPU 分布式执行。和 _Liu et al. (ECCV '24)_ 的 CityGaussian 以及其他 divide-and-conquer 工作相比，这篇论文最重要的新意在于坚持保留端到端的原始训练流程，而不是通过场景切块去换内存、再承受边界质量损失。和 _Ren et al. (USENIX ATC '21)_ 的 ZeRO-Offload 相比，它把 host offloading 做成了 3DGS 特化设计：抓住的是每轮可见性稀疏和零梯度结构，而不是通用的逐层预取。

因此，这篇论文的价值主要不在新的渲染模型，而在一个贴着 3DGS 训练访问模式设计出来的内存层级与调度方案。对所有想在消费级硬件上把 3DGS 做实用化的人来说，它都很可能会成为一个关键参考点。

## 局限性

GS-Scale 很依赖论文测到的稀疏活跃集特征。如果某类工作负载在多数迭代里都会激活大比例 Gaussian，那么它的显存节省效果和 deferred update 的收益都会明显下降。系统还默认你有足够大的主机内存，以及还不错的 CPU 内存带宽；论文明确展示了性能和 GPU/CPU 带宽比有关，并且指出在 NUMA 服务器上，由于延迟更新带来的随机访问局部性差，效果会比单节点平台更弱。

image splitting 更像是一个务实的兜底机制，而不是普适解。它只切成两个子区域，实验里采用固定的 `mem_limit = 0.3`，而且分割点只在训练开始前算一次，后续 densification 改变 Gaussian 分布时并不会重新优化。评估总体上是扎实的，但若看吞吐对比，若干实验不得不把场景缩小到 GPU-only 还能勉强运行的规模，所以最干净的 apples-to-apples 速度比较并不发生在最极端的大规模区间。

## 相关工作

- _Kerbl et al. (SIGGRAPH '23)_ — 原始 3D Gaussian Splatting 论文定义了 GS-Scale 所要保留并扩展的显式 Gaussian 训练流水线。
- _Zhao et al. (ICLR '25)_ — Grendel 通过多 GPU 分布式训练来保持原始 3DGS recipe，而 GS-Scale 用单 GPU 的主机侧 offloading 来换取更低部署门槛。
- _Liu et al. (ECCV '24)_ — CityGaussian 代表按场景切块的 divide-and-conquer 路线，GS-Scale 则主张不改训练语义、避免边界质量与效率损失。
- _Ren et al. (USENIX ATC '21)_ — ZeRO-Offload 是最接近的 host-offloading 参照，但 GS-Scale 增加了围绕可见性稀疏与延迟更新的 3DGS 专用机制。

## 我的笔记

<!-- empty; left for the human reader -->
