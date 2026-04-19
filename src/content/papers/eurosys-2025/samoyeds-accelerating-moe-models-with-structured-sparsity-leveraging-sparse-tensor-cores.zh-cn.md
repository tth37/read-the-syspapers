---
title: "Samoyeds: Accelerating MoE Models with Structured Sparsity Leveraging Sparse Tensor Cores"
oneline: "Samoyeds 把 MoE 的权重稀疏和路由后激活稀疏一起编码成适配 Sparse Tensor Core 的格式，让推理更快，也把可承载 batch 上限一起抬高。"
authors:
  - "Chenpeng Wu"
  - "Qiqi Gu"
  - "Heng Shi"
  - "Jianguo Yao"
  - "Haibing Guan"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Shanghai Enflame Technology Co. Ltd., Shanghai, China"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717455"
code_url: "https://github.com/guqiqi/Samoyeds.git"
tags:
  - llm-inference
  - gpu
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Samoyeds 把 MoE 推理当成 sparse-sparse 问题来做：expert 权重先做结构化稀疏，routing 之后本就稀疏的激活也一并编码。配合面向 Sparse Tensor Core 的专用 kernel，它在 kernel 级别相对 VENOM 最多快 1.99x，端到端相对 vLLM-DS 最多快 1.30x，最大 batch size 平均提高 4.41x。

## 问题背景

论文先把瓶颈说清楚：attention 一旦被 FlashAttention 这类方法压下去，MoE 层就成了主要开销，在几个模型里占到 Transformer block 时间的 80% 以上。可现有方案往往只解一半。MegaBlocks、vLLM-DS 会处理 permutation 或 padding，但 expert 权重还是 dense；cuSPARSELt、VENOM 能加速稀疏权重，却默认激活是 dense。

偏偏 MoE 里最不 dense 的就是输入。routing 之后，每个 expert 只接到一部分 token，激活天然稀疏。若把权重和输入都直接当稀疏矩阵处理，要么会把本该跳过的行列照样搬运，要么会把 coalesced access 弄丢。Samoyeds 要解决的正是这个双侧稀疏场景，而不是普通 sparse-dense 乘法。

## 核心洞察

Samoyeds 的核心判断是，MoE 两侧稀疏都足够规整，只是过去没人把它们一起编码。权重侧用两层结构化稀疏：细粒度 2:4 去匹配 `mma.sp`，再叠 vector-wise 稀疏把总稀疏率推到 50% 以上。激活侧则直接记录 routing 后真正保留下来的 token-expert 对。

这样做的好处是，计算结果仍与原始 MoE 等价，收益来自跳过冗余加载和乘法，而不是近似求解。论文真正抓住的不是「零更多」，而是「routing 产生的稀疏模式刚好可以被硬件吃下去」。

## 设计

权重矩阵先被切成 `M x V` 的 block。每个 block 只保留 `N` 条 sub-row，保留下来的 sub-row 再做 2:4 稀疏，于是最终编码成三部分：压紧后的非零数据、记录 sub-row 位置的 indices，以及给 SpTC 使用的 2-bit metadata。输入侧则用 `SEL` 加 vector-wise 稀疏列来表示哪些 routed token 真要参与当前 expert 的计算。

kernel 本身按 fetch 和 compute 两段流水执行：`cp.async` 把编码后的 tile 预取到 shared memory，`mma.sp` 在寄存器和 SpTC 上完成乘法。真正让它跑快的是几项配套设计：三级 tiling，把数据顺着 global memory、shared memory、register 往里送；data stationary，让输出在 sub-row 映射变化时尽量留在寄存器里；data packing，把 data 和 2-bit metadata 重排成更适合 GPU transaction 与 `ldmatrix` 的布局；layout optimization，把权重转置提前到离线阶段，把输入转置融进 global-to-shared 路径，并保持中间 expert 输出的压缩布局。论文还把 activation 和 weighted accumulation 与矩阵乘融合，减少额外 memory round trip。

## 实验评估

大部分实验都在 RTX 4070 Super 上完成，对比对象有 cuBLAS、Sputnik、cuSPARSELt、VENOM、Transformers、MegaBlocks 和 vLLM-DS。kernel 级别上，238 个 synthetic case 里 Samoyeds 相对 VENOM 最多快 1.99x，相对 cuBLAS 最多快 5.44x，相对 cuSPARSELt 最多快 3.18x，相对 Sputnik 最多快 18.76x。换成 Qwen2-MoE、DeepSeek-MoE、MiniCPM-MoE、OpenMoE-34B、Mixtral 的真实形状，平均也还能比 VENOM 快 2.33x，比 cuBLAS 快 3.95x。

到 MoE layer 级别，带 shared experts 时它相对 Transformers 平均加速 1.46x，不带 shared experts 时也有 1.45x；相对 MegaBlocks 和 vLLM-DS 的最好结果分别是 1.66x 和 1.53x。端到端部分虽然只用单个 decoder layer 代替整模型，但仍给出相对 Transformers 最高 2.36x、相对 MegaBlocks 和 vLLM-DS 最高 1.31x 和 1.30x 的提升。最大 batch size 相对 Transformers 平均提升 4.41x，OpenMoE-34B 甚至从 3 提到 56。

在 75% 稀疏率下，BERT 在 SQuAD 1.1 上平均还能保住 99.3% 以上的 dense 精度；Tiny-LLaMA-1B 和 Qwen2-1.5B 在 GSM8K 上的 perplexity 只增加 0.06 和 0.05。论文也承认自己的弱点：如果 expert 很小、expert 很多，或者矩阵形状特别偏斜，例如 Mixtral-8x22B，padding 和 tiling 开销会上来，收益就会缩小。

## 创新性与影响

Samoyeds 的贡献在于把三条本来分开的路线接到一起。VENOM 解决的是 sparse-dense 的结构化稀疏 SpTC kernel，MegaBlocks 解决的是 MoE 执行里的 block-sparse 和 padding，PIT 解决的是动态激活稀疏，但它们都没有把双侧稀疏、MoE 语义和 SpTC 约束统一到同一套格式与执行路径里。这让 routing 稀疏第一次更像一个可直接利用的系统原语，而不只是算法里的副产品。

## 局限性

它的边界也不难看出来。首先，端到端部分只是单层 decoder 的代理实验，不是真正的完整 serving stack，所以框架开销、调度开销和显存碎片化会不会稀释收益，论文没有完全回答。

其次，多数性能结果来自单一 NVIDIA 家族。论文确实比较了几种 NVIDIA GPU 上的直接移植，并显示 Samoyeds 比 VENOM 更稳，但 AMD 兼容性更多停留在「理论上可适配」而不是完整实测。精度评估也没有直接落在那些大 MoE 模型上，因为 pruning 流水线本身太吃内存。

## 相关工作

- _Castro et al. (SC '23)_ - VENOM 同样围绕 Sparse Tensor Core 设计了更灵活的结构化稀疏格式，但它解决的是 sparse weights 加 dense inputs，而不是 MoE 里的双侧稀疏。
- _Gale et al. (PMLSys '23)_ - MegaBlocks 通过 block-sparse kernel 和更少 padding 来加速 MoE 执行；Samoyeds 则进一步把 expert 权重也做成适配 SpTC 的结构化稀疏。
- _Zheng et al. (SOSP '23)_ - PIT 依靠编译器变换去利用动态激活稀疏，而 Samoyeds 把激活稀疏、结构化权重稀疏和手写 sparse kernel 绑在了一起。
- _Chen et al. (PPoPP '23)_ - DFSS 展示了动态 N:M 结构化稀疏如何贴合硬件约束处理 attention，Samoyeds 则把这种硬件感知思路推进到了 MoE 线性层。

## 我的笔记

<!-- 留空；由人工补充 -->
