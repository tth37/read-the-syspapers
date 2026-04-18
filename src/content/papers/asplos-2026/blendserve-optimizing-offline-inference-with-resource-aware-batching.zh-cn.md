---
title: "BlendServe: Optimizing Offline Inference with Resource-Aware Batching"
oneline: "BlendServe 用资源感知前缀树和双向扫描，把算力型与带宽型离线 LLM 请求混编进同一批次，同时尽量保住 prefix sharing。"
authors:
  - "Yilong Zhao"
  - "Shuo Yang"
  - "Kan Zhu"
  - "Lianmin Zheng"
  - "Baris Kasikci"
  - "Yifan Qiao"
  - "Yang Zhou"
  - "Jiarong Xing"
  - "Ion Stoica"
affiliations:
  - "University of California, Berkeley, Berkeley, CA, USA"
  - "University of Washington, Seattle, WA, USA"
  - "University of California, Davis, Sacramento, CA, USA"
  - "Rice University, Houston, TX, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790133"
tags:
  - llm-inference
  - scheduling
  - caching
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

BlendServe 把离线 LLM serving 看成“请求排序问题”，而不只是“内核优化问题”。它用资源感知前缀树和双向扫描，把计算密集与带宽密集的请求混到同一批次里，同时保住大部分 prefix sharing，最终相对 vLLM/SGLang 最高提升 `1.44x` 吞吐，并达到作者定义的 practical optimum 的约 `86.55%-90.8%`。

## 问题背景

离线 batch API 本来就允许很长的返回窗口，因此核心目标不是 `TTFT` 或 `TPOT`，而是单位硬件上的吞吐率。现有系统确实利用了 prefill 偏计算、decode 偏显存带宽这一事实，但大多只优化“batch 内部”的 overlap。只要 workload 变得异构，这种思路就不够了：一串长输入短输出请求会让 compute 饱和而 memory 闲置，一串长输出请求则正好相反。

真正困难的地方在于 prefix sharing。沿前缀 trie 做 DFS 能最大化 prefix reuse，但它也会把相似请求排在一起，进一步恶化资源失衡。论文给出的例子是，在一个 Llama-3-8B 设置里，纯 DFS 排序只能达到最优吞吐的 `71.7%`。所以 BlendServe 面对的不是单目标问题，而是要在资源互补和前缀局部性之间做受约束的折中。

## 核心洞察

论文的核心主张是：在 continuous batching 下，请求级 compute density 已经足够好用，可以作为调度信号。长 prompt、短 output 的请求更 compute-heavy；长 output 的请求更 memory-heavy。只要 batch 的组成持续逼近整个 workload 的目标 density，compute 时间和 memory 时间就更容易重叠。

这也意味着 prefix sharing 不再是绝对规则，而是可控资源。BlendServe 不坚持纯 DFS，而是接受一小部分 prefix reuse 损失，换取更好的跨请求资源互补。离线推理恰好给了系统这么做的空间。

## 设计

BlendServe 先建一个简单的性能模型。对输入长度为 `p`、输出长度为 `d` 的请求，它估计 GEMM 主导的 compute 时间和 decode 阶段 KV-cache 读取主导的 memory 时间，并定义 `Comp(r) / Mem(r)` 作为 compute density。论文用真实 kernel 时间验证这一模型，最大相对误差不超过 `6%`。

核心数据结构是资源感知前缀树。它沿用 RadixAttention 的 trie 结构，但在每个节点上附加一个已经把 prefix sharing 计入的 density 值 `(1 - s) * Tcomp / Tmem`。这样，同一棵树同时表达了前缀局部性和资源需求。

由于输出长度事先未知，BlendServe 会先做一个 warmup sampling：完整运行少量请求，再用子树内样本的平均输出长度估计剩余请求；如果某棵子树没有样本，就用共享最长前缀的 sibling 子树均值。论文报告只采样 `1%` 请求时，端到端表现已经接近 `100%` 采样。

接下来系统按层排序，把 compute-heavy 子树往左推、memory-heavy 子树往右推，同时保持层级结构。如果局部仍有离群点，就做 conditional node splitting：只要 prefix 重算代价低于阈值 `t`，就把节点拆出来重插。作者把这个阈值调到大约保留 `99%` 的 prefix sharing，而实际需要拆分的叶子通常只有 `0.1%-1%`。

运行时的 batch 由 dual scanner 形成。它同时从排序后前缀树的左右两端扫叶子，一边拿 compute-heavy 请求，一边拿 memory-heavy 请求。系统通过 `ML + MR = M` 与 `ML * rho(RL) + MR * rho(RR) = M * rho(root)` 这两个方程决定两边的显存分配，再按这个预算装填请求，使混合后的 batch 尽量逼近根节点 density。论文给出的例子是：`80GB` A100 先留 `20GB` 给权重和 buffer，再把其余 `60GB` 分成 `19.3GB` 和 `40.7GB`，从而把 density 为 `3.73` 与 `0.096` 的两类请求混成目标 density `1.27`。这条预处理路径只是一次性 warmup，论文称其耗时不到总执行时间的 `1%`，并且同样的抽象还能扩展到 data parallel 和 tensor parallel。

## 实验评估

原型系统把基于 SGLang 的前缀树管理、基于 NanoFlow 的调度器以及 C++ 后端组合起来。主要实验 workload 来自 BurstGPT、MMLU、OpenVid、WildChat、ShareGPT 和 Azure-Trace；每个代表性运行至少有 `400,000` 个请求，约消耗 `5` 个 A100 GPU 小时。

结果基本支撑了论文的核心主张。对 Llama-3-8B 的四组代表性 trace，BlendServe 相比 NanoFlow-DFS 提升 `19.34%-22.65%`，平均 `20.84%`；相对 vLLM-DFS 最高提升 `1.44x`。在 `8x` A100 上运行 Llama-3-70B 时，它相对 NanoFlow-DFS 平均提升 `18.6%`，并达到 practical optimum 的 `90.8%`。而且它确实没有靠牺牲 prefix sharing 换吞吐：BlendServe 保留了超过 `97%` 的最优 prefix sharing，而 NanoFlow-Balance 低于 `30%`；资源曲线也显示 BlendServe 的 compute 和 memory 时间更稳定。

更重要的是，这个收益不是只在一个点上成立。作者在 compute density `0.80-1.40`、prefix sharing `0.05-0.45` 的范围内合成了 `65` 个 workload，BlendServe 相对 NanoFlow-DFS 的提升为 `14%-34%`，平均 `22.53%`，其中 density 约为 `1.30` 时最好。对更 memory-heavy 的区域，收益会收缩，作者归因于更严重的 GPU interference。Data parallel 的扩展接近线性：`DP=4` 时，相对 `DP=1` 的吞吐达到 `3.78x-3.88x`。在另外四个模型上的模拟结果中，它仍有平均 `15.2%` 的提升，并达到 `89.9%` 的 practical optimum。整体来看，评估对核心论点是有支撑力的，只是主要依赖合成 workload 而不是生产真实 trace。

## 创新性与影响

相对 _Zhu et al. (OSDI '25)_ 的 NanoFlow，BlendServe 的新意不在更细粒度的算子重叠，而在于决定“哪些请求应该出现在同一个 batch 里”。相对 DistServe，它选择的是 colocate 再重排，而不是物理解耦 prefill/decode。相对 RadixAttention 式前缀树，它把 trie 从缓存索引提升成了调度对象。所以这篇论文更像一个真正的机制论文：它给离线 batch inference 增加了一个新的前端策略面，做 batch API、离线评测和多模态后端的人都很可能会引用它。

## 局限性

BlendServe 很明显是离线设计：它需要事先可见的请求池，还需要 warmup 采样输出长度，因此不适合真正的在线 serving。它的估计也更适合“prompt 相似意味着输出长度分布也相近”的任务；附录里 ShareGPT 和 WildChat 这种高方差 trace 上的收益就更弱。实验方面，论文依赖合成 workload，因为公开离线 batch trace 不存在；同时 headline throughput 也不包含 tokenization、sampling、scheduling 等 CPU 侧成本。最后，BlendServe 终究还是启发式方法，只是把到 practical upper bound 的差距压到大约 `9%-13%`，并没有达到真正全局最优。

## 相关工作

- _Yu et al. (OSDI '22)_ — Orca 建立了生成式模型 serving 中 continuous batching 的基本框架，而 BlendServe 在这个基础上增加了面向离线场景的请求重排。
- _Strati et al. (EuroSys '24)_ — Orion 在更细粒度上做算子重叠，BlendServe 则把优化点前移到 batch 形成阶段，主动改变请求组合。
- _Zhu et al. (OSDI '25)_ — NanoFlow 是 BlendServe 最接近的执行底座；BlendServe 继承其 operator-level overlap，但用资源感知 batching 取代被动的请求顺序。
- _Ma et al. (OSDI '20)_ — Rammer 展示了编译器/运行时层面的 operator overlap，而 BlendServe 把 overlap 的思路提升到 LLM serving 的请求调度层。

## 我的笔记

<!-- 留空；由人工补充 -->
