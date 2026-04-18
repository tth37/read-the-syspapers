---
title: "Nebula: Infinite-Scale 3D Gaussian Splatting in VR via Collaborative Rendering and Accelerated Stereo Rasterization"
oneline: "Nebula 将大场景 3DGS 的 LoD 搜索卸载到云端，只传输高时间局部性的 Gaussian 增量，并在客户端复用双目共享计算来做 VR 渲染。"
authors:
  - "He Zhu"
  - "Zheng Liu"
  - "Xingyang Li"
  - "Anbang Wu"
  - "Jieru Zhao"
  - "Fangxin Liu"
  - "Yiming Gan"
  - "Jingwen Leng"
  - "Yu Feng"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "ICT, Chinese Academy of Sciences, Beijing, China"
  - "Shanghai Jiao Tong University, Shanghai Qi Zhi Institute, Shanghai, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790190"
tags:
  - hardware
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Nebula 把大场景 3DGS 的切分点放在 LoD search 之后：云端负责找出这一帧该渲染的 Gaussian cut，客户端从这个 cut 继续渲染，并把左眼的大部分工作复用到右眼。论文报告 LoD 搜索最高 `52.7x` 加速，以及相对移动 GPU 基线 `12.1x` 的端到端加速。

## 问题背景

这篇论文抓住了两个扩展性问题。第一，本地头显根本装不下大场景 3DGS。作者测到场景运行时内存需求最高可到 `66 GB`，而常见 VR 设备通常不到 `12 GB`。更重要的是，场景变大后主瓶颈也不再是 rasterization，而是 LoD search；论文在移动 Ampere GPU 上测得，大场景里 LoD search 最多占到端到端延迟的 `47%`。

第二，纯云端视频流也不能真正解决问题。论文引用 `4K`、`90 FPS` VR 视频需要超过 `1 Gbps` 带宽，并且他们自己的剖析同样显示传输已经主导时延。已有 collaborative rendering 多数仍按像素切分任务，但 3DGS 的关键成本来自筛选 Gaussian。

## 核心洞察

Nebula 的核心观点是，最自然的切分点就在 LoD search 之后。LoD search 需要触及整棵层次化 Gaussian 结构，因此承受最高内存压力；而 cut 一旦选出来，后续阶段面对的只是一个小得多的 Gaussian 子集，本地设备就有机会装下。换句话说，云和端之间应该交换“本帧该渲染哪些 Gaussian”，而不是最终像素。

这个切分之所以成立，依赖两种强相似性。时间维度上，相邻帧 cut 的重叠率约为 `99%`，即便帧间隔到 `64` 也仍高于 `95%`。双目维度上，左右眼不重叠像素少于 `1%`。Nebula 因此只发送 Gaussian 增量，只复用 Gaussian 级几何关系，而不是做像素 warping，因此右眼结果仍保持 bit-accurate。

## 设计

Nebula 有三块关键设计。第一块是云端 LoD search。初始帧使用 fully streaming 的 GPU 遍历：作者为 LoD tree 增加按广度优先访问的连接，把固定大小节点块分给各个 warp，在 shared memory 中流式处理，并在找到 clean cut 后立刻停止。后续帧则使用 temporal-aware LoD search：先离线把 LoD tree 分成均衡子树，再从上一帧的 cut 出发，只搜索相关局部子树。论文强调，这样得到的结果与完整遍历保持 bit-accurate。

第二块是 Gaussian 增量管理。云端用 management table 和 reuse window `w_r` 跟踪客户端已经拥有的 Gaussian，每帧只发送客户端缺失的 `Delta cut`。两端共享回收阈值 `w_r* = 32`，超过阈值的旧 Gaussian 会同时删除。作者进一步用 vector quantization 压缩 spherical-harmonic 系数，并用 `16-bit` 定点数表示较小属性。

第三块是客户端 stereo rasterization。客户端在覆盖双眼的更宽 FoV 上只做一次 preprocessing 和 sorting。凡是通过左眼 `alpha` 检查的 Gaussian，都会被三角测量到右眼中的某个 tile，并被写入四类按 disparity 划分的列表之一。右眼渲染时只需 merge 对应列表。GSCore 只需额外加入解码器、stereo reprojection unit、merge unit，以及每个 VRC 一个 `16 KB` stereo buffer，总面积开销约 `14%`。

## 实验评估

这篇论文的实验同时覆盖算法和硬件。作者实现了一个 `1 GHz` 的 RTL 版 Nebula，并把结果缩放到 `8 nm`；对比对象包括移动 Ampere GPU、GSCore 和 GBU，云端则使用两张 `A100-80GB`。工作负载覆盖 `Urban`、`Mega`、`HierGS` 等数据集。

画质结果很强：相对左右眼都独立渲染的基线，Nebula 只损失 `0.1 dB` 的 PSNR，而且论文把这点损失归因于压缩而不是 stereo rasterization；SSIM 和 LPIPS 也没有下降。单看核心机制，temporal-aware LoD search 相比已有 LoD 搜索方法最高可达 `52.7x` 加速，stereo rasterization 相对 GPU、GBU 和 GSCore 分别带来 `1.4x`、`1.9x` 和 `1.7x` 本地渲染加速。

端到端上，Nebula 是文中最好的 collaborative 方案：相对移动 GPU 基线达到 `12.1x` 加速，默认硬件下约 `70.1 FPS`，相对移动 GPU 节能 `14.9x`，相对 GSCore 也节能 `1.4x`。论文多次用“相对有损视频流减少 `1925%` 带宽”来概括 Nebula。这个百分比写法有些别扭，但图中的定性结论是明确的：在他们的设置里，传 Gaussian 增量明显小于传压缩像素。

## 创新性与影响

和 _Kerbl et al. (TOG '24)_ 相比，Nebula 不是新的表示，而是围绕层次化 LoD 重新定义云端与客户端边界的系统设计。和 _Lee et al. (ASPLOS '24)_、_Ye et al. (HPCA '25)_ 相比，它的重点是把客户端加速器与云端 LoD 搜索、双目 bit-accurate 复用组合起来。和 _Feng et al. (ISCA '24)_ 相比，它最关键的一步是停止传像素，转而传 Gaussian 资产。

## 局限性

Nebula 很依赖时间相似性和双目相似性。论文在自己的数据集上证明了这些性质很强，但没有直接测试那种会显著降低重叠率的剧烈头部运动或场景变化。我担心低重叠时收益会下降，这一点是基于系统机制做出的推断，不是作者直接给出的实验结论。

部署层面的边界也很明显。默认硬件只有 `70.1 FPS`；若要达到 `90 FPS`，需要把渲染单元从 `128` 增加到 `256`，面积增加 `62.9%`。论文还排除了 LoD-tree 构建成本、多用户云端争用，以及更广义的云调度问题。

## 相关工作

- _Kerbl et al. (TOG '24)_ — HierGS 提供了 Nebula 所依赖的层次化 3DGS 表示与 LoD-tree 抽象，但并未讨论云端分工或双目共享计算。
- _Lee et al. (ASPLOS '24)_ — GSCore 专注于本地 3DGS 渲染加速；Nebula 则把这类客户端加速器放进云端协同框架里，并补上 stereo-specific 支持。
- _Feng et al. (ISCA '24)_ — Cicero 通过 warping 利用双目相似性，而 Nebula 认为对 view-dependent 的 3DGS 来说，Gaussian 级重投影更合适。

## 我的笔记

<!-- 留空；由人工补充 -->
