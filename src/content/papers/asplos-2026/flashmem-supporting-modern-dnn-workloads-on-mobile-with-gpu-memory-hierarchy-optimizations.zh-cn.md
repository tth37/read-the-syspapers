---
title: "FlashMem: Supporting Modern DNN Workloads on Mobile with GPU Memory Hierarchy Optimizations"
oneline: "FlashMem 用离线生成的权重流式计划、纹理内存友好布局和流水化 kernel，替代整模型预加载，在手机 GPU 上以更低内存运行更大的 DNN 工作负载。"
authors:
  - "Zhihao Shu"
  - "Md Musfiqur Rahman Sanim"
  - "Hangyu Zheng"
  - "Kunxiong Zhu"
  - "Miao Yin"
  - "Gagan Agrawal"
  - "Wei Niu"
affiliations:
  - "University of Georgia"
  - "University of Texas at Arlington"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790164"
tags:
  - ml-systems
  - gpu
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FlashMem 用离线生成的权重流式计划，替代“先把整模型装进内存”的传统做法。再加上面向纹理内存的布局和无分支流水化 kernel，它让手机 GPU 能以更低内存占用运行更大的单模型与多模型负载，并降低端到端延迟。

## 问题背景

论文面向的是一个越来越常见的移动端现实：应用会在短时间内串行调用多个体量不小的模型，或者运行单个已接近手机内存上限的大模型，但主流移动框架仍然默认在推理前预加载全部权重。作者在 OnePlus 12 上给出的数据很直接：MNN 跑 Whisper-Medium 时峰值内存达到 4,077 MB，跑 SD-UNet 时达到 4,858 MB，而且加载与权重转换的时间往往比真正推理还长。

简单做流式读取也不够。移动 GPU 上，权重要经过磁盘、unified memory、texture memory 这条多级路径，不同算子对“边算边搬数据”的容忍度又很不一样。Softmax、LayerNorm 很容易被拖慢，而 MatMul 能隐藏更多加载工作。真正的问题不是“要不要流式”，而是“该在什么层流式哪些权重块，才能既省内存又不把吞吐打垮”。

## 核心洞察

FlashMem 的核心观点是，移动 GPU 上的权重流式执行只有在系统知道“每一层还能承受多少额外数据搬运”时才真正有效。因此它把 overlap planning 做成离线优化问题，而不是在线启发式。只要系统知道哪些层还有 load capacity，就能只让模型的一部分权重常驻，在使用前不久再把剩余权重搬入，而不明显拖慢执行。

这之所以可行，是因为约束本身比较规整：lowering 后的执行顺序已知，权重生命周期可知，权重转换可按 chunk 切分，算子类型又能预测其与加载重叠的容忍度。论文真正重要的一步，是把这些因素联合起来求解，而不是各做各的局部优化。

## 设计

FlashMem 主要有三个机制。第一，是 overlap-plan generation。论文在 lowering 后的 DNN 图上定义 `OPG`：决定哪些权重进入预加载集合 `W`、每个权重最早在哪一层前进入 unified memory、以及每一层要把多少 chunk 转成 texture memory。目标函数同时惩罚“预加载过多”和“加载过早导致驻留过久”。实现上作者先用 CP-SAT 建模，再加入带 fallback 的 `LC-OPG`，以避免真实图上求解过慢或直接失效。

第二，是容量估计与自适应融合。FlashMem 将算子分成 elemental、reusable、hierarchical 三类，并用 XGBoost 预测额外数据搬运带来的延迟增长，把结果转成每层的 load-capacity 预算 `C_l`。这些预算直接约束求解器。如果某个 fused kernel 把可插入加载的边界压缩得太少，系统会选择性拆开它；在这里，“更多 fusion”反而可能减少调度自由度。

第三，是让计划能在移动 GPU 上真正执行。FlashMem 把权重重排成更适合 2.5D texture memory 的布局，减少运行时 reshape 和 transpose，然后把 kernel 改写成无分支流水线：每轮循环一边计算当前 tile，一边预取下一 tile 的权重，从而减少 SIMT 分支发散并隐藏纹理内存延迟。

## 实验评估

实验覆盖 11 个模型，任务横跨 NLP、图像分类、图像分割、图像生成、语音识别和视频分割；主平台是 OnePlus 12，并额外测试了三款手机。相对产品级框架，FlashMem 的端到端几何平均加速分别为：相对 MNN `6.1x`、相对 TVM `6.2x`、相对 LiteRT `1.7x`、相对 ExecuTorch `75x`；相对最接近的研究基线 SmartMem，则为 `8.6x`。内存方面，相对 SmartMem 的平均内存降低 `3.5x`，相对 TVM 最多可达 `8.4x`。一个很典型的大模型结果是 GPT-Neo-1.3B：平均内存从 2,667 MB 降到 554 MB，集成延迟从 48,610 ms 降到 3,086 ms。

最能支撑核心主张的有两点。第一，在被测移动 GPU 上，只有 FlashMem 能跑通 GPT-Neo-2.7B。第二，在顺序多模型实验里，它能把执行过程控制在手工设定的 1.5 GB 预算内，而 MNN 在初始化时会反复冲出高峰值。消融实验也和技术故事对得上：单独的 `OPG` 就能带来 `5.3x-8.1x` 的加速和 `2.1x-3.8x` 的内存降低，之后自适应融合和 kernel rewriting 再继续补收益。

不过边界也很明确。FlashMem 衡量的是初始化加执行的整体延迟，因此它最擅长的是冷启动和频繁换模型的场景；论文也指出，同一个模型连续 warm run 大约 3 到 12 次之后，SmartMem 可能会相对更快。

## 创新性与影响

和 _Niu et al. (ASPLOS '24)_ 相比，FlashMem 的关键新意在于把权重驻留时机本身变成一等优化变量，而不是只把 layout transformation 当成主要内存问题。和 _Li et al. (MobiCom '24)_ 相比，它更明确地扎根在移动 GPU 层次化内存与 texture memory 上。和 _Han et al. (MobiSys '24)_ 相比，它关注的是降低大模型加载与转换成本，而不是 preemption 策略。

因此，这更像一篇机制论文，而不只是测量论文。离线规划器、profile 引导的容量模型，以及 kernel 改写路径是互相咬合的，合起来确实扩大了手机可本地运行的模型规模和模型序列。

## 局限性

FlashMem 依赖不少离线工作。求解器在部署前运行，实验中使用的是带 512 GB DRAM 的工作站，并允许最多 150 秒求解，因此 planning 成本并不轻。方法也主要假设图结构静态；作者明确把 dynamic neural networks 留到未来工作。部署层面，实验只覆盖 batch size 1 和 FP16/FP32，因此它与量化模型或更剧烈在线负载波动结合时会怎样，论文没有回答。

多模型部分的适用范围也比较窄。FlashMem 主要针对顺序式或 FIFO 风格的执行，而不是更复杂的可抢占场景。对卷积占比高的模型，它的收益也更小，因为相应的权重转换没有那么容易与计算充分重叠。

## 相关工作

- _Niu et al. (ASPLOS '24)_ — SmartMem 的重点是消除很多纹理布局转换，而 FlashMem 在这条线上继续前进，引入离线 overlap planning、选择性拆融合和流水化 kernel 流式加载。
- _Li et al. (MobiCom '24)_ — FlexNN 同样关注受内存限制的边缘推理，但主要面向移动 CPU 上的自适应 slicing/loading，而不是移动 GPU 上面向 texture memory 的执行优化。
- _Han et al. (MobiSys '24)_ — Pantheon 研究的是移动边缘 GPU 上可抢占的多 DNN 推理；FlashMem 则更关注 FIFO 式模型切换路径及其底层内存层次优化。
- _Kwon et al. (SOSP '23)_ — vLLM 说明了 paging 如何降低数据中心 LLM serving 的内存压力，而 FlashMem 把“权重不必全常驻”的思路迁移到移动 GPU，但要面对完全不同的层次结构和 kernel 约束。

## 我的笔记

<!-- 留空；由人工补充 -->
