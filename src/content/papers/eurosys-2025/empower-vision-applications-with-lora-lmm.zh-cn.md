---
title: "Empower Vision Applications with LoRA LMM"
oneline: "VaLoRA 先按精度门槛把外部视觉知识装进少量 LoRA，再用自适应 tiling 和三态调度执行多适配器 LMM，把多任务视觉服务的延迟压到现有 LoRA 系统之下。"
authors:
  - "Liang Mi"
  - "Weijun Wang"
  - "Wenming Tu"
  - "Qingfeng He"
  - "Rui Kong"
  - "Xinyu Fang"
  - "Yazhu Dong"
  - "Yikang Zhang"
  - "Yuanchun Li"
  - "Meng Li"
  - "Haipeng Dai"
  - "Guihai Chen"
  - "Yunxin Liu"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University"
  - "Institute for AI Industry Research (AIR), Tsinghua University"
  - "Shanghai AI Laboratory"
  - "Beijing Academy of Artificial Intelligence (BAAI)"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717472"
code_url: "https://github.com/mi150/VaLoRA"
tags:
  - llm-inference
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

VaLoRA 不是只给 LoRA serving 补一个更快的 kernel，而是把适配器生成、异构批处理和模式切换一起重做，让一个 LMM 能同时承担多种视觉任务。论文在五个任务、三个 LMM 上报告，相比原始未调优模型，准确率提升 24-62%；相比已有 LoRA serving 系统，端到端延迟下降 20-89%。

## 问题背景

今天的视觉应用仍然高度依赖专用小模型链路。LMM 的优势是自然语言接口和更强推理，但落到垂直场景时，往往又不如按域训练的小模型，因此必须用 LoRA 把外部知识补进去。

真正的难点有三层。其一，一个任务一个适配器会让系统很碎，但把太多知识塞进同一个 LoRA 又会伤精度。其二，多个应用并发时，很容易在同一批次里遇到多个异构 LoRA；论文实测，现有 unmerged 方案会额外带来 27-140 ms 延迟。其三，不同应用目标不同，视频分析要低延迟，视觉检索更看吞吐，而 dLoRA 式切换一次就可能花掉 53 ms 以上。

## 核心洞察

作者的核心判断是，视觉场景里的 LoRA LMM 必须把离线知识打包和在线执行策略联动起来做。离线阶段要在不突破精度门槛的前提下，把外部知识压进尽可能少的适配器；在线阶段则要尽量停在 merged 模式，但在异构请求和饥饿出现时，能低成本切到 mixture 或 unmerged。

另一个关键观察是，很多视觉任务根本不需要完整语言生成。如果输出只是有限标签集合，那么把 task head 直接训练进适配器，往往比让 LMM 多轮 decode 更划算。

## 设计

VaLoRA 分成三块。第一块是离线的 accuracy-aware adapter generation。系统从领域数据集或现有小模型收集监督信号，按贪心顺序往一个 LoRA 里持续融合知识；只要某项任务精度跌破门槛，就回滚最后一步并新建适配器。作者把它视为带约束的 bin packing 近似。若任务输出是固定集合，同一个适配器还会顺带训练一个 vision task head。

第二块是 unmerged 路径上的 ATMM。论文认为 Punica、S-LoRA 和 batched GEMM 的共同问题是 tiling 固定化，输入形状一变就会出现 padding、访存放大和 SM 利用率不足。ATMM 在离线阶段 profile 输入形状与 tiling 的最佳对应关系，运行时再按当前 shape 选中预编译 kernel，并用 double buffering 把数据搬运和计算叠起来。

第三块是在线编排器。它的 switcher 只常驻 LoRA 因子 `A` 和 `B`，利用连续内存和一次性全层 `ΔW` 计算，把切换时间压到 10 ms 以内。与此同时，deLoRA 让一个热门适配器继续 merge 在基座模型里，其他请求走修正分支，先减去已 merge 的影响，再加上目标适配器，从而避免每次都为了少量冷门请求切回纯 unmerged。

## 实验评估

实验使用 Qwen-VL-7B、LLaVA-1.5-7B、LLaVA-1.5-13B 和一台 A100 80GB 服务器。工作负载覆盖 ShareGPT-4V、RefCOCO、YODA、Cityscapes、UCF101；对比对象是 Punica、S-LoRA 和 dLoRA。

端到端性能上，视觉检索场景里，VaLoRA 相对 dLoRA、Punica、S-LoRA 的平均 token latency 分别下降 72%、50% 和 20%；视频分析里，由于 task head 去掉了大部分自回归解码，这三个降幅扩大到 89%、83% 和 71%。准确率方面，带 LoRA 的 Qwen-VL 在物体检测、视频理解等强领域任务上，相比原始模型提升 24.5-62.2%；在 visual QA 和 image captioning 上，论文还报告它比对应小模型高 4.3-5%。组件实验也支持机制本身：vision task head 可降 41-63% 延迟，ATMM 比现有算子快 2.3-3.4x，总吞吐从单卡的 6.07 req/s 提升到四卡的 23.97 req/s。保留意见是，论文没有把 VaLoRA 和完整的专用视觉流水线做系统级正面对比。

## 创新性与影响

VaLoRA 的创新不在模型本身，而在把适配器生成、自适应 GPU 批处理、快速模式切换和混合调度合成一套面向视觉应用的 serving 栈。早先的 LoRA serving 工作大多只优化其中一段，或者主要面向文本 LLM。

这篇论文最可能影响统一多模态后端和多租户 LoRA serving。它最实用的一点，是提醒系统设计者：如果任务不需要自然语言输出，就不要为语言生成付费。

## 局限性

论文自己的限制说得很清楚。vision task head 只适合输出集合受限的任务，视觉检索这类自然语言交互场景仍要回到原始 LM head。离线知识融合算法也是启发式，融合顺序和预聚类方式都会影响质量。

实验范围也偏窄。大多数结果仍是单机单卡，多卡扩展只是简单展示；系统对比对象都是 LoRA serving baseline，而不是专用视觉系统全栈。Prefix caching 虽然实现了，但吞吐收益不到 4%。

## 相关工作

- _Chen et al. (MLSys '24)_ - Punica 支持异构 LoRA 的 unmerged 并发执行，而 VaLoRA 进一步指出视觉负载不能长期停在这种高开销路径上，需要 ATMM 和快速模式切换。
- _Sheng et al. (MLSys '24)_ - S-LoRA 也做了大规模并发适配器 serving，但仍以 unmerged 为主；VaLoRA 在此基础上补上自适应 tiling、低开销切换和 mixture mode。
- _Wu et al. (OSDI '24)_ - dLoRA 已经提出在 merged 与 unmerged 之间动态切换，VaLoRA 延续这个方向，但把切换成本压低，并加入 deLoRA 来缓解请求饥饿。
- _Zhou et al. (ATC '22)_ - PetS 面向的是参数高效 DNN 变体服务，而不是自回归多模态 LMM，因此没有处理 VaLoRA 关注的 batching、tiling 和跨模式调度难题。

## 我的笔记

<!-- 留空；由人工补充 -->
