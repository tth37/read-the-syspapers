---
title: "EARTH: An Efficient MoE Accelerator with Entropy-Aware Speculative Prefetch and Pattern Reuse"
oneline: "EARTH 将 MoE expert 拆成 base/delta 两段，投机预取高价值 base，并按重要性选择抓取或复用 delta，以减少带宽与推理时延。"
authors:
  - "Fangxin Liu"
  - "Ning Yang"
  - "Jingkui Yang"
  - "Zongwu Wang"
  - "Chenyang Guan"
  - "Yu Feng"
  - "Li Jiang"
  - "Haibing Guan"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Shanghai Qi Zhi Institute, Shanghai, China"
  - "National University of Defense Technology, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790155"
tags:
  - llm-inference
  - hardware
  - caching
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

EARTH 是一套面向带宽受限 MoE 推理的软硬件协同设计。它把每个 INT8 expert 切成 coarse base 和 refinement delta，先大范围投机预取 base，再只在 routed expert 足够重要时抓取或重建 delta。按论文给出的建模结果，这样最多可把 expert 加载流量降低 48%，并把端到端延迟提升到最高 2.10x。

## 问题背景

这篇论文抓住的是 MoE 语言模型部署里一个非常具体、也非常现实的痛点：稀疏激活虽然减少了算术计算，却把内存搬运问题放大了。每个 token 实际只会命中少数几个 experts，但这些 experts 来自一个很大的候选池，于是硬件必须频繁把大块权重从片外内存搬到片上。作者对 Qwen3-30B-A3B 在 DDR5-6400 上的 INT8 推理做 profiling，发现 expert fetching 大约占总周期的 88%，而 gating、expert compute 和 aggregation 加起来还不到 12%。换句话说，MoE 在 FLOPs 上看起来是“省算力”的，在数据移动上却往往是“更重”的。

直觉上的几种办法都各有硬伤。把所有 experts 常驻片上，模型一大就做不到；expert parallelism 可以把内存压力摊到更多设备上，但硬件成本和系统复杂度都会上升；压缩能减小 footprint，但过强的量化或剪枝可能破坏精度，甚至要求额外重训练。已有的 offloading 工作通常把冷 experts 放到更慢的内存层级，再通过预测做 prefetch，可静态或启发式 prefetch 很难跟上动态 routing，既容易浪费有限 buffer，也仍可能在 expert 到得太晚时把流水线卡住。

作者还指出了一个更隐蔽的难点。若想做自适应精度，最直接的方法是同时存多份 expert，比如 INT8 和 INT4 各一份，但这样会把存储和传输开销直接翻倍，在带宽受限场景里反而得不偿失。反过来，如果只保留一份被截断的低精度权重，又会丢掉数值上重要的信息。于是论文真正要解决的问题变成：能不能把 expert 表示成一种“可切片”的格式，让系统在 runtime 里按重要性只搬最需要的那部分，同时还保持实现足够简单、适合硬件执行。

## 核心洞察

论文最核心的论点是：MoE 推理并不要求每个 routed expert 在任何时刻都以完整精度出现。一个 routed expert 可以被拆成两个阶段来对待：紧凑的 base 先承担大部分有效计算，较小的 delta 只在 gating 结果表明这个 expert 足够重要时再补上。只要系统投机预取的是“更多 experts 的 base”，而不是“更少 experts 的完整权重”，它就能在相同 buffer 预算下扩大 prefetch 覆盖面，并把 miss 的代价压到更低。

这个想法之所以成立，是因为作者同时利用了两种规律。第一，gating 历史对下一 token 的 expert 选择具有一定短期局部性，因此可以做有意义的 speculative prefetch。第二，权重的低阶修正部分会反复出现相似的 base-delta 组合，很多 delta 不必每次都从 DRAM 原样抓取。EARTH 把这两点合在一起：总是预取预测 expert 的 base；高重要性 expert 取真实 delta；低重要性 expert 直接跳过 delta；中等重要性 expert 则通过一个小 LUT 在片上复用或重建 delta。它把“该抓哪个完整 expert”这个问题，改写成了“这个 expert 当前值不值得完整精度”。

## 设计

EARTH 的第一步是 dual-entropy encoding。对一个 INT8 expert，它把每个权重拆成 4-bit 的高位 base 和 4-bit 的低位 delta。论文把这种划分描述为一种硬件友好的折中：它保留了可组合的算术结构，访问仍然是字节对齐的，也能和常见 PE 数据宽度自然对接。更重要的是，它把 expert 变成了“可以分段搬运”的对象。base 可以被广泛预取，也可以单独参与近似计算；delta 则从必选负载变成按需补充。

speculative prefetcher 利用 gating layer 的 routing history 预测接下来可能会被选中的 experts，并把它们的 base 放进片上的 FIFO buffer。等真实 routing 结果出来后，EARTH 分三种情况处理。若 prefetch hit 且该 expert 很重要，就抓取真实 delta，保证完整精度；若 hit 但重要性低，就完全跳过 delta，只用 base 计算；若 prefetch miss，则只加载正确 expert 的 base，因此 miss 惩罚远小于抓整份 expert。论文说这些重要性阈值会离线校准，以便把跳过 delta 带来的质量变化控制在大约 1% baseline perplexity 以内。

当 base-only prefetch 把第一层瓶颈缓解后，delta 流量会反过来成为新的瓶颈。EARTH 的第二个关键机制 pattern reuse，就是专门应对这个“瓶颈转移”。作者离线统计主导性的 `<base, delta>` 组合，把它们编码进 LUT，并声称即使模型规模变化，主导模式也通常只有几十种。运行时，对于 gating weight 落在中间区间的 experts，系统不再从 DRAM 抓取真实 delta，而是用已经拿到的 base 去查 LUT，在片上重建一个预测 delta。这个 “match and action” 路径，是 EARTH 相比普通 base-only prefetch 最大的区别。

相应的硬件结构也是围绕这种表示法组织的。EARTH 有一个 16-PE 的 compute core、分 bank 的 weight/token buffers、带 top-k selector 的 gating module、负责 LUT 式 delta 重建的 weight dispatcher，以及 output-stationary dataflow。实验部分固定的片上存储规模是 16 MB weight buffer 和 1 MB token buffer。主控制器把 on-chip load、weight dispatch、activation dispatch、PE compute、accumulation 和 write-back 做成流水，使 delta decoding 可以和计算重叠，而不是顺序串行地堵在后面。

## 实验评估

这篇论文的实验在架构研究语境下算比较完整，但主体仍然是建模和综合，而不是实测硅片。作者用 Verilog RTL 实现了 EARTH，在 TSMC 28 nm、250 MHz 下做综合，用 CACTI 7 建模 SRAM，再用一个按 RTL 时序校准的 cycle-accurate simulator 跑端到端结果。测试模型包括 Mixtral-8x7B-Instruct、Qwen1.5-MoE-A2.7B 和 DeepSeek-V2-Lite-Chat，数据集则使用 CNN/DM 与 LongBench Gov_report。比较对象包括 EdgeMoE、AdapMoE、DAOP、HybriMoE 和 APTMoE。

最核心的结果是端到端加速。跨三个模型，EARTH 报告了 1.56x-2.10x 的延迟改进，其中 Mixtral 上收益最高。论文还给出了 compute-transfer overlap ratio，为 86%-91%，这点很重要，因为它说明系统的主要价值确实是把 memory stall 隐藏掉，而不只是减少一点算术工作量。作者还把实际速度与“理想完全重叠”的上界做了对比：Mixtral 达到理想值的 90.5%，Qwen 为 93.2%，DeepSeek 为 94.0%。这组数据和论文的中心论点是对得上的。

准确率与带宽之间的折中也讲得比较清楚。当配置把 80%-90% 的 experts 保留在 important 桶里时，论文报告整体 loading demand 可以减少 20% 以上，而 Rouge-L 几乎不变。对 DeepSeek，更激进的配置仍能把 load reduction 推到 40% 以上；结论部分则总结为总体 memory traffic 最多可下降 48%。ablation 也比较有帮助：只有 naive prefetch 时速度提升只有 1.12x；加上 speculative base prefetch 后到 1.52x；再加上完整的 delta reuse 后，报告值达到 2.06x。这个渐进过程能比较直接地说明每个组件在补哪一段瓶颈。

能耗与面积结果也让设计更完整。在 DeepSeek-V2-Lite-Chat 上，EARTH 的总能耗是 AdapMoE 的 0.59x，并且比 EdgeMoE 低 21.54%。综合后的芯片面积是 27.52 mm2，其中 PE array 占 77.55%，新增的 LUT 与 control logic 只占 6.08%。这支持了作者的说法：delta reuse 这部分逻辑相对计算阵列来说并不贵。我的保留意见是，论文把多个异构 baseline 都映射到作者自己的归一化建模栈里，因此“总体趋势”很有说服力，但精确到某个百分比的跨系统差距，仍然要结合这种比较方式来看。

## 创新性与影响

和 _Hwang et al. (ISCA '24)_ 这类通过更早预测 experts 来加快 MoE inference 的工作相比，EARTH 的新意在于它不只是更早知道“要抓谁”，而是先把被抓的 payload 本身缩小成 base/delta，再用硬件路径恢复需要的精度。和 _Zhang et al. (DATE '25)_、_Wei et al. (SC '24)_ 这类围绕 CPU/GPU 内存层次优化 offloading 的工作相比，EARTH 更像一个彻底的 accelerator co-design：权重表示、prefetch 策略和 datapath 是一起决定的。和 _Sarkar et al. (ICCAD '23)_ 这样的视觉 MoE FPGA 加速器相比，EARTH 明显更聚焦于 LLM 风格的 expert 权重搬运，而不是只做任务级稀疏性。

因此，这篇论文大概率会被两类人引用。第一类是做 accelerator architecture 的研究者，他们会把它看作“不是一味加带宽，而是让表示法配合内存调度”的一个例子。第二类是做 MoE serving 或 MoE inference runtime 的系统研究者，他们会从中得到一个启发：expert importance 与 partial-fidelity execution 可以是很有价值的调度信号，而且这种思想并不一定只属于软件层。就论文类型来说，它更像一篇实打实的新机制论文，而不是单纯的 profiling 或 benchmark 论文。

## 局限性

EARTH 依赖若干离线前提。important / moderate / unimportant 的阈值和 reuse LUT 都需要提前校准，因此跨模型、跨量化格式、跨部署目标的迁移并不是零成本的。这个设计还默认 routing history 足够稳定，能够支撑 speculative prefetch，也默认主导性的 base-delta 模式足够稳定，值得做 LUT reuse；论文没有特别深入地分析极端非平稳或对抗性 routing 场景。

实验范围也比标题给人的想象更窄。它主要关注的是单加速器上的推理，不涉及分布式 expert parallelism、多租户 serving，或训练阶段。准确率部分主要用 Rouge-L 等下游任务指标来反映，而不是更完整的一组 serving 质量指标；同时，论文没有给出 fabricated prototype 或真实部署系统，只做到 RTL 加综合加仿真。最后，4/4 划分被论证为务实且硬件友好，但论文并没有证明它在更宽的量化选择上仍然是最优的。

## 相关工作

- _Hwang et al. (ISCA '24)_ — Pre-gated MoE 通过更早预测 experts 来提升推理速度，而 EARTH 进一步把被投机搬运的 payload 缩成 base-delta 两段。
- _Zhang et al. (DATE '25)_ — DAOP 依赖 CPU/GPU offloading 与 predictive pre-calculation；EARTH 则假设专用 accelerator，并通过片上重建与复用来打同一个带宽瓶颈。
- _Wei et al. (SC '24)_ — APTMoE 优化的是带宽受限 GPU 节点上的 expert loading；EARTH 则把权重格式与 datapath 一起设计给资源受限 accelerator。
- _Sarkar et al. (ICCAD '23)_ — Edge-MoE 是面向视觉任务的 MoE FPGA accelerator，而 EARTH 针对的是 LLM 风格 expert offloading，并把 expert-fetch latency 当作首要瓶颈。

## 我的笔记

<!-- 留空；由人工补充 -->
