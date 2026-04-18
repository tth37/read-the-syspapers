---
title: "AGS: Accelerating 3D Gaussian Splatting SLAM via CODEC-Assisted Frame Covisibility Detection"
oneline: "AGS 复用视频 CODEC 的 SAD 中间结果估计帧共视性，据此跳过大部分跟踪细化与无贡献 Gaussian，并用专用硬件流水化 3DGS-SLAM。"
authors:
  - "Houshu He"
  - "Naifeng Jing"
  - "Li Jiang"
  - "Xiaoyao Liang"
  - "Zhuoran Song"
affiliations:
  - "School of Computer Science, Shanghai Jiao Tong University, Shanghai, China"
  - "Department of Micro-Nano Electronics, Shanghai Jiao Tong University, Shanghai, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3760250.3762229"
tags:
  - hardware
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

AGS 把视频 CODEC 在运动估计阶段本来就会产生的 SAD 值拿来充当帧共视性信号。共视性高的帧只做粗粒度位姿估计和选择性映射，共视性低的帧再补少量 3DGS 细化与完整映射。配合对应的专用硬件流水线后，它相对 A100、AGX Xavier 和 GSCore 分别获得 `6.71x`、`17.12x` 和 `5.41x` 的速度提升，同时只付出较小精度代价。

## 问题背景

论文要解决的是 3DGS-SLAM 很准但太慢的问题。像 SplaTAM 这类系统能把场景重建质量做得明显高于传统 SLAM，但不到 600 帧的输入在 A100 上仍需 20 多分钟。这对需要快速建图后立刻执行任务的机器人并不现实。

作者把瓶颈归纳为三点。第一，跟踪约占每帧运行时间的 `83%`，因为它通常需要约 `200` 次 3DGS 迭代，而映射只需约 `30` 次。第二，一个 Gaussian table 中有 `85.1%` 的 Gaussian 对输出像素没有贡献，却仍会被处理。第三，early termination 会让部分像素引擎提前空闲、部分继续忙碌，导致硬件失衡。GSCore、Cicero 这类已有加速器能帮助渲染或 NeRF 推理，但没有覆盖完整、训练主导的 3DGS-SLAM 流水线。

## 核心洞察

这篇论文最重要的命题是：SLAM 相邻帧的时间相似性足够强，一个廉价的帧共视性指标就能同时指导跟踪裁剪、映射裁剪和硬件调度。AGS 不额外做复杂分析，而是直接复用视频 CODEC 在宏块运动估计里产生的最小 SAD 值，把它们当作当前帧与上一帧差异程度的近似。

这个指标能驱动两类优化。对跟踪来说，共视性高意味着相机位姿离上一帧不远，轻量级神经网络估计通常已经够用，只有共视性低的帧才需要继续做 3DGS 细化。对映射来说，共视性高意味着上一关键帧里“不贡献颜色”的 Gaussian，大概率在当前帧里仍然不贡献；论文显示，在最高共视等级下，这种延续比例超过 `80%`。另外，alpha 计算不依赖后续递归颜色累积，因此可以拆出来做负载再分配。

## 设计

AGS 的整体设计由三部分构成。第一部分是基于 CODEC 的帧共视性检测。系统从运动估计阶段拿到各宏块的最小 SAD，把它们累加成共视性分数，并同时送给跟踪路径和映射路径。

第二部分是 movement-adaptive tracking。每个输入帧都会先做一遍粗粒度位姿估计，底座来自 Droid-SLAM 风格的特征提取与 ConvGRU 更新器。如果当前帧共视性高于 `ThreshT`，系统直接接受粗估计；若低于阈值，再补上 `IterT` 次 3DGS 细化。论文最终采用 `ThreshT = 90%` 和 `IterT = 20`。

第三部分是 Gaussian contribution-aware mapping。AGS 把帧分成 key frame 与 non-key frame。关键帧执行完整映射并记录贡献信息；非关键帧重用这些记录，跳过预测为“无贡献”的 Gaussian。具体做法是先用 `Threshα = 1/255` 判断单像素层面的无贡献，再统计该 Gaussian 在整帧中的无贡献像素数，并与 `ThreshN` 比较。key/non-key 的划分由 `ThreshM` 决定，最终取值为 `ThreshM = 50%`、`ThreshN = 450`。

硬件层与算法层一一对应。FC detection engine 借助现有视频 CODEC 工作；pose tracking engine 由 `32 x 32` systolic array 加轻量级 GS array 组成；mapping engine 则加入 GS logging/skipping table 和 update/comparison unit。最有意思的是 GPE scheduler：它把渲染拆成 alpha 计算与颜色累积两个阶段，让空闲 GPE 先替忙碌 GPE 计算 alpha，并把结果放进 alpha buffer，从而把 temporal reuse 直接转化成更高利用率。

## 实验评估

实验同时覆盖算法效果与硬件效果。软件侧使用 TUM-RGBD、Replica 和 ScanNet++；对比对象包括 SplaTAM、Orb-SLAM2、GPU 平台和 GSCore 组合方案。硬件侧采用带 Ramulator 的周期级模拟器，并将 Verilog 设计在 28nm、`500MHz` 条件下综合，因此证据对架构论文是充分的，但仍属于仿真结果。

最重要的精度结果是，AGS 在 TUM-RGBD 的跟踪上把几何平均 ATE RMSE 从 SplaTAM 的 `5.54 cm` 降到 `2.81 cm`，相当于 `1.97x` 改善；映射只带来平均 `2.36%` 的 PSNR 损失。选择性映射也比较稳，把有贡献 Gaussian 误判为无贡献的平均假阳性率只有 `5.7%`。性能方面，AGS-Server 相对 A100 和 GSCore-Server 的平均加速比分别为 `6.71x` 与 `5.41x`，AGS-Edge 相对 AGX Xavier 和 GSCore-Edge 为 `17.12x` 与 `14.63x`；能效相对 A100 提升 `22.58x`，相对 AGX Xavier 提升 `42.28x`。另外，作者把 AGS 接到 Gaussian-SLAM 上也得到 `5.11x` 加速。论文自己的分析还表明，TUM-RGBD 中有 `63.8%` 的相邻帧属于高共视性，这解释了为何该方法能稳定获益。

## 创新性与影响

相对于 _Keetha et al. (CVPR '24)_，AGS 的新意不在于提出另一套 3DGS-SLAM 软件算法，而是把时间相似性同时转化为跟踪减算、映射裁剪和硬件流水化。相对于 _Lee et al. (ASPLOS '24)_，它覆盖了 3DGS-SLAM 的完整训练路径，而不只是在渲染阶段做推理加速。相对于直接套用 _Teed and Deng (NeurIPS '21)_ 的神经跟踪器，AGS 只把 Droid-SLAM 风格模块当作粗估计前端，并保留少量 3DGS 细化来维持建图质量。它对 temporal reuse、AI 加速器和实时 3DGS-SLAM 研究都很有参考价值。

## 局限性

AGS 的收益强依赖输入序列结构。只有当相邻帧共视性足够高时，粗粒度跟踪和选择性映射才真正成立；若相机快速运动、场景动态很强，或者存在明显视角跳变，两条加速路径都会变弱。论文中的 `IterT`、`ThreshM` 和 `ThreshN` 也都是在 Desk 场景敏感性实验中经验选出来的，可迁移性并不是零成本。

硬件评估同样有典型限制。性能结论来自 trace 驱动的周期模拟和综合，而不是实芯片测试；与 GSCore 的对比需要把 GSCore 的加速渲染与 GPU 训练部分拼接，因为 GSCore 本身并不支持完整 3DGS 训练。最后，AGS 在纯轨迹精度上仍不如传统 SLAM，Orb-SLAM2 的几何平均 ATE RMSE 为 `1.98 cm`。也就是说，AGS 优化的是高质量 3DGS-SLAM 的效率边界，而不是在所有场景下取代几何派 SLAM。

## 相关工作

- _Keetha et al. (CVPR '24)_ — SplaTAM 是 AGS 的软件基线，AGS 保留其 3DGS-SLAM 重建范式，但削减了大量跟踪迭代和映射计算。
- _Teed and Deng (NeurIPS '21)_ — Droid-SLAM 为 AGS 的粗粒度位姿估计提供神经网络骨架，而 AGS 额外加入选择性的 3DGS 细化来维持与 3DGS 建图的一致性。
- _Lee et al. (ASPLOS '24)_ — GSCore 通过跳过无用渲染工作加速 3DGS 推理，而 AGS 关注的是训练主导的 SLAM 回路，并利用跨帧冗余做裁剪。
- _Yan et al. (CVPR '24)_ — GS-SLAM 代表另一类 3DGS-SLAM 系统设计，AGS 的关注点则是基于共视性的体系结构加速，而不是场景表示策略本身。

## 我的笔记

<!-- 留空；由人工补充 -->
