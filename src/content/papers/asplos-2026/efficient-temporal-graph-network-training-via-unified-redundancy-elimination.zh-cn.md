---
title: "Efficient Temporal Graph Network Training via Unified Redundancy Elimination"
oneline: "PULSE 把 TGN 训练里的计算、消息存储和加载冗余统一到最小单元上处理：批内去重、消息按需重建、GPU 缓冲按时间重用。"
authors:
  - "Yiqing Wang"
  - "Hailong Yang"
  - "Kejie Ma"
  - "Enze Yu"
  - "Pengbo Wang"
  - "Xin You"
  - "Qingxiao Sun"
  - "Chenhao Xie"
  - "Zhongzhi Luan"
  - "Yi Liu"
  - "Depei Qian"
affiliations:
  - "Beihang University, State Key Laboratory of Complex & Critical Software Environment, Beijing, China"
  - "Beihang University, Beijing, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790157"
code_url: "https://doi.org/10.5281/zenodo.17945819"
tags:
  - graph-processing
  - ml-systems
  - gpu
  - memory
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PULSE 把 TGN 训练看成一个横跨计算、消息存储和数据加载的统一冗余问题。它只保留最小输入、最小持久状态和最小可复用 GPU 块，其余部分都通过索引精确重建，而不是重新计算。论文在四个数据集、两类 TGN 模型上报告最高 `6.67x` 的吞吐提升，而且精度不变。

## 问题背景

论文讨论的是连续时间 TGN 的标准训练流程：每个 batch 先做时间约束邻居采样，再加载 node memory 和 raw message，执行 memory update 与 temporal attention，最后写回状态。问题不是这条流程本身，而是同一份逻辑信息会在多个地方重复出现。批内很多采样行共享 node ID、edge ID 或 timestamp；raw message 又常常重复了 node memory 和 edge feature 里已经能恢复的信息；跨 batch 的特征访问也存在明显重用，但模式很不规则。

已有系统只优化局部。ETC 和 TGLite 减少部分访问或加载冗余，TGOpt 关注的是 inference 阶段 attention 里的冗余。作者认为这还不够，因为这些瓶颈会互相放大：raw-message 冗余存储会吞掉本可用于缓存的显存，计算冗余又会抬高数据搬运成本。论文在 `wiki-talk` 上测得组件级批内冗余达到 `0.5147-0.9789`，raw-message-store 冗余平均为 `0.8682`，跨 batch 的 node/edge 复用率也常在 `0.3-0.4`。所以真正的问题是：如何在不改变 TGN 语义的前提下，把整条训练链路里的重复工作一起压缩掉。

## 核心洞察

核心命题是：每个阶段都只保留语义上真正不可约的最小单位。PULSE 把它们分别定义为面向计算的 Minimal Input Unit (MIU)、面向消息持久化的 Minimal Storage Unit (MSU)，以及面向显存管理的 Minimal Reuse Unit (MRU)。一旦按这三个单位重写流水线，很多被删掉的数据都可以通过 inverse map、dependency counter 和 buffer indirection 精确恢复，而不是近似恢复。

这比传统 row-wise deduplication 更细。过去只要整行不完全相同，就会整行重算；PULSE 则把路径拆成 node、edge、time 等可复用组件，让冗余在 row-wise 算子之间继续传播，直到真正的聚合步骤才停止。

## 设计

PULSE 的计算去重采用离线加在线的混合方案。正样本跨 epoch 不变，所以先离线去重；负样本在运行时去重后与正样本唯一集合合并，形成当前 batch 的 MIU。随后，Operator-Level Reconstruction 对 row-wise 子算子分别去重，再通过 inverse index map 恢复结果；在 temporal attention 中，完整 `Q/K/V` 行只会在后续乘法真正需要时才物化。

在存储层，PULSE 只保留 MSU，也就是那些仍被 raw message 引用、因此暂时不能丢弃的过期 node-memory 条目。它不做昂贵的一对一依赖跟踪，而是维护 updated / outdated memory 的轻量级引用计数。每个 batch 更新时，只把仍被引用的旧值 spill 到空闲槽位，重写消息索引，其余内容按需重建。

在加载层，PULSE 预留一块软件管理的 GPU buffer，并按固定大小的 MRU 划分，以减少不同特征维度带来的碎片。BlockPool 负责块和槽位管理。其上的 Bipartite Temporal Reuse 把 node-indexed 数据与 edge-indexed 数据分开处理：前者较小，显存允许时尽量常驻；后者太大，则放进一个按时间滑动的窗口里缓存。窗口 stride 负责平衡 miss rate 和替换开销，论文最后选出的最佳值是 `10`。

## 实验评估

实验平台是一台配有 Intel Xeon Gold 6336Y CPU 和 `A100 40GB` GPU 的服务器。模型是 TGN 和 TGAT，配置有四种，通过 batch size（`2000` 或 `6000`）与层数（`1` 或 `2`）组合得到。数据集包括 `lastfm`、`wiki-talk`、`stackoverflow` 和 `gdelt`，基线是 ETC 和 TGLite。

结果很清楚：PULSE 在所有 workload 上都最好，平均相对 ETC 提升 `2.37x`，相对 TGLite 提升 `3.28x`，在 `wiki-talk` 的 `C4` 下对 ETC 的最大加速达到 `6.67x`。ETC 在两层配置 `C2` 和 `C4` 下还会 OOM，而 PULSE 因为同时降低了持久存储占用和 attention 峰值显存，依然能稳定训练。机制层面上，PULSE 平均减少 `64.23%` 的 host-to-device 传输量，以及 `68.91%` 的 temporal operator 处理元素数。ablation 也支持论文主张：最大端到端收益来自 memory-state management（`+134.3%`）和 edge-feature management（`+106.4%`），说明瓶颈确实更偏向数据搬运。精度方面，所有数据集和配置下的 AP/AUC 都与基线一致，因此这组实验足以支持它在单卡 TGN 训练场景里的中心论点。

## 创新性与影响

相对于 _Gao et al. (VLDB '24)_，PULSE 不再停留在局部访问优化，而是把计算、存储和加载统一到同一个精确重建框架里。相对于 _Wang and Mendis (ASPLOS '24)_，它比 TGLite 更像一次深层运行时重写。相对于 _Wang and Mendis (PPoPP '23)_，它把“冗余感知”从 TGAT inference 扩展到了完整 training 流水线。

因此，这篇论文最重要的影响不是提出了新模型，而是给图学习系统提供了一条可复用原则：围绕不可约状态组织 TGN 训练，其余内容按需恢复。

## 局限性

论文只评估了 TGN 和 TGAT，并且硬件只覆盖单台 `A100 40GB` 服务器，所以对更新 GPU 和分布式多 GPU 训练的可移植性仍是开放问题。正样本离线预处理大约要一个 epoch 的 `1.5x`，虽然长训练可以摊销，但短作业未必划算。缓存策略也依赖 stride 和预留 buffer 等工作负载相关参数；如果未来 TGN 的 message 语义更复杂，精确重建是否仍像现在这样便宜，也还有待验证。

## 相关工作

- _Gao et al. (VLDB '24)_ — ETC 通过减少冗余访问和流水化来加速训练，但没有把组件级计算冗余和 raw-message 存储冗余一起纳入统一处理。
- _Wang and Mendis (ASPLOS '24)_ — TGLite 提供的是连续时间 temporal GNN 的轻量框架，而 PULSE 做的是更深层的运行时重构，包括精确重建与定制 GPU 内存管理。
- _Wang and Mendis (PPoPP '23)_ — TGOpt 关注 temporal graph attention inference 的冗余优化；PULSE 延续了“冗余感知”这条线，但把范围扩展到 training 的存储与加载阶段。
- _Dai et al. (ASPLOS '25)_ — Cascade 通过 dependency-aware 方式支持大 batch TGN training，而 PULSE 的重点是消除标准训练流水线内部本就存在的重复工作。

## 我的笔记

<!-- 留空；由人工补充 -->
