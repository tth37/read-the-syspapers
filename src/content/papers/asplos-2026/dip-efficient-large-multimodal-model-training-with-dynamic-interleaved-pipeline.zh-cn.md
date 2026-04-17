---
title: "DIP: Efficient Large Multimodal Model Training with Dynamic Interleaved Pipeline"
oneline: "DIP 通过按模态拆分专属流水段、把批次细分为模态子微批并异步搜索调度，在动态多模态负载下提升大模型训练吞吐。"
authors:
  - "Zhenliang Xue"
  - "Hanpeng Hu"
  - "Xing Chen"
  - "Yimin Jiang"
  - "Yixin Song"
  - "Zeyu Mi"
  - "Yibo Zhu"
  - "Daxin Jiang"
  - "Yubin Xia"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University, Shanghai, China"
  - "StepFun, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790154"
tags:
  - llm-training
  - ml-systems
  - scheduling
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

DIP 把多模态训练中的不平衡问题前移到 partitioning 层面处理，而不是只靠后端调度去补救。它先把不同模态拆到各自专属的 pipeline segment，再把 batch 细分为按模态划分的 sub-microbatch，并为每个 batch 异步搜索调度。论文在五个 12B-94B 模型上报告，相比已有系统最高可提升 97.3% 的训练吞吐。

## 问题背景

问题来自结构异构性和批次异构性的叠加。一个 LMM 往往同时包含 image encoder、language backbone、diffusion decoder 和 modality adapter，它们的算子类型和延迟曲线差异很大。即使先不看数据，仅模型结构本身就会让 pipeline partitioning 很难平衡：作者在一个 37B vision-language 模型上的穷举实验表明，即便把 layer split 全部枚举一遍，stage latency 仍有 16.7% 的差异，在 Megatron-LM 的 `1F1B` 调度下会额外产生 22.8% 的 bubble overhead。

真实多模态训练数据会继续放大这种失配。按 sequence length 做 packing 也无法真正消除不平衡，因为图像更多的 batch 主要压到视觉路径，而文本更多的 batch 主要压到语言路径。论文报告，在一个 text-to-video 设置里，即使经过 packing，最重的 batch 计算量仍是最轻 batch 的 4.15 倍；带动态数据的 7B VLM 相比固定预算的单模态基线会多出 40.3% 的开销。此前关于 variable-length LLM training 的方法大多默认负载变化会近乎均匀地作用于所有 layer，而多模态训练并不是这样。

## 核心洞察

论文最重要的命题是：动态不平衡不能只靠 scheduler 在后面兜底，而应该先从流水线结构本身把它削弱。如果把代价差异很大的模态混在同一个 pipeline segment 里，这种延迟失配就是结构性的，再好的排序也无法真正消除。DIP 因此先做 separated partitioning，让每种模态拥有专属的 pipeline segment。

接着，它把一个 microbatch 再拆成按模态划分的 sub-microbatch，让较慢的 image 或 video 模块可以执行多个更短的小阶段，从而把 stage latency 调整到更接近 backbone stage 的尺度。由于每个 batch 的模态混合都不同，调度必须在线生成；但搜索被放到空闲 CPU 核上异步完成，避免卡住 GPU 主路径。

## 设计

DIP 由离线 partitioning 和在线 planner 两部分组成。离线阶段，它会对每个 modality module 的不同 sub-microbatch size 做 profiling，选择那个仍能保持至少 95% 峰值 GPU 效率的最小尺寸。随后测量各模态的延迟，按比例分配 pipeline segment 数量，再把 layer 放到 `P * K_i` 个 model chunk 上。

在线阶段首先做 metadata prefetch，提前拿到下一批数据的 token 数、image 数等元信息。接着 sub-microbatch partitioner 会把每种模态的工作拆成 `M_i = ceil(N_i / B_i)` 个 sub-microbatch，并生成相应的 forward 和 backward pipeline segment。这样，一个原本不均匀的 batch 就被转换成许多更细粒度的调度单元。

调度搜索器分三步工作。第一步是用 Monte Carlo Tree Search 给 pipeline segment 分配优先级。第二步是 greedy pipeline-stage interleaving：当两类 stage 都可调度时尽量模仿 `1F1B`，否则就选择最早能够开始的 stage 去填 bubble。第三步是 per-layer memory optimization：系统先为每个 stage pair 预计算若干 memory-saving candidate，再解一个小规模近似 ILP，在显存约束下尽量压低时延。

论文还实现了两个支撑组件。一个是 operator-level simulator，用 FLOPs、内存访问量和通信量估计 stage latency 与 memory usage；另一个是对 Megatron-LM runtime 的扩展，让中心 planner 能把动态生成的 action list 下发给 worker。整个搜索过程并行跑在 CPU 核上，并限制最多只占机器一半的 CPU 核。

## 实验评估

实验覆盖五个 12B 到 94B 的模型，包含三个 vision-language 配置和两个 text-to-video 配置。主实验运行在 64 张 H800 GPU 的集群上，另有一个 16 张 H20 GPU 的小集群用于和 FSDP 做对比。基线包括 Megatron-LM、为了公平而在 Megatron-LM 内复现的 `nnScaler*`，以及适用场景下的 Optimus。

总体结果很强。论文在真实数据集上对 100 次 iteration 取平均后发现，DIP 在 VLM 任务上相比基线提升 15.6%-76.2%，在 T2V 任务上提升 36.6%-97.3%。在 H20 集群的 VLM-S 配置中，DIP 比 Megatron-LM 快 27%；而 FSDP 只比 Megatron-LM 慢约 3%，说明主要收益确实来自 DIP 的计划与调度。Ablation 也很清楚：VLM-S 上的 iteration time 从 26.13 秒一路降到 16.05 秒，总体提升 62.8%。

最能支撑论文中心论点的是动态负载实验。当 batch 中的平均图像数升高时，Megatron-LM 在第 6 个 iteration 上比 DIP 慢 52.9%；`nnScaler*` 和 Optimus 虽然有所缓解，但仍比 DIP 慢 10.4%。sub-microbatch study 也验证了作者强调的平衡点：更小的图像块会降低调度对排序的敏感度，但小到 8 以下时会让 GPU 利用率下降，而 size 12 在他们的设置里最优。planner 本身也较实用。随着 microbatch 数增加，DIP 的搜索时间仍控制在 10 秒以内，而 Z3 和 Gurobi 在搜索规模超过大约 10 个 microbatch 后就会在 30 分钟以上超时。需要注意的是，面向 3k-16k GPU H100 集群的结果来自 simulator，而不是完整实机训练。

## 创新性与影响

相较于 _Jiang et al. (EuroSys '24)_，DIP 的新意不只是为 variable-length 输入动态打包，而是明确把 modality-specific imbalance 当作一等问题来建模，并围绕它重构 pipeline。相较于 _Feng et al. (ATC '25)_ 和 _Wang et al. (ASPLOS '25)_，它关注的是每个 batch 随输入变化而在线重生成 schedule，而不是面向固定任务集合的较静态方案。

因此，这篇论文最可能影响的是正在昂贵 GPU 集群上训练 frontier multimodal model 的系统团队。它的贡献既是一个新的调度机制，也是一种新的问题表述：在 LMM 训练里，真正该被平衡的单位不是整个 multimodal microbatch，而是按模态切开的工作段。

## 局限性

DIP 很依赖 profiling 以及 simulator 的准确性。论文展示了经过校准后 simulator 的平均准确率可达 97.6%，但这也意味着系统会持续背负建模误差，以及在新硬件、新 kernel 或新模型结构上重新 profiling 的维护成本。该设计还默认下一批数据的 metadata 足够早可得，便于异步规划，并且默认 model chunk 一旦放置完成，在训练过程中不会迁移。

实验虽然覆盖了多种模型，但部署范围仍有限。大多数真实执行都发生在最多 64 张 GPU 的集群上，而 3k-16k GPU 的结果是模拟得到的。部分基线比较也是在 Megatron-LM 内复现原系统思路，而不是完整端到端运行原始系统。最后，DIP 只优化固定 DP/TP/PP 计划内部的 pipeline scheduling，并不联合搜索完整并行空间。

## 相关工作

- _Jiang et al. (EuroSys '24)_ - DynaPipe 优化的是 variable-length multi-task training，而 DIP 处理的是不会均匀打到所有 layer 的模态不平衡。
- _Feng et al. (ATC '25)_ - Optimus 通过利用 bubble 加速 multimodal LLM training，而 DIP 进一步加入按模态拆分的 partitioning 和按 batch 在线生成的调度。
- _Wang et al. (ASPLOS '25)_ - Spindle 面向预定义任务集合上的 multi-task training，而 DIP 关注单个多模态流水线里的动态输入混合。
- _Jeon et al. (ASPLOS '25)_ - GraphPipe 将 pipeline execution 推广到 DAG 调度；DIP 更专注于 multimodal transformer 的在线搜索。

## 我的笔记

<!-- 留空；由人工补充 -->
