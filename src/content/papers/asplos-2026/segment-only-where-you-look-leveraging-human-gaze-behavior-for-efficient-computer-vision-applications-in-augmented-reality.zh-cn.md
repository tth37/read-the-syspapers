---
title: "Segment Only Where You Look: Leveraging Human Gaze Behavior for Efficient Computer Vision Applications in Augmented Reality"
oneline: "SOLO 用视线驱动显著性采样、结果复用和 SoC 插件加速器，让 AR 分割只围绕用户当前注视的对象执行。"
authors:
  - "Tianhua Xia"
  - "Haiyu Wang"
  - "Sai Qian Zhang"
affiliations:
  - "Tandon School of Engineering, New York University, New York City, NY, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790216"
tags:
  - hardware
  - energy
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SOLO 的核心主张是：AR 分割不该继续对整张高分辨率画面一视同仁，而应该跟着人的注意力走。它把视线感知下采样、跨帧复用、显著性感知图像传感器和 SoC 插件加速器连成一条链，只在注视目标附近保留高分辨率。论文报告端到端延迟最高可降 `12x`，相对全分辨率 GPU 基线平均获得 `8.6x` 加速和 `9.1x` 节能。

## 问题背景

论文瞄准的是 AR 视觉工作负载和 AR 硬件之间非常尖锐的不匹配。多百万像素外向摄像头已经很常见，但把整帧直接送进现代分割网络，在移动级硬件上远远达不到交互要求。作者用 Jetson Orin NX 近似 AR 计算平台时，`2880 x 2880` 输入上的 HRNet 延迟达到 `3347 ms`，ViT-Base 达到 `3942 ms`；而流畅 AR 体验大约只容得下 `50-70 ms`。简单把整帧统一缩小也不行，因为用户真正关心的对象会一起被压糊。

AR 使用行为本身却很有结构。用户通常会在一个对象上停留一段 fixation，然后通过 saccade 跳到下一个对象；而在短时间窗口内，头部姿态常常让连续帧保持高度相似。于是，全帧分割同时浪费在两个地方：外围区域不重要，许多帧的结果又本可以复用。论文因此把目标改写成端到端系统设计问题：怎样把视线行为转化为感知、带宽和推理成本的真实下降。

## 核心洞察

这篇论文最值得记住的命题是：在 AR 里，真正值得被精细分割的对象，通常就是当前视线附近的实例，而人的视觉生理又允许系统据此有选择地计算。fixation 期间，精度主要需要保证在注视对象附近；saccade 期间，人眼会发生短暂的 saccadic suppression，因此部分帧可以直接跳过；在视角变化不大的短视频段内，前一帧的 mask 往往还能继续使用。只要系统能从眼部相机低成本预测视线，再把它转成外向相机上的显著性图，就能只在真正重要的地方花费像素和算力。

这比一般的 learn-to-downsample 更进一步，因为这里的显著性图不是只靠场景统计推断的。SOLO 同时使用眼部图像和粗粒度前景图像，因此下采样策略表达的是“用户此刻想看什么”。对应的硬件含义也很直接：既然已经知道该读哪些像素，就不该再把整张图都采下来再压缩，而应该从传感器读出阶段就跳过不需要的部分。

## 设计

软件路径的核心是 `SOLONet`。系统先把完整输入帧均匀下采样成粗粒度图像 `I_fd`，再把 `I_fd` 和眼部图像 `I_e` 一起送入 `ESNet`。`ESNet` 包含八层 gaze-tracking ViT、基于 attention score 的 token pruning、`int8` 量化，以及一个单层 RNN 来检测 saccade；它输出显著性分数图，再据此把原始高分辨率帧变成更小但非均匀的 `I_fs`，只在注视实例附近保留高分辨率。

下游分割网络也针对任务做了收缩。它不再尝试为整张图的所有对象都输出像素级结果，而只输出“当前关注实例”的二值 mask 和类别标签，再上采样回原始分辨率。训练时，作者端到端联合优化，用 Dice loss 保证实例区域分割质量，再加一个 `l2` 正则项推动显著性图贴近真实实例区域。

在线执行时，`SSA`，也就是 SOLO Streaming Algorithm，负责决定什么时候必须重新分割。只有当视角变化超过阈值 `alpha`、视线位置变化超过阈值 `beta`，或者进入新的视图段时，系统才重新运行 `SOLONet`；若检测到 saccade，也可以直接复用结果。

硬件路径把同样的思想推进到传感器和 SoC。论文在外向摄像头中加入 `SBS`，也就是 saliency-based sensing，只读出被选中的 pixel sub-array，从源头减少 ADC/readout 和 MIPI 传输成本；同时，一个面积为 `4.7 mm^2` 的 SOLO accelerator 作为 AR SoC 插件实现 `ESNet`，内部用 `16 x 16` systolic array 和控制逻辑来完成 token pruning、复用检查与索引生成。

## 实验评估

实验同时覆盖算法精度和硬件收益。在 LVIS、ADE20K 和 Aria Everyday 上，作者把 SOLO 与平均下采样 `AD`、不使用视线信息的显著性下采样 `LTD`，以及全分辨率分割 `FR` 做比较，并分别测试 HRNet、SegFormer、DeepLabV3 作为 backbone。最能说明问题的结果是：在 FLOP 预算接近的前提下，引入视线条件确实同时提升了精度和效率。以 HRNet on LVIS 为例，SOLO 达到 `0.66/0.56` 的 b-IoU/c-IoU，而 `LTD` 只有 `0.56/0.49`，`FR` 只有 `0.53/0.45`。

复用实验也很关键。作者显示，在 Aria Everyday 上，SSA 跳过大约 `60%` 帧时，c-IoU 只下降 `0.05`。硬件侧结果则更直接支撑论文主张：和 `FR+GPU` 相比，SOLO 在多种模型和数据集上的平均收益是 `8.6x` 加速和 `9.1x` 节能。一个很直观的例子是 HR on Aria，延迟从 `598.2 ms` 降到 `49.4 ms`。传感器实验也说明 co-design 不是陪衬：在高光照下，`SBS` 平均把感知延迟再降 `4.3x`，感知能耗平均下降 `8.9x`。

用户研究在这里尤其重要，因为“正确性”本来就和延迟强相关。Quest Pro 上的静态场景 A/B 测试显示，参与者在 `96% +/- 6%` 的试次里更偏好基于 SOLO 的呈现；在 DAVIS 2016 的动态场景实验中，SOLO 在 `128` 次试验中被选中 `122` 次，同时在启用 SSA 后仍维持 `28.7 ms` 的平均逐帧延迟。综合来看，这些结果确实支持论文的中心论点：收益不只是减少算术量，更是在人的感知层面得到更好的延迟-精度平衡。

## 创新性与影响

相对于 _Recasens et al. (ECCV '18)_ 和 _Thavamani et al. (ICCV '21)_ 这类显著性下采样工作，SOLO 的新意在于把“显著性”从通用场景统计替换成真实用户视线，并把这个信号一路推进到传感器和 SoC。相对于 _Cheng et al. (CVPR '22)_ 这类常规分割系统，它把任务从“分割整个场景”收缩成“分割当前被注视的实例”，再围绕这一更窄的契约做系统级优化。因此，这篇论文最可能影响 AR 系统构建者、移动视觉系统研究者，以及关注感知驱动计算的软硬件协同设计研究者。

## 局限性

这套方案天然依赖“当前注视实例就是最值得精细分割的对象”这一前提。凡是需要全场景理解、多对象联合推理，或者持续监控外围异常的任务，都不太适合直接套用；系统也依赖较准确的 gaze estimation。论文中不少最亮眼的硬件结论来自 RTL 综合和传感器建模，而不是已经流片并集成到真实设备中的芯片。结果复用同样依赖视图稳定性；在更动态的 DAVIS 数据集上，SSA 仍然有效，但只能跳过 `13%` 的帧。最后，用户研究虽然结果很强，但样本量仍然偏小，静态场景实验只有 7 名参与者，动态场景 A/B 只有 4 名参与者。

## 相关工作

- _Recasens et al. (ECCV '18)_ — Learning to Zoom 提出了基于显著性的可学习重采样，而 SOLO 把显著性替换成 AR 场景中的视线条件采样。
- _Thavamani et al. (ICCV '21)_ — Fovea 同样利用非均匀采样，但目标是自动驾驶导航，不是用户注视驱动的 AR 实例分割。
- _Cheng et al. (CVPR '22)_ — Mask2Former 是强大的全场景分割基线，而 SOLO 用任务范围收缩换取大幅更低的交互延迟。
- _Liu et al. (TVCG '25)_ — FovealNet 关注的是高效 gaze tracking 本身，SOLO 则把 gaze 作为传感与分割协同设计的控制信号。

## 我的笔记

<!-- 留空；由人工补充 -->
