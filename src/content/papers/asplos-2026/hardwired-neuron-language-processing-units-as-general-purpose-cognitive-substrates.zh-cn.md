---
title: "Hardwired-Neuron Language Processing Units as General-Purpose Cognitive Substrates"
oneline: "把一个 FP4 LLM 直接硬化进金属可编程神经元阵列，用 16 芯片 structured ASIC 消除权重搬运，并把定制化 LLM 推理拉回到可承受的经济区间。"
authors:
  - "Yang Liu"
  - "Yi Chen"
  - "Yongwei Zhao"
  - "Yifan Hao"
  - "Zifu Zheng"
  - "Weihao Kong"
  - "Zhangmai Li"
  - "Dongchen Jiang"
  - "Ruiyang Xia"
  - "Zhihong Ma"
  - "Zisheng Liu"
  - "Zhaoyong Wan"
  - "Yunqi Lu"
  - "Ximing Liu"
  - "Hongrui Guo"
  - "Zhihao Yang"
  - "Zhe Wang"
  - "Tianrui Ma"
  - "Mo Zou"
  - "Rui Zhang"
  - "Ling Li"
  - "Xing Hu"
  - "Zidong Du"
  - "Zhiwei Xu"
  - "Qi Guo"
  - "Tianshi Chen"
  - "Yunji Chen"
affiliations:
  - "State Key Lab of Processors, Institute of Computing Technology, Chinese Academy of Sciences, Beijing, China"
  - "University of Chinese Academy of Sciences, Beijing, China"
  - "University of Science and Technology of China, Hefei, China"
  - "Institute of Software, CAS, Beijing, China"
  - "Cambricon Technologies, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790169"
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

这篇论文的核心主张是：如果一个前沿 LLM 真会长期充当大量应用的共同认知底座，那么我们就不该继续把它的权重当成运行时数据，而应直接把它们做进芯片。论文真正的关键贡献是 Metal-Embedding：把权重编码到高层金属布线拓扑里，而不是编码进异构器件单元，这样大多数 photomask 都能在不同芯片和后续重旋之间共享。基于这一点，作者提出 16 芯片的 HNLPU，把原本几乎不可能落地的硬化方案拉回到更可接受的 NRE、吞吐和能效区间。

## 问题背景

论文抓住的是当前 LLM 硬件一个很难回避的事实：即使已经很专用的 LPU，本质上仍然在反复搬运巨大权重。无论是像 Groq、Cerebras 这样把更多状态放上芯片，还是把 Transformer 数据流做得更硬化的加速器，它们都还是把模型参数当成“运行时要取的数据”。作者认为，这正是为什么即便硬件越来越专用，推理能耗仍然被 memory movement 主导。

于是最自然的极端想法就是把模型直接硬化。理论上，这样可以做到完美的 architecture-model matching，完全消除 parameter fetching，并把数据通路压缩成只做常数运算的电路。问题不在概念，而在经济性。论文估计，如果按最直白的 cell-embedding 方式把 `gpt-oss 120B` 在 `5nm` 上硬化，需要大约 `176,000 mm2` 的计算阵列，拆成 200 多个异构芯片，对应的 photomask 成本就会超过 `$6B`。更糟的是，硬化模型产量不会高，而模型权重还需要周期性更新，这意味着简单硬化从商业上几乎不可接受。

所以真正值得回答的系统问题不是“能不能做一个硬化 LLM 加速器”，而是“能不能保留硬化带来的极致效率，同时把非经常性工程成本降到足以让固定模型推理平台具备经济可行性”。

## 核心洞察

论文最重要的洞察是：朴素硬化之所以贵，不只是因为要存很多常数，而是因为把这些常数存进了错误的物理载体。如果权重值不是体现在异构硅器件单元里，而是体现在金属层的布线拓扑里，那么参数相关部分就能被上移到更便宜、更晚期的金属层，而底下绝大多数工艺层都能在不同芯片、甚至后续重旋之间复用。

这件事成立的关键在于 FP4 只有 16 个离散权重值。HNLPU 的 Hardwired-Neuron (HN) 单元先利用 weight constancy，再用 distributive law 把重复的常数乘法提出来，最后把输入 bit-serialize，使得 accumulation 先于 constant multiplication 发生。计算一旦被改写成 accumulate-multiply-accumulate 的形式，“某个输入该乘哪个权重”就变成了连线问题：把输入信号接到代表权重 `a`、`b`、`c` 等不同值的 accumulator 区域即可。作者的论点是，金属布线拓扑在密度和成本上都比 cell-level embedding 更合适，而这一步才真正把 hardwiring 从“物理上可做”推进到“经济上可能值得做”。

## 设计

Metal-Embedding 分成两层。第一层是 HN 算术单元。与传统 constant-MAC neuron 里“几千个常数乘法器加一个超宽加法树”的结构不同，HN 先按相同权重值把输入归类，对 bit-serialized 输入做 popcount，再只保留 16 个常数乘法器，最后再做一次较小规模的归约。这同时减少了 multiplier 数量和 adder 强度。论文给出的 operator-level 结果是，Metal-Embedding 相比 cell embedding 大约有 `15x` 的密度优势，并把相对 CMAC grid 的面积压缩了 `93.4%`。

第二层是 Sea-of-Neurons，也就是一种 structured-ASIC 思路。参数无关的 HN array 先用共享的 FEOL 和低层 BEOL mask 预制出来，真正跟权重相关的部分只放在 `M8-M11` 这些金属层上按芯片定制。对整体经济性最重要的后果是：整个 16 芯片系统里，`70` 层 mask 中有 `60` 层都能保持 homogeneous，其中还包括所有 EUV 层。论文据此估计，初次 tapeout 的 photomask 成本可下降 `86.5%`，参数更新时的 re-spin 成本可下降 `92.3%`，相对朴素方案总体约为 `112x` 的 photomask 成本缩减。

在此之上，作者实现了完整的 `gpt-oss 120B` FP4 推理系统 HNLPU。16 个芯片通过 CXL 3.0 组成逻辑上的 `4 x 4` 行列互连。所有固定权重投影由 HN array 完成；VEX 单元负责 attention score、RMSNorm、SwiGLU、softmax、residual 和 sampling；片上 `320 MB` Attention Buffer 先承担 KV cache，容量不够时再溢出到 HBM。映射策略也很明确：`Wqkv` 按列组切分，`Wo` 按行组切分，MoE experts 则在芯片间独立分配；router 权重因为只占总权重的约 `0.01%`，所以被直接复制到所有芯片上。系统再把 36 层模型和层内 6 个阶段都串成流水线，在 continuous batching 下最多支持 `216` 个在途 token 或 sequence。

## 实验评估

这篇论文的评测既有 operator-level 的物理实现结果，也有整机级系统建模。RTL 在 `5nm` 下完成综合与布局布线，多芯片 CXL 互连用 CNSim 建模，主系统比较则用 `gpt-oss 120B` FP4 对比 TensorRT-LLM 上实测的 H100，以及结合公开云服务数据校准的 Cerebras WSE-3。

在算子层面，Metal-Embedding 的证据比较直接。对一个代表性的 `1 x 1024` 乘 `1024 x 128` 的矩阵向量乘，ME 的面积大约是传统 MAC 阵列所需 SRAM 块的 `0.95x`，而 cell embedding 需要 `14.3x`。执行周期也显著下降，因为硬化算子可以并行完成乘法，而不必从 SRAM 流式取权重。能耗方面，ME 既避免了 SRAM 访问，又不像 cell embedding 那样承担巨大泄漏，因此优于后两者。

在系统层面，最醒目的数字是 `249,960 tokens/s` 吞吐和 `6.9 kW` 总功耗，对应 `36,226 tokens/kJ`。论文据此给出相对 H100 的 `5,555x` 吞吐提升和 `1,047x` 能效提升，相对 WSE-3 则是 `85x` 和 `283x`。单芯片拆解也很清楚：每颗芯片是 `827.08 mm2`、`308.39 W`，面积和功耗主要都被 HN array 与 Attention Buffer 占据。执行时间分解则显示，一旦权重搬运被拿掉，短上下文场景下最主要的瓶颈变成了 inter-chip CXL communication，而长上下文下 attention 计算重新成为主导。

经济分析和性能分析在这篇论文里几乎同等重要。作者估计 HNLPU 的初始 NRE 为 `$59.25M-$123.3M`，参数更新 re-spin 为 `$18.53M-$37.06M`，在 OpenAI 级部署下三年 TCO 相比等吞吐 H100 集群可下降 `41.7x-80.4x`，碳足迹可下降 `357x`。这些结果确实支撑了论文的主叙事，但也要看到边界：吞吐和功耗来自实现与建模，TCO 结论则依赖部署规模、封装、电价、更新频率等一系列假设，而不是来自已制造成品。

## 创新性与影响

和 _Yu et al. (MICRO '24)_ 的 Cambricon-LLM 相比，HNLPU 的新意不是再做一层更好的大模型 memory hierarchy，而是直接把 model-weight fetch 整件事从系统里删除。和 _Yu et al. (OSDI '22)_ 的 Orca 以及一类 serving-system 工作相比，它不再尝试围绕 memory traffic 做调度，而是主张通过硬件实现彻底消除这类 traffic。和 _Sankaralingam et al. (ISCA '22)_ 的 Mozart 这类专用 dataflow processor 相比，它进一步放弃了大部分可编程性，换来把单一模型当作认知底座的极端专用化。

因此，这篇论文的重要性更多体现在“重新划边界”。它在论证：如果前沿模型部署最终会收敛到少数几个长期存在的模型，那么“general-purpose” 应该从硬件/软件层上移到模型和 prompt 接口层。若这个前提成立，HNLPU 就不只是一个新机制，还是一个带有强经济叙事的体系结构方向；若这个前提不成立，整篇论文最有吸引力的部分也会明显削弱。

## 局限性

这篇论文最大的局限，正是它所依赖的部署前提。HNLPU 只有在某个模型足够稳定、足够值钱、推理量足够大，值得为它支付定制 mask 和数周重旋周期时才成立。这对 hyperscaler 也许可想象，但离普适结论还很远。设计本身也绑定在单一的 `gpt-oss 120B` FP4 配置上，因此一旦架构、量化格式或软件特性变化，代价都会远高于 GPU。

评测也有明显的“面向未来”成分。论文给出了 sign-off 级布局结果和详细建模，但没有 fabricated silicon，因此一些 headline 对比是在“实测 baseline”与“模拟或估算的 HNLPU”之间进行的。最后，作者自己也承认，等权重搬运问题被消掉之后，CXL 通信会变成一等瓶颈；而 LoRA 风格更新、可编程解码、更自动化的设计流等灵活性问题，都还留在 future work 中。

## 相关工作

- _Yu et al. (OSDI '22)_ — Orca 优化的是软件层的分布式 Transformer serving，而 HNLPU 认为主导低效的是权重搬运，并试图用硬件把它直接去掉。
- _Sankaralingam et al. (ISCA '22)_ — Mozart 暴露了可复用的 AI dataflow，但仍然是可编程处理器；HNLPU 则进一步专用到单一硬化模型。
- _Yu et al. (MICRO '24)_ — Cambricon-LLM 用 chiplet 和 hybrid architecture 支持 70B LLM on-device inference，但依然把权重当作 memory 中的数据，而不是金属化结构。
- _Mei et al. (ASPLOS '25)_ — Helix 解决的是 heterogeneous GPU serving 与网络调度，这几乎正好处在与 HNLPU 相反的设计点上。

## 我的笔记

<!-- 留空；由人工补充 -->
