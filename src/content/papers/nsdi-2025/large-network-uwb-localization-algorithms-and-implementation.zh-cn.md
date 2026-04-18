---
title: "Large Network UWB Localization: Algorithms and Implementation"
oneline: "Locate3D 把 UWB 的 range 与 AoA 联合进优化，再用 MST 选边和 rigidity decomposition，在大规模对等网络里更快完成 3D 定位与定向。"
authors:
  - "Nakul Garg"
  - "Irtaza Shahid"
  - "Ramanujan K Sheshadri"
  - "Karthikeyan Sundaresan"
  - "Nirupam Roy"
affiliations:
  - "University of Maryland, College Park"
  - "Nokia Bell Labs"
  - "Georgia Institute of Technology"
conference: nsdi-2025
category: wireless-cellular-and-real-time-media
tags:
  - networking
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Locate3D 是一个 peer-to-peer 的 UWB 定位系统，它把 angle-of-arrival 当成一等拓扑约束，而不是只做 range fitting 时顺手丢掉的信息。通过联合优化 range 与 angle、只采样低不确定性的边、并对非刚性区域做修复，它把定位延迟最多降低 `75%`（`4.2x`），同时在 32 节点楼宇部署中做到 `0.86 m` 的 3D 中位误差，在带 15 个 anchor 的 100,000 节点仿真中做到 `12.09 m` 的中位误差。

## 问题背景

论文的出发点是现代 UWB 硬件能力与主流大规模定位算法之间的错位。range-only 的 multidimensional scaling 之所以长期流行，是因为 pairwise distance 容易测，而且不要求很重的基础设施。但这类方法需要很多边、收敛慢，而且通常只能恢复位置。更关键的是，它直接浪费了新一代商用 UWB 阵列在同一次交互里就能给出的 azimuth 和 elevation 信息。

这种浪费在作者关心的场景里尤其昂贵，例如无人机编队、资产追踪标签、楼宇里的应急响应者，以及未来的车联网或蜂窝协同网络。在这些环境中，节点会移动，连通性不完整，遮挡常见，更新延迟与最终精度同样重要。如果系统每一轮都要重测一个很稠密的图，或者强依赖密集 anchor，实际部署就会变得太慢或者太脆弱。

看似自然的替代方案是多模态定位，例如把 UWB 和 VIO 结合起来。论文认为，对于超大规模部署，这不是一个好的默认选项，因为不同用户和环境之间的相机质量、光照与标定条件并不一致。Locate3D 因此选择 RF-first 的单模态路线：优先仅靠 peer-to-peer UWB 测量恢复 3D 位置与朝向，只在基础设施存在时再机会式地利用它。

## 核心洞察

核心判断是：一条经过精心选择的 UWB 边，比传统的 range-only 边信息量大得多，因为它同时携带 range、azimuth 和 elevation 三个约束。只要优化器能稳定利用 angle 信息而不陷入糟糕的局部极值，那么系统就可以用远少于 range-only 方法的采样边数来恢复一个大图。

但这件事只有和另外两个观察结合起来才真正成立。第一，真正有价值的边不是任意边，而是那些预测不确定性更低、几何条件也更适合测角的边，所以选边问题可以转化为一个基于 uncertainty weight 的 minimum spanning tree。第二，即便一个 spanning tree 连通，它也仍然可能是 flexible 的，因此系统还必须显式检查 rigidity，并通过子图分解和关键边把它修补成唯一可实现的拓扑。

换句话说，Locate3D 之所以有效，是因为它先用 angle 把可行几何空间大幅收紧，再用图算法把有限的测量预算花在最值钱的约束上。

## 设计

Locate3D 的算法主体可以拆成四块。第一块是联合 range-angle 的目标函数。它不再只优化欧氏距离误差，而是加入一个基于 negative cosine 的角度损失项。论文对这个设计给了充分动机：如果直接在 arctangent 表达式上做平方角度误差，目标面会高度 non-convex，局部极值非常多；而 cosine 形式更平滑，并且把角度损失限制在有界范围内。与此同时，range loss 在和 angle loss 合并前会先被归一化，避免距离量级过大把 angle 的梯度完全淹没。

第二块是 optimal edge selection。论文指出，在 `n` 个节点的 3D 图里，range-only 方法大致需要 `3n-4` 级别的约束，而同时带有 range、azimuth、elevation 的一条边可以更高效地约束节点。因此 Locate3D 使用 Kruskal 算法构造 MST，边权来自一个估计的不确定性面积：边越短、方差越小、越像 LOS、越有可靠 angle，成本就越低。第一次迭代属于 cold start，需要较广泛地测邻居；后续迭代则复用上一轮拓扑估计，只挑下一批最值得测的边。

第三块处理的是“连通不等于可定位”。商用 UWB 阵列的 angle field of view 有限，所以某些 AoA 在 broadside 附近会严重失真，或者干脆缺失。Locate3D 先依据传感器 FoV，再结合可用的 inertial rotation 信息，对可疑 angle 做过滤。随后它在 distance 与 angle 约束上构造 rigidity matrix，通过接近零的 eigenvalue 和对应位移向量识别 rigid subgraph，并记录连接不同子图的 critical edges，供后续轮次在不重测整张图的前提下重新把这些区域拼起来。

第四块是参考系对齐和 anchor 集成。原始 AoA 是在每个节点自己的局部坐标系里上报的，因此双向测量必须先被旋转到一个公共全局坐标系。Locate3D 利用成对 azimuth 与 elevation 观测之间的互补几何关系，求解 roll、pitch 和 yaw 偏移；如果 IMU 已经提供了 roll 与 pitch，则只需要再解 yaw。anchor 在这个系统里是可选增强而不是硬依赖。static anchor 会让 MST 更偏向带全局坐标的节点，而“virtual anchor”则允许基础设施摄像头把高置信度用户临时注册为 anchor，再把这些信息注入整张图。

## 实验评估

实现上，作者使用 Raspberry Pi 3、NXP SR150 UWB 板卡和 Intel Realsense T261，UWB 采样频率为 `20 Hz`。论文报告了 32 个节点、超过四小时的真实数据，并用 20,000 条实测 UWB 交互拼接出 city-scale 仿真。对于一篇同时强调算法与系统性的论文，这种“真实部署 + 大规模仿真”的组合是合理的。

在 room-scale 实验里，Locate3D 的中位绝对误差达到 2D `18 cm`、3D `30 cm`。更重要的是，它在 `Cappella` 失效的场景里仍然稳定：更暗的光照不会影响 RF 测量，静止节点也能正常定位，因为系统并不依赖 odometry tail。在 LOS 与 NLOS 对比中，3D 中位误差只从 `31 cm` 上升到 `39 cm`，说明过滤与选边逻辑确实在抑制噪声，而不只是把误差平均掉。

楼宇级实验是最有说服力的真实部署证据。32 个节点跨多层楼、完全不依赖基础设施 anchor 时，Locate3D 报告 `0.86 m` 的 3D 中位定位误差和 `4.5°` 的平均朝向误差。论文还把基于 AprilTag 的 ground truth 路径和 motion capture 做了对比校验，因此这个楼宇结果要比单纯仿真更可信。

大规模结果则把系统的可扩展性边界说得很清楚。在带 15 个 anchor 的 `100,000` 节点仿真中，中位误差是 `12.09 m`；只有一个 anchor 时则升到 `21 m`。在一个大约 `22 km x 3.2 km` 的纽约市 wide-area 仿真里，`100,000` 节点在 1 个和 5 个 anchor 下的中位误差分别是 `82.31 m` 和 `34.19 m`。这些数字显然不是导航级别的结果，但足以支撑论文的中心论点：这种方法可以扩展到极大的 peer graph。ablation 也和论文主张高度一致：直接加 raw angles 会明显降延迟但伤精度，过滤后精度恢复，rigidity 会以少量额外延迟换来唯一实现，而完整的 `Range+Angle+MST` 组合则在保持接近 range-only 精度的同时给出最大的延迟收益。

## 创新性与影响

这篇论文的新意不在于“UWB 可以测角”，这件事在硬件层和更早的系统里已经存在。真正的贡献是把 AoA 从头到尾当成图约束来设计一个完整的定位栈：目标函数、选边策略、刚性修复、参考系对齐，全部围绕这个能力展开。和依赖 VIO 轨迹去拼接稀疏 UWB range 的 `Cappella` 相比，Locate3D 保持了 RF-centric 设计，因此在黑暗环境和静止用户上依然成立。和从基础设施 anchor 做三角定位的 `ULoc` 相比，Locate3D 则把 peer-to-peer 约束向外传播，所以在 anchor 稀疏或超出覆盖范围时仍能工作。

因此，这篇论文同时会被几类人引用：做 localization substrate 的系统研究者、需要低基础设施依赖协同定位的 robotics/XR 构建者，以及决定 UWB 传感器能力该如何暴露给上层的硬件与平台设计者。它既提出了新机制，也给出了新的系统 framing：大规模网络定位不该被看成单纯的 range fitting，而应被看成受约束的图构造问题。

## 局限性

这个系统还不是一个真正的实时分布式实现。原型能够在线采集数据，但主要在 Matlab 里离线处理，所以论文更强地证明了算法可行性与测量质量，而不是完整的部署成熟度。作者自己也在 discussion 里承认，如果要进一步改善高移动性场景下的最坏延迟和鲁棒性，需要引入带本地 leader 的半分布式实现。

Locate3D 也高度依赖 AoA 质量，而当前 COTS UWB 硬件的有效 FoV 仍然偏窄，在 broadside 附近还有明显偏差。过滤逻辑和可选的惯性信息可以缓解这个问题，但无法消除底层硬件限制。如果 angle 质量继续下降，系统就会退化回更接近 noisy range-only 的工作状态。

最后，大规模精度仍然停留在米级到几十米级，并且会随着 anchor 数量显著改善。cold start 仍然需要广泛测邻居；如果多个子图长时间彼此远离，漂移问题仍可能累积；virtual anchor 机制在几十秒尺度内也只能注册一部分可见用户。因此，这篇论文更应该被理解为一个可扩展的 peer-localization substrate，而不是一个已经彻底解决的 turnkey 导航系统。

## 相关工作

- _Grosswindhager et al. (SenSys '18)_ - `SALMA` 用单个 anchor 加 UWB multipath assistance 解决小规模定位问题，而 Locate3D 面向的是 anchor-optional 的大规模 peer-to-peer 3D 定位。
- _Stocker et al. (IPSN '19)_ - `SnapLoc` 关注围绕基础设施的大量 tag 的超快 UWB 室内定位，而 Locate3D 关注的是 ad hoc 网络中的 uncertainty-aware 选边与 rigidity 维护。
- _Zhao et al. (IMWUT '21)_ - `ULoc` 依靠密集 UWB anchor 和 AoA 三角定位达到厘米级结果，而 Locate3D 用更少的基础设施换取稀疏 anchor 条件下更广的覆盖能力。

## 我的笔记

<!-- 留空；由人工补充 -->
