---
title: "TPLA: Tensor Parallel Latent Attention for Efficient Disaggregated Prefill & Decode Inference"
oneline: "把 MLA 重参数化为可张量并行的 decode 注意力，并在 prefill 保留 MLA 形式，从而同时降低每卡 KV 开销、守住精度并改善 TTFT。"
authors:
  - "Xiaojuan Tang"
  - "Fanxu Meng"
  - "Pingzhi Tang"
  - "Yuxuan Wang"
  - "Di Yin"
  - "Xing Sun"
  - "Muhan Zhang"
affiliations:
  - "Institute for Artificial Intelligence, Peking University, Beijing, China"
  - "Tencent Youtu Lab, Shanghai, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790237"
tags:
  - llm-inference
  - gpu
  - caching
  - disaggregation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TPLA 针对的是 `MLA` 在 tensor parallel 推理里的一个具体短板：虽然 `MLA` 本来靠低秩 latent KV cache 节省内存，但一旦把注意力头分到多张 GPU 上，每张卡仍然要持有完整的 latent cache，内存优势会被明显冲淡。论文的做法是把 latent KV 沿特征维切到不同设备上，同时让每个 attention head 逻辑上仍能“看到”完整 latent 信息；再结合 prefill 用 MLA、decode 用 TPLA 的分相策略，把这件事做成可部署的系统路径。结果是在两张 H800 上、`32K` 上下文长度时，DeepSeek-V3-0324 和 Kimi-K2-Base 的 decode 吞吐分别达到 `1.79x` 和 `1.93x` 的加速。

## 问题背景

这篇论文抓住的是模型结构和部署方式之间的不匹配。`MLA` 由 DeepSeek-V2 引入，本质上是把每个 token 的 KV 状态压成一个低秩 latent 向量，因此在单卡 decode 时，KV cache 比标准多头注意力甚至 `GQA` 更省。但在 tensor parallel 场景里，问题出现了：不同 attention head 分散到多张 GPU 上做计算时，每张 GPU 仍然需要完整的 latent 向量 `cKV`。也就是说，随着 TP 度数上升，单卡 KV cache 并不会像大家直觉期待的那样继续下降。论文举了一个很直观的例子：在 `TP=4` 时，LLaMA-3-70B 的 GQA 每卡 KV 维度是 `512`，而 DeepSeek-V3 的 MLA 每卡仍需复制 `576` 维 latent cache。

一个看似直接的修补方案是 `GLA`，也就是把 latent KV cache 本身切开分给不同设备。但论文指出，这种做法虽然改善了系统侧的 KV 开销，却伤到了模型侧的表达能力。因为一旦 head 被分组、每组只接触自己那一份 latent slice，原本应该存在的跨组 query-latent 交互就被消掉了。于是 `GLA` 的代价并不只是“近似了一点”，而是让每个 head 真正失去了一部分表示空间，而且通常还需要从头训练。于是论文要解决的问题就很具体了：既要在 tensor-parallel 推理下减少每卡 KV cache 和内存带宽压力，又要尽量保住 MLA 的精度优势，而且最好能直接加载已有的 MLA checkpoint。

## 核心洞察

这篇论文最值得记住的一点是：`GLA` 那种“省内存就必须牺牲 head 可见的 latent 空间”的权衡并不是必然的。latent KV cache 可以跨设备切分，但不必让每个 head 永久只看见一部分 latent。只要把每个 head 的输入维度也一起切分，而不是把“某些 head 永久绑定到某一块 latent”，那么每个设备都可以在本地 latent shard 上为所有 head 计算一部分 attention 结果，最后再用 all-reduce 把输出合起来。这样一来，每卡 KV cache 下降了，但每个 head 在逻辑上仍然访问了完整的 latent 空间。

真正麻烦的地方在于 `RMSNorm` 和 `softmax`。这两个算子本来都依赖完整 latent 向量上的全局统计量；如果直接切 shard，本地计算看到的只是局部片段，误差就会冒出来。TPLA 的第二层洞察是，先在 MLA 权重里吸收一个正交变换，再去做切分，就能让 shard 上的局部统计更接近全局统计。对于 `RMSNorm`，Hadamard 这种数值均衡型变换效果更好；对于 `softmax`，`PCA` 更合适，因为 softmax 更依赖高方差、信息更集中的维度能否留在前半部分。第三层洞察则是系统层面的：prefill 是 compute-bound，decode 是 memory-bound，所以没必要在两个阶段硬用同一种注意力形式。prefill 保持 MLA，decode 再切到 TPLA，才是更合理的工程答案。

## 设计

实现上，TPLA 建立在论文对 MLA 的吸收式重写之上：key 的上投影被吸收到 query 激活里，value 的投影被吸收到输出投影里。随后，TPLA 把 latent KV 向量沿特征维切到不同设备上，但和 `GLA` 不同，它不会让每张卡只负责一小撮独占 head。相反，每个原始 attention head 都会在每个 latent shard 上保留一份“局部计算视角”，于是各设备分别在本地 latent shard 上算出部分 attention 输出，再通过 all-reduce 合成为最终结果。论文还证明，这可以看成一种“复制了 head 的特殊 `GLA`”，这点很重要，因为它意味着 `FlashAttention-3` 这类成熟 kernel 可以比较自然地复用，TPLA 不需要整套推理栈从零重写。

为了让预训练 checkpoint 可直接转换，论文给了两类重参数化。第一类针对 `RMSNorm`：作者寻找一个正交矩阵 `U`，使得 latent 向量变换后，各 shard 上计算出的局部范数能够近似全局范数。Hadamard 在这里好用，是因为它会把数值幅度尽量摊平，让每一半 shard 的 RMS 更接近整体。第二类针对 `softmax`：这里的目标不是均值意义上的“均衡”，而是让每个 shard 的点积得分更接近完整向量上的得分。论文发现 Hadamard 对这一点帮助不大，而基于校准集做的 `PCA` 更有效，因为它会把更高方差、更重要的信息集中到前部维度。作者再把这些系数吸收到原模型权重里，于是得到一条无需从头训练的 MLA-to-TPLA 转换路径。

真正把论文从“模型改写”推进到“系统设计”的，是 prefill/decode separation。decode 阶段主要受内存带宽限制，所以减少每卡 KV cache 直接转化为吞吐提升；prefill 阶段则主要受算力限制，这时 TPLA 的复制式 head 结构反而不划算。为此，论文提出 `TPLA (pd sep.)`：在 prefill 阶段保留重参数化后的 MLA，而且不切 `RMSNorm` 与 `softmax`；到了 decode 阶段，再切换到 TPLA，并部分复用 prefill 产生的 KV cache。这样既避免了绝大多数 prompt token 上的近似误差，也顺带降低了 `TTFT`。

## 实验评估

实验同时覆盖了精度保真和推理性能。短文本 commonsense 任务上，`GLA` 和 TPLA 的差别非常明显。对 DeepSeek-V2-Lite，原始 MLA 在 WikiText-2 上的 perplexity 是 `6.31`；直接转成 GLA 后飙到 `2212`，而训练自由的 TPLA 只有 `7.24`。在 MMLU、ARC、PIQA、HellaSwag、OpenBookQA、WinoGrande 上也呈现同样趋势：TPLA 相比 MLA 仍有损失，但远小于 GLA，而轻量对齐或 `pd sep.` 几乎能把差距补回来。比如 DeepSeek-V3 的平均 commonsense 分数从 `72.10` 降到 `68.00`，Kimi-K2-Base 从 `73.52` 降到 `70.49`，属于“有损但可控”的范围。

长上下文结果更有说服力，因为它没有掩饰问题。在 LongBench 上，直接 TPLA 转换的 slicing 误差会随着序列变长而积累，所以退化更明显。但 `TPLA (pd sep.)` 缩小了大部分差距：DeepSeek-V3 的平均分从 `58.19` 到 `56.04`，论文把它概括为平均仅 `2.15%` 的损失；Kimi-K2-Base 则从 `54.78` 到 `52.39`。作者也坦率承认，用拼接短文本做的轻量 alignment 对长生成任务帮助有限，这一点让整篇实验显得更可信。

性能实验则比较精准地围绕论文主张展开。作者去掉了 DeepSeek-V3-0324 和 Kimi-K2-Base 里的 `MoE` 路由，以隔离 attention 机制本身的影响；两边都转成 `BF16`，并统一使用 `FlashAttention-3`。在两张 H800 上，随着上下文长度增加，TPLA 的 decode 吞吐优势越来越明显：`32K` 上下文时，DeepSeek-V3-0324 达到 `1.79x`，Kimi-K2-Base 达到 `1.93x`。prefill 侧则印证了论文的分相动机：因为 prefill 是 compute-bound，原始 TPLA 并不理想，而 `TPLA (pd sep.)` 在 `1K` prompt 长度时比 TPLA 快约 `1.4x`。总体来看，这些实验很好地支撑了论文的中心论点：对 latent attention 来说，真正值得优化的是 decode 期的内存带宽，而不是把 prefill 和 decode 混成一个统一设计。

## 创新性与影响

相较于 _Zadouri et al. (arXiv '25)_，TPLA 的新意不只是“让 MLA 更适合硬件”，而是在缩小每卡 KV cache 的同时，仍让每个 head 保有对完整 latent 空间的访问。相较于 _DeepSeek-AI (arXiv '24)_ 提出的 `MLA`，这篇论文补上的是部署阶段缺失的一环：把一个单卡上很优雅的压缩注意力，改造成在 tensor-parallel 推理里依然成立的机制。相较于 _Zhong et al. (OSDI '24)_ 的 DistServe，它也不是替代关系，而是互补关系：DistServe 解决的是 prefill/decode 资源分离，TPLA 解决的是 decode 自身为什么还能进一步减轻内存带宽负担。

因此，这篇论文对两类读者都会有影响。一类是做 LLM serving 的系统研究者，他们会把它当作 latent attention 与 tensor parallel 推理之间的一座桥，尤其适合和 disaggregated prefill/decode 架构结合来看。另一类是做模型结构与部署接口的研究者，因为这篇论文展示了如何在不丢掉预训练 checkpoint 的前提下，把注意力形式改写成更利于部署的版本。它更像“新机制加可落地转换路径”，而不只是一次测评。

## 局限性

这篇论文最大的限制，是当前最好用的方案基本停留在 `g=2`。作者明确指出，`PCA` 在分组数更大时会迅速变差，因为后面的主成分携带的信息本来就弱；这意味着同一套方法未必能平滑扩展到更激进的切分。长生成精度也是未完全解决的问题：附录里的 `RULER` 结果显示，即使是对齐过的版本，在更长上下文下也会明显掉分，说明 decode 阶段的近似误差会随着生成步数积累。

实验范围也有边界。吞吐测试去掉了 `MoE`，只在两张 H800 上做，并主要聚焦 attention 路径而不是完整生产 serving 栈。论文虽然强调与 `FlashAttention-3` 的兼容性，但没有真正展示多节点、异构网络或完整 disaggregated 集群控制面的端到端表现。最后，作者也没有给出从零训练 TPLA 的完整结果，只是论证其可行性，并承认复制式 head 结构会增加训练成本。

## 相关工作

- _DeepSeek-AI (arXiv '24)_ — DeepSeek-V2 提出了 `MLA`，而 TPLA 可以看成是给 `MLA` 补上 tensor-parallel 部署能力的一次系统化改写。
- _Zadouri et al. (arXiv '25)_ — `GLA` 同样想通过切 latent attention 来加速 decode，但它会缩小每个 head 可见的 latent 容量，因此成为 TPLA 最直接的对照对象。
- _Zhong et al. (OSDI '24)_ — DistServe 把 prefill 和 decode 放到不同 serving 阶段，而 TPLA 借用了相同的阶段区分思想，并进一步修改注意力计算本身以减轻 decode 侧内存带宽压力。
- _Meng et al. (arXiv '25)_ — TransMLA 展示了如何把非 MLA checkpoint 转成 MLA，这篇论文则借助这条桥梁说明 TPLA 最终并不只局限于原生 MLA 模型。

## 我的笔记

<!-- 留空；由人工补充 -->
