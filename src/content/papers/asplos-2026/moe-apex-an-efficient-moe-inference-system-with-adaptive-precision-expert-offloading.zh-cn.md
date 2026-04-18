---
title: "MoE-APEX: An Efficient MoE Inference System with Adaptive Precision Expert Offloading"
oneline: "MoE-APEX 在 expert miss 时按重要性选择高精度、低精度或跳过，并把这一决策贯穿到预取和缓存，显著降低边缘设备上的 MoE 推理延迟。"
authors:
  - "Peng Tang"
  - "Jiacheng Liu"
  - "Xiaofeng Hou"
  - "Yifei Pu"
  - "Jing Wang"
  - "Pheng-Ann Heng"
  - "Chao Li"
  - "Minyi Guo"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "The Chinese University of Hong Kong, Hong Kong, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790187"
tags:
  - llm-inference
  - memory
  - caching
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

MoE-APEX 是一个面向内存受限边缘设备的 MoE expert offloading 系统，它把 expert precision 变成运行时决策。每次发生 cache miss，系统都会根据 gating output 选择高精度、低精度或跳过，并让预取和缓存都感知这件事。论文的核心结论是：MoE 推理真正卡住的不是计算，而是 expert loading。

## 问题背景

这篇论文针对的是一个很具体的部署瓶颈。MoE 模型虽然每个 token 只激活少量 experts，但完整 expert 集合仍然大到装不进边缘 GPU。以 Mixtral-8x7B 为例，每个 token 实际只激活 14B 参数，但完整模型要保存 45B 参数，总存储需求达到 87 GB。现有 expert-offloading 系统一般把 non-expert weights 和少量 hot experts 留在 GPU，把其余 experts 放到 CPU 内存或 SSD，按需拉取。

问题是，这种办法只解决容量，不解决延迟。论文测得，Mixtral 的单个 336 MB float16 expert 在 Jetson Orin 上加载一次，大约是 GPU 计算时间的 20 倍、non-expert processing 的 5 倍。时间分解进一步表明，expert loading 占了 RTX 4090 上 85.8% 的总时间，在 Jetson Orin 上占 88.1%。因此，仅靠 prefetching 很难把这部分 stall 藏住；过去方案要么继续忍受高 miss latency，要么激进地 skip experts 并承担精度损失。

## 核心洞察

论文的核心判断是：不是每一次 cache miss 都值得同样处理，因为不同 experts 对当前 token 的重要性并不相同。gating output 本身就是一个廉价的在线重要性信号。作者进一步证明，gating weight 的幅度与 expert 对最终输出的真实贡献高度相关，在 Mixtral-8x7B 上给出了 0.99 的相关系数。于是，系统可以在 miss 发生时决定：这个 expert 应该高精度拉取、低精度替代，还是直接跳过。

更重要的是，作者没有把这件事只做成一个局部优化。一旦 miss handling 变成 precision-aware，prefetching 和 caching 也必须变成 precision-aware。MoE-APEX 因此把 miss-time loading、future-layer prediction 和 cache replacement 一起围绕 miss cost 来设计。

## 设计

MoE-APEX 由三个协同组件组成。第一层是 token 级的 Dynamic Expert Loader。它先按归一化后的 gating magnitude 对当前 top-k experts 排序，再计算 cumulative score。系统使用两个阈值 `T1` 和 `T2`：第一个 expert 永远保持高精度；较不重要的 experts 允许用低精度版本替代；最不重要的一小部分可以直接跳过。对 Mixtral-8x7B，作者选择的阈值把选择结果大致分成 67% 高精度、30% 低精度和 3% 跳过。低精度版本使用 int2，相比 float16 最多可把加载代价缩短 8 倍。

第二层是 layer 级的 Adaptive Expert Predictor。它利用 transformer 相邻层 hidden state 与 gating input 的高度相似性来预测后续层的 experts。论文报告说，下一层 top-1 expert 的预测准确率大约为 96%，向前看两层或三层时平均也还有约 90%。为了避免逐层计算多个 future gating modules 的线性开销，MoE-APEX 把它们堆叠起来，在 GPU 上一次性并行计算，然后预取预测到的 experts，并暂时保护它们不被驱逐。

第三层是 sequence 级的 Cost-aware Cache Manager。作者没有直接沿用 LFU，而是提出 Least Costly Used (LCU)。LCU 分别统计每个 expert 的高精度和低精度使用频率，并按不同 precision 的加载代价加权，再叠加 recency 与 layer-distance 信号。它的核心不变量是：缓存应优先保留未来 miss 代价最高的 experts，而不是只看总使用次数。原型系统在 `Llama.cpp` 之上增加了大约 8,500 行 C/C++ 代码。

## 实验评估

实验覆盖了三类内存受限平台上的四个 MoE 模型：Jetson Orin 与 RTX 4090 上测试 Mixtral-8x7B 和 Phi-MoE，RTX 2080 Ti 上测试 DeepSeek-MoE 与 DeepSeekV2-Lite。比较对象包括 Transformers、DeepSpeed-Inference、Llama.cpp、MoE-Offloading、MoE-Infinity、AdapMoE 和 Fiddler，但不同平台能运行的 baseline 并不完全相同。主要指标是 prefill latency 和 decoding throughput，测试基本都采用 batch size 1。

最重要的结果是，MoE-APEX 在 prefill 和 decode 两端都稳定领先。Jetson Orin 上，相对 Llama.cpp，Mixtral-8x7B 与 Phi-MoE 的平均 decoding speedup 分别达到 12.0x 和 18.57x，prefill latency 分别下降 78% 和 80%；相对 MoE-Infinity，这两个模型的平均 decoding speedup 仍有 3.36x 和 9.75x，prefill latency 分别降低 58% 和 72%。在 RTX 4090 上，它也继续领先最强的 MoE-specific baseline AdapMoE，Mixtral-8x7B 与 Phi-MoE 的平均 decoding speedup 分别为 1.34x 和 1.59%。在 RTX 2080 Ti 上面对 DeepSeek 两个模型时，它相对最佳 baseline 仍有 1.49x 和 1.68x 的 decoding speedup。

机制级实验基本支持这条因果链。mixed precision 在 GSM8K、ARC 与 TruthfulQA 上带来的精度下降都不超过 1%。dynamic loading 单独拿出来看，可贡献 1.22x 到 1.53x 的加速。prefetching 能把 prefill latency 再压低约 10%，而 misprediction overhead 低于总延迟的 1%；LCU 相比 LFU 可把 miss penalty 再降低 2.36% 到 3.10%。我认为这些证据对单请求 edge inference 场景已经比较有说服力，但并没有真正覆盖更复杂的多租户 serving。

## 创新性与影响

和 _Hwang et al. (ISCA '24)_ 相比，MoE-APEX 的关键区别在于把 precision 本身也变成 miss-time 的调度对象，而不只是预测该预取什么。和 _Zhong et al. (ICCAD '24)_ 相比，它主张低精度替代往往比直接跳过更稳妥。和 _Yu et al. (DATE '25)_ 相比，它给出的不是单点 CPU assistance，而是对 loading、prefetching 与 caching 的一体化改造。

因此，这篇论文最可能影响的是试图在笔记本、嵌入式 GPU 或小型 edge server 上部署 MoE 模型的工程团队，以及研究模型 offloading 与 edge inference 的系统研究者。它真正的贡献不是新的模型结构，而是把 adaptive precision 提升为 offloading 的一等系统控制旋钮。

## 局限性

这篇论文的适用范围比标题看上去要窄一些。它依赖预先生成好的低精度 expert 副本，也需要足够的 CPU 内存或 SSD 来存放这些副本；作者给出的额外存储开销达到模型大小的 12% 到 16%。此外，实验几乎都围绕 batch size 1 展开，因此对连续多请求 serving 的说明仍然有限。

系统里还有一些较强的部署假设。阈值需要按模型 profile，predictor 也依赖跨层高相似性，因此它对新架构的可迁移性更多是经验性展示，而不是严格保证。不同平台上的 baseline 覆盖并不一致，因为若干已有系统在 Jetson 上并不易运行。最后，论文证明了平均精度损失很小，但没有深入分析长尾输入或极端 gating 分布下 importance estimate 是否仍然稳定。

## 相关工作

- _Hwang et al. (ISCA '24)_ — Pre-gated MoE 通过预测未来 expert 使用来重叠加载，而 MoE-APEX 在此基础上进一步加入了 adaptive-precision miss handling 和 precision-aware cache policy。
- _Zhong et al. (ICCAD '24)_ — AdapMoE 倾向于直接跳过低重要度 experts；MoE-APEX 则把低精度替代当作更温和、通常也更保精度的中间路线。
- _Yu et al. (DATE '25)_ — DAOP 更依赖 CPU 侧的预测性计算；MoE-APEX 主要关注如何降低 expert movement 本身的代价。
- _Kwon et al. (SOSP '23)_ — PagedAttention 解决的是 dense LLM serving 的内存管理问题，而 MoE-APEX 面向的是 MoE 模型里 sparse experts 的放置与拉取。

## 我的笔记

<!-- 留空；由人工补充 -->
