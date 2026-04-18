---
title: "CLM: Removing the GPU Memory Barrier for 3D Gaussian Splatting"
oneline: "CLM 只把视锥裁剪所需属性常驻 GPU，把其余 Gaussian 状态卸载到 CPU，并用流水、缓存和重排在单张消费级 GPU 上训练大场景 3DGS。"
authors:
  - "Hexu Zhao"
  - "Xiwen Min"
  - "Xiaoteng Liu"
  - "Moonjun Gong"
  - "Yiming Li"
  - "Ang Li"
  - "Saining Xie"
  - "Jinyang Li"
  - "Aurojit Panda"
affiliations:
  - "New York University, New York, NY, USA"
  - "Pacific Northwest National Laboratory, Richland, WA, USA"
  - "University of Washington, Seattle, WA, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790140"
code_url: "https://github.com/nyu-systems/CLM-GS"
tags:
  - gpu
  - memory
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CLM 把大场景 3D Gaussian Splatting 的训练重新表述为“GPU 只维护当前工作集”的问题，而不是“GPU 必须容纳整个模型”。它让视锥裁剪必需的属性常驻 GPU，把其余 Gaussian 状态放到 CPU pinned memory，并结合 microbatch 流水、重用感知缓存和视图重排，尽量把传输与 CPU Adam 的代价藏在渲染计算后面。

## 问题背景

这篇论文要解决的是 3DGS 很现实的一道扩展性门槛：场景越大、细节越多，想要高质量重建就需要越多 Gaussian，但模型状态的增长速度远快于单卡显存能承受的范围。每个 Gaussian 有 59 个可训练参数，而训练时还要额外保存梯度和 Adam 状态。作者据此估算，仅模型状态就需要 `N x 59 x 4 x 4` 字节，因此 24 GB 的 RTX 4090 在还没算 activation 和临时 buffer 之前，大约只能容纳 2600 万个 Gaussian。

这对大场景远远不够。论文列出的例子里，Rubble 需要 4000 万个 Gaussian、约 50 GB；Alameda 需要 4500 万个、约 60 GB；Ithaca 需要 7000 万个、约 80 GB；MatrixCity BigCity 更是达到 1 亿个、约 110 GB。现有办法大致只有三类：用多 GPU 分摊显存、对 Gaussian 做剪枝/层次化压缩、或者把场景切成多个子区域分别处理。它们分别带来更高硬件成本、潜在画质损失，或边界拼接与调参复杂度。至于“把全部状态每步都从 CPU 搬到 GPU”的朴素 offload 方案，也同样不理想，因为它既保留了与模型大小成正比的 GPU 内存需求，又叠加了大量 PCIe 传输和 CPU Adam 开销。

## 核心洞察

CLM 最核心的洞察是，3DGS 训练其实足够稀疏，GPU 并不需要同时看到整张场景。每个视角只会访问其 frustum 内的 Gaussian，而在大场景里，这个工作集相对于全模型是极小的。论文在 MatrixCity BigCity 上测到，平均每个 view 只访问全部 Gaussian 的 `0.39%`，最大也只有 `1.06%`。一旦接受这个事实，offloading 就不再是通用虚拟内存式的“缺页再搬运”，而是一个结构化的系统设计问题：先算出活跃集合，只搬活跃集合，再把流水线维持住。

第二层洞察是，这种稀疏访问并不是随机的。相邻视角常常会重用大量相同 Gaussian，而一个 Gaussian 在一个 batch 内的“最后一次被访问”也往往能提前判断。CLM 正是同时利用这两点：相邻 microbatch 之间的重叠访问减少传输量，而“最后一次使用”则让 CPU 端 Adam 可以在整个 batch 结束前就开始处理部分参数。这样做的结果不是单纯“显存省一点”，而是把通信和优化器工作转化为可以被后续 GPU 渲染隐藏的一部分后台开销。

## 设计

CLM 首先把 Gaussian 属性分成两类。selection-critical attributes，也就是 frustum culling 必须使用的 position、scale 和 rotation，会对所有 Gaussian 常驻 GPU；这部分只占 59 个 float 里的 10 个。其余 non-critical attributes，例如颜色相关的 spherical harmonics 和 opacity，则放在 CPU pinned memory 中，只有当某个 Gaussian 真正进入当前视角 frustum 时才加载到 GPU。这样一来，frustum culling 本身不需要先把整份模型搬到 GPU。

在此基础上，CLM 把训练重构成以单张图像为单位的 microbatch 流水。系统先执行 pre-rendering frustum culling，显式算出每个 microbatch 的 in-frustum 集合 `S_i`，然后只把这些 Gaussian 送入 rasterization kernel，而不是像传统实现那样对全部 Gaussian 扫一遍、再在 kernel 内部隐式忽略大多数无关项。为了高效搬运这些稀疏分布的参数，CLM 实现了 selective-loading kernel，直接从 pinned CPU memory 收集所需参数；对应的 gradient-store kernel 则把梯度写回 CPU，并在相邻 microbatch 都会使用同一 Gaussian 时做梯度累加。

真正让流水有效的是三项优化。第一，precise Gaussian caching 会把 `S_i ∩ S_{i+1}` 直接从当前 microbatch 的 GPU buffer 复制到下一个 microbatch，因此跨 PCIe 传输的只有不重叠部分。第二，overlapped CPU Adam 会先计算每个 Gaussian 在当前 batch 中最后一次被访问的 microbatch，只要某个 Gaussian 的梯度已经最终确定，就立刻在 CPU 上做 Adam 更新，而不是等整个 batch 完成。第三，pipeline order optimization 会重排视图顺序，使相邻 microbatch 的工作集重叠尽可能大。论文把这个排序问题表述成以 symmetric difference 为距离的 Traveling Salesman Problem，并用局部搜索近似求解。实现上，CLM 基于 Grendel 扩展，结合 gsplat 的 rasterization kernel，使用独立 CUDA stream 和 double buffering 去重叠加载、计算、梯度写回和 CPU Adam。

## 实验评估

实验设计与论文主张基本是对齐的。作者选了五个在规模、分辨率和稀疏性上差异明显的场景，并在两个平台上测试：`RTX 4090 + PCIe 4.0` 与 `RTX 2080 Ti + PCIe 3.0`。基线也比较公平：GPU-only baseline 是单卡模式的 Grendel 加 gsplat；enhanced baseline 额外引入了 CLM 的 pre-rendering frustum culling；naive offloading baseline 则同样使用 pinned memory、CPU Adam 和 gradient accumulation，从而把比较重点落在 CLM 的调度与传输设计上，而不是工程底座差异。

最醒目的结果是可训练模型规模。以 BigCity 为例，在 RTX 4090 上，enhanced GPU-only baseline 大约在 `18.4M` Gaussian 处触发 OOM，naive offloading 能到 `46.0M`，而 CLM 可以训练到 `102.2M`；在 RTX 2080 Ti 上，CLM 也能做到 `47.0M`，而 enhanced baseline 只有 `7.7M`。这种规模提升直接换来了质量提升：BigCity 上，CLM 把 PSNR 从 GPU-only 极限 `15.3M` 模型的 `23.93` 提升到 `102.2M` 模型的 `25.15`。性能方面，CLM 相对 naive offloading 有 `1.38x-1.92x` 的加速；与 enhanced baseline 相比，在较慢的 2080 Ti 上保留了 `86%-97%` 的吞吐，在更快的 4090 上保留 `55%-90%`。消融实验也和机制叙述吻合：CLM 相比 naive offloading 将通信量减少了 `37%-82%`，而基于 TSP 的排序在所有排序策略里都得到最低的传输量。综合来看，这些结果有力支撑了论文的中心论点：CLM 的关键价值不只是节省显存，而是把原本根本训不动的模型规模变成可训练，从而实实在在提高重建质量。

## 创新性与影响

和 _Zhao et al. (ICLR '25)_ 这类多 GPU 扩展方案相比，CLM 的创新点在于它把 CPU memory 变成单 GPU 训练的有效模型容量，而无需改变 3DGS 表达方式。和 _Kerbl et al. (TOG '24)_ 及其他层次化/剪枝方法相比，CLM 并不通过压缩场景来适配显存，而是通过重排数据放置、传输和执行顺序来保持 fidelity。和 _Lin et al. (CVPR '24)_ 这类场景分区方法相比，它保留一份全局场景表示，因此避免了跨分区拼接带来的不连续性。

这让 CLM 同时对两类读者有价值。对实践者来说，它提供了一条在 commodity hardware 上训练更大 3DGS 场景的可行路径。对系统研究者来说，这篇论文则是一个很典型的 workload-specific offloading 例子：它成功的原因不是照搬通用虚拟内存，而是抓住了 frustum 稀疏性、视角空间局部性以及 batch 内“最后一次访问”这些 3DGS 特有结构。具体机制未必能直接套到所有模型上，但这种分析方法很可能能迁移到其他稀疏的 differentiable rendering 流水线上。

## 局限性

CLM 并不是“显存无限化”。它仍然要把所有 Gaussian 的 selection-critical attributes 留在 GPU 上，所以最终上限依然受 GPU 显存约束，只是常驻集合比完整模型小得多。系统还依赖较大的主机内存与 pinned memory；即便是 BigCity，论文报告的 pinned RAM 也已经达到数十 GB。当前实现基于 CUDA，并依赖 pinned-memory DMA 与多 stream 重叠，尽管论文认为设计思想本身可以迁移。算法层面上，TSP 式重排在文中的 batch 规模下开销很小，但 batch 继续增大后，这部分代价未必还能忽略。最后，实验重点放在训练吞吐与重建质量，而不是端到端交互式推理延迟；这一点是我根据实验内容做出的归纳，不是作者明确写出的限制。

## 相关工作

- _Kerbl et al. (TOG '23)_ — 提出了 3D Gaussian Splatting 及其 densification 训练流程，而 CLM 保留该学习框架，只改变 Gaussian 状态的驻留位置。
- _Zhao et al. (ICLR '25)_ — Grendel 通过多 GPU 扩展 3DGS 训练，CLM 则用单 GPU + CPU offload 来跨越同一条显存墙。
- _Lin et al. (CVPR '24)_ — VastGaussian 通过场景分区处理大场景，CLM 则保持单一全局场景表示，避免分区边界不一致。
- _Kerbl et al. (TOG '24)_ — hierarchical 3D Gaussians 通过改变表示本身来压缩内存，而 CLM 主要优化的是数据放置与传输方式。

## 我的笔记

<!-- 留空；由人工补充 -->
