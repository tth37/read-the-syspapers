---
title: "PAT: Accelerating LLM Decoding via Prefix-Aware Attention with Resource Efficient Multi-Tile Kernel"
oneline: "PAT 按共享前缀打包解码请求、为 CTA 选择资源匹配的多 tile kernel，并合并部分结果来降低 LLM decode attention 延迟。"
authors:
  - "Jinjun Yi"
  - "Zhixin Zhao"
  - "Yitao Hu"
  - "Ke Yan"
  - "Weiwei Sun"
  - "Hao Wang"
  - "Laiping Zhao"
  - "Yuhao Zhang"
  - "Wenxin Li"
  - "Keqiu Li"
affiliations:
  - "Tianjin University, Tianjin, China"
  - "Stevens Institute of Technology, Hoboken, NJ, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790200"
code_url: "https://github.com/flashserve/PAT"
tags:
  - llm-inference
  - gpu
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PAT 认为，LLM decode attention 的真正瓶颈是内存流量，而不只是算力利用率。它先把共享 KV 前缀的解码请求打包进同一个 CTA，再为每个 CTA 选择更匹配查询数与 KV 长度的 tile 形状，最后用多流执行和轻量 merge kernel 还原最终 attention 输出。论文表明，这种组合能够同时减少重复的 global-memory 访问，并改善 kernel 延迟与端到端 token 延迟。

## 问题背景

这篇论文抓住了一个越来越关键、但常被“更快 attention”口号掩盖的问题：随着提示词和生成长度增长，推理系统的 decode 阶段越来越主导整体延迟，而 decode attention 本质上是 memory-bound，因为每一步都要从 global memory 重新搬运越来越大的 KV cache。与此同时，真实业务中的请求往往有大量共享前缀。系统提示词、工具模板、RAG 检索片段都会在 continuous batching 窗口内形成多层级共享前缀。vLLM、SGLang 这一类系统虽然已经支持 prefix KV reuse，可以减少 KV cache 占用，但这种“逻辑复用”并不会自动减少 attention kernel 反复读取共享 KV block 的次数。

作者认为，现有 attention kernel 在这里有两类不同的浪费。以 FlashAttention 为代表的 query-centric kernel 采用 one-query-per-CTA，每个查询各跑各的，于是同一批中共享的前缀 block 会被多个 CTA 重复搬运。以 FastTree、RelayAttention 一类为代表的 KV-centric 方案虽然试图把共享前缀放到一起，但往往仍然依赖固定 tile 形状和大量 padding，于是又会带来 shared memory 浪费、register 压力和长尾 CTA 导致的 execution bubble。换句话说，问题并不只是“支持 prefix reuse”，而是要在动态 batch、动态 KV 长度和多层前缀并存的情况下，把 prefix reuse 真的变成更少的内存访问和更高的硬件利用率。

## 核心洞察

论文最核心的判断是：decode attention 应该被视为一个 memory-centric packing 问题。如果多个请求共享足够长的 KV 前缀，那么把它们放进同一个 CTA 执行就是划算的，因为“共享前缀只加载一次”带来的收益，足以覆盖后续写入和读取中间结果以便 merge 的额外开销。但这件事只有在 kernel 形状也能跟着 packed CTA 自适应时才成立；如果仍然强迫所有 CTA 走同一种 tiling 策略，就只是把瓶颈从重复加载转移成资源浪费。

基于这一点，PAT 提出了 pack-forward-merge 三段式设计。先按共享前缀打包查询，让一个 CTA 能在 on-chip memory 中复用 KV block；再用一组可变 tile 的 kernel 去执行这些 CTA，让 tile 大小跟着实际查询数和 KV 长度变化；最后再用 online softmax 把分散的部分结果合并回来。真正重要的不是某一个单点技巧，而是 packing 决策与 kernel 配置必须一起设计，否则减少 global-memory 访问的收益会被新的执行低效吃掉。

## 设计

PAT 的第一阶段是 pack。系统先把一个 decode batch 的 block table 变成 prefix tree：内部节点表示共享前缀，叶子节点表示单个查询。调度器围绕一个启发式 profit model 决定某个节点应该单独成为一个 CTA、继续拆开，还是与某个子节点合并。这个模型显式比较“少加载多少 KV block”和“为了后续 merge 多出来多少中间结果读写”。由于精确搜索空间是指数级，论文采用了线性复杂度的树遍历启发式。此外，PAT 还做了 lazy update：只要 block table 没变，就复用之前的 packing 结果；而新的调度计算则异步执行，从而把在线开销压低。

第二阶段是 kernel 设计。PAT 不再接受先前工作里 one-size-fits-all 的 tile 策略，而是先离线根据 shared-memory 上限、register 上限，以及“想把带宽跑满至少要有多少 in-flight 数据”这三个约束，求出一组可行的 `(m, n)` tile 组合，并分别编译成 kernel。在线执行时，tile selector 会为每个 CTA 选 tile：查询维度上，选择不引入额外 padding 的最小可行 `m`；KV 维度上，则依据 profiling 得到的分段规则选 `n`。长 KV 倾向于较大的 `n`，因为它能减少尾部 bubble、让每个 CTA 获得更多带宽；短 KV 则更适合较小的 `n`，以避免最后一个 tile 形成明显的 compute-only 尾巴。

第三阶段是 forward 与 merge。因为不同 tile 形状通常意味着不同 kernel 配置，直接执行会退化成串行多次 launch。PAT 因此按 tile 配置把 CTA 分组，为每一组建立独立 CUDA stream，让不同配置的 kernel 并行推进。对于 KV 长度极端偏长的 CTA，它还会沿 KV 维度继续切分，避免少数超长 CTA 拉高整个 batch 的尾部时间。最后，merge kernel 基于 online softmax，把每个查询每个 head 的局部 max、log-sum-exp 和加权和重新规约成最终输出。实现上，PAT 是 vLLM 的一个 plugin，直接复用 vLLM 的 paged KV cache，而不是另起一套 serving runtime。

## 实验评估

这篇论文的实验设计和它的问题定义是对齐的。作者在 A100 和 H100 上做 kernel benchmark，又在真实在线服务轨迹上做端到端实验。合成 batch 会系统性改变 prefix tree 结构、共享前缀长度、非共享后缀长度以及 attention head 配置，这一点很重要，因为 PAT 的收益本来就依赖“前缀共享有多少”和“打包后 CTA 有多不均匀”。端到端部分则使用 Qwen3-8B、Llama-3-8B 跑 `toolagent` 与 `conversation` 两类真实 trace，并进一步在 Qwen2.5-72B 的 TP/PP 部署和 Qwen3-30B-A3B 的 MoE 部署上验证扩展性。

最关键的 kernel 结果是：在存在共享前缀的工作负载下，PAT 相比现有最强基线平均将 attention latency 降低 53.5%。在 A100 的合成 workload 上，它对 FlashAttention 最多快 `21.5x`，对 FlashInfer 最多快 `11.7x`，对 FastTree 最多快 `3.2x`，对 RelayAttention 最多快 `11.9x`，对 RelayAttention++ 最多快 `5.7x`。论文给出的解释是可信的：query-centric 基线主要输在重复 global-memory 访问，KV-centric 基线则主要输在固定 tile 和较弱的打包启发式。即使把共享前缀移除，PAT 仍凭借 multi-tile 与 multi-stream 设计获得小幅平均收益，说明它不是只能在“极端有前缀复用”的场景下工作。

端到端 serving 的结果也很直接。在相同请求速率下，PAT 相对 RelayAttention++ 将平均 TPOT 降低 `17.2-68.1%`，相对 FlashAttention 降低 `17.0-89.5%`，相对 FlashInfer 降低 `32.2-93.1%`。因为 decode 更快，它也显著降低了 TTFT。更重要的是，ablation study 证明这些收益不是偶然叠出来的：把 memory-oriented packer 换成 compute-oriented 版本、改成 naive packing、强制使用固定 tile、或者关闭 multi-stream forward，都会明显恶化延迟。也就是说，论文的核心主张得到了比较完整的支撑：PAT 的效果来自 prefix-aware packing 与 resource-aware execution 的联合作用，而不是某一个孤立的小优化。

## 创新性与影响

和 _Kwon et al. (SOSP '23)_ 相比，PAT 并没有发明新的 KV-cache 抽象；它默认 paged KV cache 已经存在，真正关注的是 decode kernel 应该怎样建立在这个抽象之上。和 _Pan et al. (MLSys '25)_ 相比，它最关键的差异是 cost model：PAT 明确把 decode attention 视为 memory-bound，因此 packing 目标是减少内存流量，而 FastTree 的 compute-oriented packing 在这个问题上被作者认为并不匹配。和 _Zhu et al. (ACL '24)_ 相比，PAT 也不只处理单层 system prompt，而是把问题推广到多层共享前缀，并配上可以随 CTA 动态变化的 kernel 家族。

因此，这篇论文对两类读者都很有价值。一类是写 GPU kernel 和 attention runtime 的人，他们会把 PAT 看成一种新的 prefix-aware decode primitive；另一类是做 LLM serving 的系统研究者，他们会把 PAT 视为“共享前缀如何真正转化成吞吐与时延收益”的实现路径。它的贡献不是单纯再做一个更快 kernel，而是把 shared-prefix execution 重新组织成一个同时涉及调度和 kernel 设计的问题。

## 局限性

PAT 的收益显然依赖工作负载结构。论文自己就承认，小 batch 或几乎没有共享前缀的场景下，可提升空间会明显缩小；它的无前缀实验也确实只显示出较温和的收益。多 tile 配置还需要针对每种 GPU 架构离线重新推导，而在线 tile selector 依赖 profiling 得到的规则，并不是完全解析式的模型。

它也没有试图解决所有 serving 层面的问题。PAT 聚焦 decode 阶段，并作为 vLLM plugin 接入现有 paged KV cache，所以它并不处理 admission control、跨模型路由或更大范围的集群调度。multi-stream execution 虽然减少了 residual bubble，但 discussion 部分也坦率指出，GPU 调度本身仍不可控，因此距离理论最优仍有缺口。最后，实验虽然对 attention latency 和在线 serving 已经足够扎实，但依然主要围绕单一 serving substrate 和少数模型家族展开。

## 相关工作

- _Kwon et al. (SOSP '23)_ — PagedAttention 让 serving 系统中的 KV-cache 复用变得可行，而 PAT 关注的是 decode kernel 如何利用这种复用来减少内存流量。
- _Dao et al. (NeurIPS '22)_ — FlashAttention 奠定了 IO-aware fused attention 的基础，但其 query-centric 执行方式无法在 decode 阶段利用跨请求共享前缀。
- _Pan et al. (MLSys '25)_ — FastTree 同样面向树状前缀共享，而 PAT 主张使用 memory-oriented packing 目标，并进一步加入 multi-tile 与 multi-stream 执行。
- _Zhu et al. (ACL '24)_ — RelayAttention 主要针对长 system prompt 减少冗余加载，而 PAT 把这个思路扩展到多层共享前缀和动态 CTA 形状。

## 我的笔记

<!-- 留空；由人工补充 -->
