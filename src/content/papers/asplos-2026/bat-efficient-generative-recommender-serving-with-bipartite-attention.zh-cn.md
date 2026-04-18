---
title: "Bat: Efficient Generative Recommender Serving with Bipartite Attention"
oneline: "Bat 让生成式推荐请求可按用户前缀或商品前缀重排，并结合冷热感知的缓存放置与调度，提升 KV cache 复用和服务吞吐。"
authors:
  - "Jie Sun"
  - "Shaohang Wang"
  - "Zimo Zhang"
  - "Zhengyu Liu"
  - "Yunlong Xu"
  - "Peng Sun"
  - "Bo Zhao"
  - "Bingsheng He"
  - "Fei Wu"
  - "Zeke Wang"
affiliations:
  - "Zhejiang University, Hangzhou, China"
  - "Taobao & Tmall Group of Alibaba, Beijing, China"
  - "The University of Hong Kong, Hong Kong, China"
  - "Aalto University, Espoo, Finland"
  - "National University of Singapore, Singapore, Singapore"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790131"
tags:
  - ml-systems
  - caching
  - scheduling
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Bat 的核心观点是：生成式推荐请求里，可复用的前缀不必永远是用户画像。它提出 Bipartite Attention，把用户 token 和商品 token 都变成可选的 KV cache 前缀，再配合冷热感知的调度器和 hot-replicated cold-sharded 商品缓存放置策略，决定每个请求该复用哪一侧。论文在四个数据集上报告，相比完全重算，Bat 的吞吐最高提升 `2.3x`；相比传统的 user-as-prefix 方案，最高提升 `1.6x`。

## 问题背景

这篇论文针对的是推荐系统里的一个新现实：ranking 阶段开始从 DLRM 这类相对轻量的模型，转向 Transformer 式的 Generative Recommender。这样的模型会把用户画像、约 `100` 个候选商品以及指令 token 拼成一个长提示词，再通过因果自注意力给候选商品打分。表达能力更强了，但推理代价也随之上升。作者把它类比为 LLM serving 的 prefill 阶段，并展示了当模型规模在 `1B-7B`、输入长度接近 `8K` token 时，单个请求就可能超过 `100-200 ms` SLO。

于是，prefix caching 看起来是最自然的优化方向，但论文指出现有做法几乎只吃到了表面收益。默认的组织方式是 user-as-prefix：把用户画像放在前面，缓存用户部分的 KV cache，后面的候选商品和指令在线计算。问题在于，这种缓存只能在“同一个用户的多次请求”之间复用，无法跨用户共享；而候选商品集合来自实时 retrieval，不同轮次常常不同，因此商品侧也很难复用。作者在真实广告 workload 上测得，这种做法的 cache hit rate 只有 `18%`，相对重算带来的总计算节省不到 `11%`。

内存压力同样说明问题并不只是“做一个更大的缓存”。以 Qwen2-1.5B 为例，`1000` 个用户 token 就大约对应 `29 MB` KV cache；如果要缓存 `10^8` 个用户，理论上需要超过 `2.9 PB` 存储。也就是说，传统 user-as-prefix 方案既复用率低，又把缓存对象选成了最难大规模持久保存的一侧。

因此，论文真正要解决的系统问题是：如何找到一个更适合共享的缓存单位，并且让系统能按请求动态决定应该缓存用户前缀还是商品前缀，而不是把这个选择写死在模型输入格式里。

## 核心洞察

Bat 最重要的洞察是：在推荐 ranking 任务里，用户信息和候选商品集合在更高层语义上是 permutation-invariant 的。换句话说，只要每个用户内部、每个商品内部自己的 token 顺序仍被保留，而且不同商品之间的 attention 继续被 mask 掉，那么“先放用户再放商品”和“先放商品再放用户”不必导致语义变化。这样一来，有些请求完全可以把商品集合而不是用户画像当作可复用前缀。

这件事有价值，是因为商品和用户的可共享性天生不同。用户画像高度个性化，跨用户几乎不能复用，而且很多用户很冷；而商品访问通常呈现明显热点分布。论文 trace 显示，大约 `90%` 的访问集中在最热的 `10%` 商品上。于是，如果系统能把热门商品的 KV cache 变成共享前缀，它就能把缓存从“按用户零散命中”变成“按热点商品跨用户摊销”。

但 Bat 并没有因此简单地把系统改成永远 item-as-prefix。作者强调，这其实是一个资源分配问题：对于历史很长、短时间内又会频繁回来的用户，缓存用户画像仍可能更划算；对于大量冷用户或短画像用户，缓存商品更有收益。也正因为如此，Bipartite Attention 不是单独的 attention 小技巧，而是后续缓存放置和调度策略成立的前提。

## 设计

设计的第一部分是 Bipartite Attention 本身。Bat 支持两种输入组织方式。`User-as-prefix` 时，缓存前缀是 `[U]`，在线计算后缀 `[I1, ..., IN, Instr]`；`Item-as-prefix` 时，缓存前缀改成 `[I1, ..., IN]`，在线计算 `[U, Instr]`。为了让商品 KV cache 可以独立复用，Bat 同时修改了 attention mask 和 position encoding：不同候选商品之间不允许相互 attention，各商品的首 token 共享同样的起始位置 ID，从而避免某个商品的 KV cache 依赖它在候选列表里的绝对槽位。最终，模型仍通过一个 discriminant token 输出排名 logit。

第二部分是整体系统架构。Bat 在 retrieval 和 GPU 推理之间加入一个中心化 prompt scheduler。它接收请求后，先向 cache meta service 查询相关用户和商品条目的状态与热度，再决定当前请求采用哪种前缀组织方式，然后把 batch 派发给 inference worker。真正的 KV cache 数据由独立的 KV cache worker 管理，按页存放在 CPU 或 GPU 内存中，并通过 DMA 或 RDMA 传输。meta service 只维护索引与 hotness，不持有物理缓存内容。关键不在架构是否新奇，而在于 Bat 会在执行前主动决定复用哪一侧前缀。

第三部分是缓存放置。因为引入 item cache 会占用本可分给 user cache 的本地内存，Bat 不能简单把全部商品都复制到每台机器上。作者因此提出 hot-replicated cold-sharded。它先根据离线测得的网络带宽和 prefill 时间，算出系统能容忍的跨机 KV 传输比例；再根据商品访问频率分布，选择最热的一小部分商品做全副本复制，长尾部分则分片到不同 worker。这样既能让热点商品尽量本地命中，又不会为整个商品全集付出完整复制的内存代价。

第四部分是 hotness-aware prompt scheduling。作者指出，只看“用户 token 多还是商品 token 多”是错误的，因为长画像用户未必热，给他们分配 user cache 往往会产生强制 miss。Bat 因此维护一个基于滑动窗口的用户访问频率估计，只在两个条件同时满足时才选择 user-as-prefix：当前用户 token 数大于 item token 数，且该用户的预测频率高于缓存中最冷的 user entry。否则就退回 item-as-prefix。也就是说，Bat 只把宝贵的 user-cache 空间留给“很快会再次命中”的用户。

## 实验评估

实验设计比常见的概念验证更完整。作者在一个 `4` 节点 A100 集群上完成主要实验，又在 `16` 节点 H20 生产集群上评估可扩展性；数据集包括 Amazon 的 `Games`、`Beauty`、`Books`，以及基于真实广告 trace 构造的 `Industry`。模型方面使用 Qwen2-1.5B、Qwen2-7B 和 Llama3-1B，所有系统都建立在同样的 vLLM 与 FlashInfer 底座上，baseline 也统一采用 CPU-memory KV cache。

最关键的结果是，Bat 同时战胜了完全重算和固定前缀策略。论文报告在不同模型与数据集上，Bat 的 cache hit rate 最高达到 `58%`，相对 recomputation 的吞吐提升最高 `2.3x`，相对 user-as-prefix 的提升最高 `1.6x`。更重要的是，固定策略之间的输赢关系并不一致：在 `Beauty`、`Books` 和 `Industry` 上，item-as-prefix 比 user-as-prefix 更强；但在用户访问频率更高的 `Games` 上，user-as-prefix 反而更优。这个分化正好支撑了 Bat 的核心论点，即不存在一个在所有 workload 上都最优的固定前缀布局。

精度实验同样关键，因为 Bat 的收益并不只是缓存管理，而是建立在“重排后语义不变”这个命题上。Table 3 显示，大多数情况下 item-as-prefix 在 Recall、MRR、NDCG 上与 user-as-prefix 接近，有时甚至更好；但也不是完全没有代价，例如 Qwen2-1.5B 在 `Books` 上会有轻微退化，Llama3-1B 在一些设置下也更敏感。作者把这一点归因于基础模型对位置变化的鲁棒性不同，并提出可进一步结合 PIC/CacheBlend 一类 position-independent caching 技术来缩小差距。

组件分析也比较扎实。HRCS 放置在 `Books` 上相对全复制方案，在 `10 Gbps` 和 `100 Gbps` 网络下分别带来 `10%` 和 `16%` 的吞吐提升，同时避免纯哈希分片带来的重通信开销。hotness-aware scheduling 在 user cache 很小的时候明显优于只看 token 数的 cache-agnostic 策略。延迟实验里，在 `200 ms` P99 目标下，Bat 可承受的请求速率约为 user-as-prefix 的 `1.47x`、recomputation 的 `1.57x`。可扩展性方面，系统从 `1` 到 `16` 节点近线性扩展，并在 `Industry-100M` 物品规模下仍保持优势。

整体来看，实验对中心论点的支撑是充分的：它不仅证明了“item cache 能工作”，还证明了在不同 workload 形态下，动态选择 user prefix 和 item prefix 确实比任何单一策略更稳。相对不足之处在于，评估仍主要停留在 ranking 阶段和 `100` 候选商品规模，没有真正进入 retrieval 里上万候选的极端场景。

## 创新性与影响

相对于 _Zhai et al. (ICML '24)_ 这类 generative recommender 工作，Bat 的创新点不在模型更强，而在 serving 抽象发生了变化：它把 prompt order 变成了系统可以主动控制的杠杆，并用推荐语义为这种控制提供正当性。相对于 _Kwon et al. (SOSP '23)_ 以及后续通用 LLM prefix-caching 系统，Bat 的区别在于它不是被动缓存固定 prompt，而是先改变 prompt 结构，再围绕这个变化设计缓存放置与准入策略。相对于 _Hu et al. (ICML '25)_ 这类研究位置无关缓存的工作，Bat 更像是把类似思想落到一个具体 workload 上。

因此，这篇论文最可能影响两类读者。一类是正在尝试把 GR 真正部署到线上 ranking 里的工程团队，因为 Bat 直接回答了“生成式推荐太贵怎么办”这个现实问题。另一类是做系统研究的人，因为这篇论文很好地展示了 workload semantics 如何反过来塑造缓存对象、缓存放置和调度策略。

## 局限性

最大的局限是对基础模型的依赖。Bat 成立的前提是 item-as-prefix 不会显著伤害推荐质量，而论文自己也展示了这件事并非对所有模型都天然成立。实际部署时，这意味着系统方案的一部分变成了“挑选或微调一个能承受位置重排的 GR 模型”。

第二个局限是它默认商品描述相对稳定、热点分布明显。离线预计算 item KV cache、复制热点、后台更新长尾，这对广告和电商确实很合理；但如果 item 元数据频繁变动，或者热点变化比热度估计器更快，那么这套设计的收益可能会下降。

最后，论文只评估了 ranking 阶段，且主要集中在 `100` 候选商品规模。作者提到 retrieval 阶段可能有 `10K+` 候选，Bat 在那里也许更有潜力，但论文并没有给出实证。多模型 serving 和端到端推荐流水线也都留在了未来工作里。

## 相关工作

- _Zhai et al. (ICML '24)_ — HSTU 证明了大规模 generative recommender 在工业 ranking 中的价值，而 Bat 关注的是这一路线的 serving 成本问题。
- _Kwon et al. (SOSP '23)_ — PagedAttention 提供了分页式 KV cache 底座，Bat 建立在这类底座之上，但额外利用了推荐场景特有的 prompt 重排与商品前缀共享。
- _Hu et al. (ICML '25)_ — EPIC 研究 LLM serving 中的位置无关缓存，而 Bat 把相近思想用在更具体的推荐 workload 上，让 item prefix 具备可复用性。
- _Yao et al. (EuroSys '25)_ — CacheBlend 通过选择性重算 token 来弥补缓存复用带来的精度损失，这和 Bat 在部分基础模型上的 item-as-prefix 精度差距直接相关。

## 我的笔记

<!-- 留空；由人工补充 -->
