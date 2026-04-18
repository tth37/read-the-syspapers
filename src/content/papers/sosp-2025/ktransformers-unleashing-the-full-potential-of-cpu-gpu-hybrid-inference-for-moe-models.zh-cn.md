---
title: "KTransformers: Unleashing the Full Potential of CPU/GPU Hybrid Inference for MoE Models"
oneline: "KTransformers 把 AMX/AVX-512 专用 MoE kernel、CUDA Graph 编排和 expert deferral 结合起来，让单 GPU 加 CPU 能更快本地运行超大 MoE。"
authors:
  - "Hongtao Chen"
  - "Weiyu Xie"
  - "Boxin Zhang"
  - "Jingqi Tang"
  - "Jiahao Wang"
  - "Jianwei Dong"
  - "Shaoyuan Chen"
  - "Ziwei Yuan"
  - "Chen Lin"
  - "Chengyu Qiu"
  - "Yuening Zhu"
  - "Qingliang Ou"
  - "Jiaqi Liao"
  - "Xianglin Chen"
  - "Zhiyuan Ai"
  - "Yongwei Wu"
  - "Mingxing Zhang"
affiliations:
  - "Tsinghua University"
  - "Approaching.AI"
  - "Hangzhou Dianzi University"
  - "University of Electronic Science and Technology of China"
  - "Beijing University of Posts and Telecommunications"
  - "Beijing Institute of Technology"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764843"
code_url: "https://github.com/kvcache-ai/ktransformers"
tags:
  - llm-inference
  - gpu
  - scheduling
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

KTransformers 通过联合设计 CPU kernel、CPU/GPU 调度，以及一个小幅放松模型执行顺序的 Expert Deferral，让本地 hybrid MoE inference 真正可用。对 DeepSeek-V3、DeepSeek-V2.5 和 Qwen2-57B-A14B，它把 prefill 提升了 4.62x-19.74x，把 decode 提升了 1.66x-4.90x。

## 问题背景

MoE 模型表面上很适合 hybrid inference：attention 和 shared experts 留在 GPU，routed experts 驻留在 DRAM 并由 CPU 执行。但论文指出，现有系统在两个阶段都浪费了大量性能。Prefill 阶段，长 prompt 会同时激活很多 experts，CPU 因而长期卡在 expert GEMM 上，而通用 AVX-512 或供应商 AMX kernel 并没有围绕 MoE 的 layout 与 cache 复用做协同优化。Decode 阶段，每步算得很少，launch 和同步反而成了主导开销：系统频繁跨越 host 边界、发起短小 GPU kernel，并在 CPU-GPU 与跨 NUMA 协调上不断阻塞。作者在 DeepSeek-V3 上测到的代表性结果是：prefill 70.02 tokens/s，decode 4.68 tokens/s，GPU 利用率不到 30%。

## 核心洞察

论文的核心洞察是：本地大 MoE 推理卡住的是整条 pipeline，而不是某一个算子。Prefill 需要更快的 CPU expert kernel，decode 需要避免被 CPU/GPU 边界反复打断，而标准 Transformer 的严格层间依赖还限制了重叠空间。KTransformers 因此把三类手段绑在一起：高 arithmetic intensity 时用面向 AMX 的 kernel 和 layout，低强度 decode 场景切到 AVX-512；把 submit/sync 协调点藏进单个 CUDA Graph；再利用 residual connection 的鲁棒性，把部分 routed experts 延后一层消费，换出更大的 CPU/GPU overlap 窗口。

## 设计

KTransformers 基于 HuggingFace Transformers 提供了一个 YAML 驱动的 module injection 框架，可以按类名或模块名匹配原模块，再替换成硬件特化实现，同时保持 HuggingFace 接口不变。对 MoE block，最关键的替换是 fused CPU operator 和专门的 AMX/AVX-512 kernel。Expert weight 会在加载时被重排成 AMX tile 友好的子矩阵，并围绕 cache 层次切块；Gate、Up、Down 等子算子也会在依赖允许时做融合，prefill 还引入动态任务调度来缓解 expert 命中不均。系统并不会无差别地使用 AMX：在 decode 这种低 arithmetic intensity 的向量-矩阵场景里，运行时会切到兼容同一布局的 AVX-512 kernel，因为此时更低的开销比更高的峰值吞吐更重要。

协调层面，shared experts 留在 GPU，routed experts 留在 CPU。Control thread 负责把 routed-expert 任务推给后台线程，同时发起 GPU 上 shared experts 的执行。为了避免每次 submit/sync 都把 CUDA Graph 打碎，KTransformers 用 `cudaLaunchHostFunc` 把这些协调点包进 stream，让整个 decode 路径仍能落在单个 graph 中。对于双路 CPU，系统还使用 NUMA-aware tensor parallelism，把每个 expert 的 weight matrix 分片到不同 socket 上，让大部分访问保持本地，只在最后做轻量归约。

最特别的机制是 Expert Deferral。标准 MoE 中，layer `k` 的所有 routed experts 都必须先完成，layer `k+1` 的 attention 才能继续。KTransformers 把 routed experts 分成 immediate 与 deferred 两组，后者延到 `k+2` 层再贡献结果，从而打破这条硬依赖，让 CPU 上的 deferred experts 可以和 GPU 的下一层计算更充分重叠。论文对 DeepSeek-V3 的分析显示，在 BF16 配置下 defer 3 个 experts 是最佳点：CPU 利用率从 74% 拉到接近饱和，单层时间下降 26%，端到端 decode 吞吐提升 33%。

## 实验评估

评估明确围绕“本地部署”展开。硬件是一台双路 Xeon 8452Y 服务器，接 A100 40 GB 或 RTX 4080 16 GB；工作负载是 batch size 1 的 Wikitext prompt；模型覆盖 DeepSeek-V3、DeepSeek-V2.5 和 Qwen2-57B-A14B。基线是 Fiddler 与 Llama.cpp，其中作者还补齐了 Llama.cpp 的 expert-level offloading 能力，尽量保证可比性。

主结果比较扎实。Prefill 阶段，KTransformers 在所有 prompt 长度上都超过两个基线，加速达到 4.62x-19.74x。Decode 阶段，不开 Expert Deferral 时，它已经比 Fiddler 快 2.42x-4.09x、比 Llama.cpp 快 1.25x-1.76x；在量化模型上，相对 Llama.cpp 的优势变成 1.77x-1.93x。继续叠加 Expert Deferral 后，decode 还能再涨最多 45%，使总体 decode 加速达到 1.66x-4.90x。分解实验也符合设计叙事：Prefill 更依赖 AMX 和动态调度，decode 更依赖 AVX-512、NUMA-aware tensor parallelism 与 CUDA Graph。Expert Deferral 的精度损失并非零，但相当小：主表上的变化基本都在 2 分以内，而在 DS-3 的 LiveBench 上，默认 defer 6 个 experts 时平均只下降 0.5%，明显好于直接跳过这些 experts。

## 创新性与影响

这篇论文的创新点不是新模型，而是新的系统组合方式。相较于 Fiddler，KTransformers 在 CPU kernel、NUMA locality 和 decode 同步路径上都推进了一大步；相较于那些通过减少激活 experts 来提速的算法工作，它尽量保持模型结构不变，把优化放在运行时上。这个结论既对想做私有本地部署的工程团队有价值，也对系统研究者有启发：只要放松得足够克制，执行顺序上的小改动就能换来显著的 CPU/GPU overlap。

## 局限性

不过，这篇论文的边界也很明确。它几乎完全围绕 batch size 1 的本地 serving 展开，因此并不能证明同一套设计在更高并发或云端场景下仍然最优。CPU 侧收益也明显依赖 Intel AMX、双路 NUMA 和大容量 DRAM，对更弱 CPU 或其他 ISA 的可迁移性尚不清楚。Expert Deferral 本身是一种近似而非零成本技巧，最优 defer 数量依赖具体模型，而这种语义变化在长尾任务上的风险也没有被彻底排除。除此之外，论文的评估停留在单机 hybrid serving，对分布式部署和长期运维复杂度几乎没有展开。

## 相关工作

- _Kamahori et al. (arXiv '24)_ - Fiddler 率先展示了 MoE inference 的 CPU/GPU orchestration，而 KTransformers 进一步深挖了 CPU kernel、NUMA locality 和 decode 同步路径。
- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention 让 GPU 常驻的 LLM serving 更高效，但 KTransformers 面向的是稀疏 MoE 放不进显存、必须把参数和计算同时扩展到 CPU 的另一类场景。
- _Song et al. (SOSP '24)_ - PowerInfer 通过 selective offloading 加速 dense 模型的本地推理，而 KTransformers 则利用 MoE sparsity，把 routed experts 的执行真正放到 CPU 上。
- _Hwang et al. (ISCA '24)_ - Pre-gated MoE 通过算法层面减少激活 expert 数量来降成本，而 KTransformers 尽量保留原始 expert 集合，优化的是异构运行时如何执行它们。

## 我的笔记

<!-- empty; left for the human reader -->
