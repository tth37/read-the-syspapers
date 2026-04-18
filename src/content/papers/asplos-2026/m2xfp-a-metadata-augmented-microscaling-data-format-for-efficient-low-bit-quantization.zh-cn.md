---
title: "M2XFP: A Metadata-Augmented Microscaling Data Format for Efficient Low-bit Quantization"
oneline: "M2 XFP 只额外增加每元素 0.25 bit 元数据，就能离线细化权重尺度并在线保护激活最大值，显著缩小 MXFP4 的精度损失。"
authors:
  - "Weiming Hu"
  - "Zihan Zhang"
  - "Haoyan Zhang"
  - "Chen Zhang"
  - "Cong Guo"
  - "Yu Feng"
  - "Tianchi Hu"
  - "Guanglin Li"
  - "Guipeng Hu"
  - "Junsong Wang"
  - "Jingwen Leng"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Shanghai Qi Zhi Institute, Shanghai, China"
  - "Computing Product Line, Huawei, Shanghai, China"
  - "Computing Product Line, Huawei, Beijing, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790185"
tags:
  - hardware
  - llm-inference
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

M2 XFP 的核心判断是：4-bit microscaling 的主要问题不是 FP4 天生不够，而是 MXFP4 会把每个 block 里最关键的值量化坏。为此，它把一小笔元数据预算分成两条路径来用：静态权重走离线搜索后的 subgroup scale refinement，动态激活走在线 top-1 保护。这样做把有效精度维持在 4.5 bit，却把论文报告的精度损失相对 MXFP4 降低了 70.63%，同时仍然保持轻量的 systolic-array 硬件实现。

## 问题背景

这篇论文针对的是一个已经被工业界广泛接受、但在 4-bit 上暴露明显精度问题的路线。像 MXFP4 这样的 microscaling 格式已经被 NVIDIA、AMD 和 Microsoft 的加速器支持，因为它们让反量化非常简单：一组低比特值共享一个紧凑 scale，数据通路就能做得又快又省面积。但问题在于，这个共享 scale 往往采用 E8M0 这种二次幂格式。在 4-bit 精度下，scale 的粒度太粗，常常无法和 block maximum 对齐，结果是组里最大的值先被严重舍入，随后整组误差都被放大。

已有补救方法各有明显代价。像 NVFP4 那样改用 FP8 shared scale，虽然提高了 scale 精度，却缩小了数值范围，还需要额外 rescaling。像 ANT、M-ANT 这类自定义数值类型虽然表达能力更强，但如果要把同样思路用于动态激活，就需要昂贵的在线类型选择和更复杂的解码器。另一些依赖重元数据的工作能修补部分 outlier，却引入了明显的控制开销。作者因此把问题重新表述为：在不破坏 MX 硬件效率叙事的前提下，能否用极少量的 metadata 把主要精度损失补回来？

## 核心洞察

论文最重要的洞察是，metadata 的最佳使用方式在 weights 和 activations 上并不对称。在固定 shared scale 下，最有效的做法是给每个 subgroup 中最关键的元素补额外 mantissa，因为这能直接打到 block maximum 的主要误差源上。但一旦允许离线搜索，subgroup-level 的 scale refinement 会变得更强，因为系统可以联合选择更好的 shared scale 和更好的 metadata 配置。

因此，追求“统一的一种 metadata 策略”本身就是错误目标。权重是静态的，可以承受离线搜索，所以更适合用 subgroup-level extra mantissa 去细化 subgroup scale。激活是动态生成的，对延迟敏感，所以更适合一个确定性的在线策略：先找到每个 subgroup 的 top-1 元素，再只给这个元素补 mantissa。论文把这两个组成部分分别称为权重侧的 `Sg-EM` 和激活侧的 `Elem-EM-top1`，两者合起来就是 M2 XFP。

## 设计

论文先给 metadata 分配方式建立了一套统一分类。metadata 可以表现成 extra mantissa 或 extra exponent，也可以作用在单个元素上，或者作用在 subgroup 的 shared scale 上，于是得到 `Elem-EM`、`Elem-EE`、`Sg-EM`、`Sg-EE` 四类方案。作者随后用相对 FP16 的均方误差，以及把 scale 与 metadata 摊薄到每个元素后的 equivalent bit width 来比较这些方案。在这条 Pareto 前沿上，extra exponent 从来没有真正变成最优选择；真正有效的是 extra mantissa。

M2 XFP 的最终配置使用 group size 32、subgroup size 8。对 weights，每个 subgroup 分到 2 个 metadata bit，用来把 subgroup scale 细化到 `{1.0, 1.25, 1.5, 1.75} x S` 中的一个；如果启用 adaptive shared scale，还允许 group exponent 带上 `-1`、`0` 或 `+1` 的 bias。这个搜索成本对静态权重是可以接受的，但对运行时激活就太贵了。对 activations，在线量化器先计算 group shared scale，把整组先量化成基线 FP4，再在量化域里找出每个 subgroup 的 top-1 元素，然后仅对这个元素补 2 个 mantissa bit。这个编码过程中还要做 bias 和 clamp，确保保护后的值高 4 位仍与原始 FP4 编码一致；否则，被“保护”的元素在替换后反而可能不再是 subgroup 最大值。

硬件支持也刻意做得很克制。整个加速器只新增三个专用单元：top-1 decode unit、增强版 FP4 x FP4 processing element，以及流式 quantization engine。decode unit 用小型 LUT 加比较树，在每个 subgroup 中确定唯一最大值并在并列时固定选最低下标；PE 把带扩展 mantissa 的激活拆成基线 FP4 值和一个小修正项，前者走原本的 MAC 路径，后者走轻量辅助路径；权重侧的 subgroup-scale refinement 则通过 shift-and-add 实现，不需要完整乘法器。存储布局也保持规则化：每个 group 对应一个 128-bit 的 4-bit 数据块、一个 8-bit shared scale，以及 8 bit metadata。

## 实验评估

实验同时覆盖算法精度和硬件代价。精度方面，作者测试了 LLaMA-2 7B、LLaMA-3 8B/70B、OPT-6.7B、Mistral-7B、Falcon-7B，在 Wikitext 和六个 zero-shot 任务上评估；还用 DeepSeek-R1-Distill-Qwen 1.5B 与 7B 跑了 AIME、MATH-500、GSM8K、GPQA、LiveCodeBench 等 reasoning benchmark。硬件方面，他们扩展 DNNWeaver，在 28nm、500 MHz 条件下综合新增逻辑，并与 MicroScopiQ 以及 MX 化改写后的 ANT、M-ANT、OliVe 做对比，所有方案都使用相同的 `32 x 32` PE 组织。

最关键的精度结果是 7B/8B LLM 套件上的平均精度损失。MXFP4 相对 FP16 的平均 accuracy loss 为 `5.38%`，而 M2 XFP 把这个数字降到 `1.58%`，论文据此报告相对 `70.63%` 的下降。与同样有效 4.5 bit 的 NVFP4 相比，M2 XFP 也把平均 loss 从 `2.52%` 降到 `1.58%`，对应 `37.30%` 的改进。Wikitext perplexity 也反映了同样趋势，例如 LLaMA3-8B 从 `8.30` 降到 `6.84`，LLaMA3-70B 从 `4.84` 降到 `3.56`。在 reasoning 模型上，效果依然明显：DeepSeek-R1-Distill-Qwen-1.5B 的平均分从 MXFP4 下的 `36.91` 提升到 M2 XFP 的 `44.44`，更接近 FP16 的 `49.03`。

硬件结果同样有说服力，不过它们是基于建模和综合，而不是流片实测。相对于当时最强的 MX accelerator MicroScopiQ，M2 XFP 平均报告最高 `1.91x` speedup 和 `1.75x` energy reduction。新增的 top-1 decode unit 与 quantization engine 在全系统里只贡献 `0.26%` 的面积开销和 `0.36%` 的功耗开销，而 PE tile 规模也仍与 MXFP4、NVFP4 处在同一量级。整体来看，这组实验比较好地支撑了论文的主张：这些额外 metadata 不只是把模型精度补回来，而且没有把 MX 原本的吞吐和能效优势还回去。

## 创新性与影响

和 _Rouhani et al. (ISCA '23)_ 的 shared microexponents 相比，M2 XFP 的新意不只是“再加一些 metadata”，而是系统性地证明：在这个 4-bit 区间里，把 bit 预算花在 mantissa refinement 上，比花在 exponent refinement 上更值。和 _Ramachandran et al. (ISCA '25)_ 相比，M2 XFP 追求的是更小的控制开销，以及一条对 activations 足够干净的在线路径。和 _Guo et al. (MICRO '22)_、_Hu et al. (HPCA '25)_ 这类以 datatype 设计为中心的工作相比，这篇论文则明确主张：对动态推理张量来说，改变基础数据类型并不是最合适的重心。

因此，这篇论文会同时影响两个方向的人。对 accelerator architect 来说，它给出了一条保留 MX 风格硬件简洁性的 W4A4 精度改进路线。对量化研究者来说，它传达的更一般结论是：当 shared-scale 设计已经接近收敛时，metadata 的放置位置和语义，可能比再发明一种 4-bit 数据类型更重要。

## 局限性

这篇论文最现实的限制在于，权重路径依赖离线 adaptive search，所以完整设计并不能一视同仁地适用于所有张量类别或所有部署流水线。激活路径的确足够轻量，但权重量化路径明确依赖离线校准。实验也主要围绕 GEMM 主导的 linear layers 展开；论文讨论了把方法扩展到 Attention 和 KV cache，但没有在报告的加速器结果里做完整实现。

另外还有两个较窄但重要的边界。第一，硬件结论来自模拟器和综合结果，而不是实际芯片，因此性能和能耗数字距离真实产品仍有一步距离。第二，最终采用的 group size `32` 与 subgroup size `8` 在本文实验中论证充分，但论文没有证明它们在其他模型家族或未来 MX-capable accelerator 上依然最优。

## 相关工作

- _Rouhani et al. (ISCA '23)_ — SMX 给相邻值增加 shared microexponent，而 M2 XFP 认为在 4-bit 区间里，mantissa refinement 是更有效的 metadata 预算。
- _Guo et al. (MICRO '22)_ — ANT 通过改变底层数值类型来提升量化质量，而 M2 XFP 保持 FP4 数据通路不变，把额外表达能力放进 metadata。
- _Hu et al. (HPCA '25)_ — M-ANT 把 adaptive datatype 扩展到 group quantization，但 M2 XFP 认为动态 activations 需要比运行时类型搜索更便宜的在线路径。
- _Ramachandran et al. (ISCA '25)_ — MicroScopiQ 依赖 block-level 结构元数据和混合精度 outlier 处理，而 M2 XFP 追求的是能适配规则 MX 硬件的更低开销 metadata。

## 我的笔记

<!-- 留空；由人工补充 -->
