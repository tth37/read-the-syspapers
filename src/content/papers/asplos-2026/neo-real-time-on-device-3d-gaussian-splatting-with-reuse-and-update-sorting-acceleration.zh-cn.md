---
title: "Neo: Real-Time On-Device 3D Gaussian Splatting with Reuse-and-Update Sorting Acceleration"
oneline: "Neo 复用前一帧每个 tile 的 Gaussian 排序结果并做增量修补，再配合专用排序硬件，把高分辨率 on-device 3DGS 推进到实时范围。"
authors:
  - "Changhun Oh"
  - "Seongryong Oh"
  - "Jinwoo Hwang"
  - "Yoonsung Kim"
  - "Hardik Sharma"
  - "Jongse Park"
affiliations:
  - "KAIST, Daejeon, Republic of Korea"
  - "Meta, Sunnyvale, CA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790192"
code_url: "https://github.com/casys-kaist/Neo.git"
tags:
  - hardware
  - gpu
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Neo 的判断是：on-device 3D Gaussian Splatting 真正卡住的已经不再主要是 rasterization，而是每一帧都把每个 tile 的 Gaussian 列表从头重排。它的做法是沿用前一帧的有序表，只做增量修补，并为这种 reuse-and-update 流程设计专门的排序加速器。在论文评估的场景上，这足以显著降低 DRAM traffic，并把 QHD 渲染推进到实时区间。

## 问题背景

论文面对的是一个很典型的 AR/VR 约束：高分辨率 view synthesis 必须本地执行，因为云端渲染延迟太高；但 wearable 或 edge-class 设备的带宽预算又很紧。已有 3DGS 系统，尤其是 GSCore，已经显著优化了 rasterization，但作者证明这主要是在暴露一个新的瓶颈。在 `51.2 GB/s` 内存系统下，GSCore 在 FHD 只有 `31.1 FPS`，在 QHD 更只有 `15.8 FPS`。

更关键的是，单纯加算力并不能解决问题。在同样 `51.2 GB/s` 带宽下，把 GSCore 从 4 个 core 扩到 16 个 core，吞吐只提升约 `1.12x`；而把 DRAM 带宽提升 `4x`，性能却能提升 `3.83x`。这说明限制项不是算术吞吐，而是 memory traffic。论文的 pipeline breakdown 也支持这一点：sorting 最多占到 GPU traffic 的 `90.8%`，以及 GSCore traffic 的 `69.3%`。对 on-device 渲染来说，每帧全量重排 Gaussian 的代价太高了。

## 核心洞察

Neo 的核心命题是：3DGS 的 sorting 不该被看成“每帧一次全新的全局排序”，而该被看成“在旧结果上做增量修补”。论文统计六个场景后发现，超过 `90%` 的 tile 会保留前一帧 `78%` 以上的 Gaussian；即便看排序变化最剧烈的 `99th percentile`，位移最大的 Gaussian 也只移动 `31` 个位置。这意味着，前一帧的有序表已经非常接近当前帧的正确答案。

因此，Neo 复用前一帧的 sorted Gaussian table，只修复视角变化带来的局部失真，再插入新进入 tile 的 Gaussian、删除移出的 Gaussian，并在 rasterization 时刷新深度。真正的收益首先来自算法改写：原本带宽开销极重的全局排序，被换成了可以放进片上、只需一次 off-chip pass 的局部修补。

## 设计

Neo 每帧的软件流程有四步：reordering、insertion、deletion 和 depth update。reordering 使用 Dynamic Partial Sorting：系统不再对每个 tile 的 Gaussian table 做全局排序，而是把 `256` 项 chunk 读入片上内存，局部排序后写回一次。为了让 Gaussian 能跨 chunk 边界移动，Neo 每隔一轮把排序边界平移半个 chunk。作者只保留单次 off-chip sorting pass，因为更多 pass 只会线性增加 traffic，而质量收益很小；他们报告这一选择带来的退化低于 `0.1 dB`。

insertion 和 deletion 处理可见性变化。incoming Gaussian 在 preprocessing 阶段识别；outgoing Gaussian 先标记 invalid，再在 merge 时真正删除，从而避免立即搬移后续大量条目。depth refresh 也被折叠进 rasterization：系统在 Gaussian feature 已经被读取时顺手把新 depth 写回 table。代价是排序时使用“滞后一帧”的 depth，但论文报告质量损失可以忽略；同时指出，如果没有这个优化，traffic 会增加 `33.2%`。

硬件结构与数据流相匹配。Neo 包含一个 Preprocessing Engine、一个带 `16` 个 sorting core 的 Sorting Engine，以及一个带 `4` 个 rasterization core 的 Rasterization Engine。其重点不是做一个泛化的“更快排序器”，而是为 reuse-and-update ordering 专门定制整条 pipeline。

## 实验评估

评估使用 Tanks and Temples 中六个场景，在 HD、FHD 和 QHD 三种分辨率下渲染。主要 baseline 是 NVIDIA Orin AGX 64GB 和 GSCore；为了公平比较，论文把 GSCore 也扩展到 `16` 个 core，与 Neo 的 `16` 个 sorting unit 对齐。结果显示，Neo 的优势会随着分辨率提高而变大。跨场景平均来看，它在 HD、FHD、QHD 下分别比 Orin AGX 快 `5.0x`、`8.7x`、`12.4x`，比 GSCore 快 `1.7x`、`3.2x`、`5.5x`；在 QHD 下平均吞吐达到 `97.7 FPS`。

traffic 数据与这一结论一致。渲染 60 帧 QHD 图像时，Orin AGX 平均需要 `360.8 GB`，GSCore 需要 `104.6 GB`，Neo 只需 `19.5 GB`，分别下降 `94.6%` 和 `81.4%`。质量也基本守住：六个场景上的最大 PSNR 下降不到 `1.0 dB`。作者还测试了更极端情形：在 Mill 19 的 Building 和 Rubble 大场景上，Neo 仍有 `72.9 FPS` 的平均吞吐；在更快相机运动下，也能在实验设置中保持高于 `60 FPS`。这些实验基本对准了论文主张的目标区间，因此说服力是足够的。

## 创新性与影响

相对于 _Lee et al. (ASPLOS '24)_，Neo 的新意不在于再做一个以 rasterization 为中心的 3DGS 加速器，而在于指出：当 rasterization 已经优化后，sorting 会成为新的主瓶颈。相对于 _Feng et al. (ISCA '25)_，Neo 不采用持续消耗带宽的 background sorting，而是对当前帧的 table 做增量修补。相对于 _Wu et al. (MICRO '24)_ 和 _Ye et al. (HPCA '25)_，它更像互补方案：那些工作优化 3DGS 栈中的其他阶段，而 Neo 专注于带宽敏感的排序路径。它最可能留下来的贡献，是把 3DGS acceleration 重新定义成一个围绕 sorting path temporal similarity 展开的系统问题。

## 局限性

Neo 明显依赖 temporal coherence。视角变化越剧烈，复用得到的旧排序就越不准确，算法也越可能需要几帧时间才能重新收敛。评估范围本身也有边界：硬件结果来自 simulator 与 RTL synthesis，而不是实硅；论文也没有覆盖模型压缩、双目渲染整合，或完整头显部署链路里的全部问题。

## 相关工作

- _Lee et al. (ASPLOS '24)_ — GSCore 通过 hierarchical sorting 和 subtile rasterization 加速 3DGS，而 Neo 进一步指出 sorting traffic 会成为下一瓶颈，并用 temporal reuse 取代逐帧全量重排。
- _Feng et al. (ISCA '25)_ — Lumina 也利用 neural rendering 中的 temporal redundancy，但它依赖 background sorting；Neo 则用增量式的原位修补来避免持续带宽争用。
- _Wu et al. (MICRO '24)_ — GauSPU 面向 SLAM 场景下的 3DGS acceleration，核心在 sparsity-aware rasterizer；Neo 的重点则是 view synthesis 里的 sorting overhead。
- _Ye et al. (HPCA '25)_ — Gaussian Blending Unit 复用的是 edge GPU 上的 rasterization 工作，而 Neo 复用的是 Gaussian ordering，因此两者是互补关系。

## 我的笔记

<!-- empty; left for the human reader -->
