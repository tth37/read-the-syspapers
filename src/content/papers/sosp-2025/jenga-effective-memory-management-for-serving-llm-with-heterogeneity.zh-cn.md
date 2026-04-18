---
title: "Jenga: Effective Memory Management for Serving LLM with Heterogeneity"
oneline: "Jenga 用 LCM 大页和 attention-aware 缓存策略替换同质化 KV 分页，让异构 LLM 在同样显存下容纳更大 batch。"
authors:
  - "Chen Zhang"
  - "Kuntai Du"
  - "Shu Liu"
  - "Woosuk Kwon"
  - "Xiangxi Mo"
  - "Yufeng Wang"
  - "Xiaoxuan Liu"
  - "Kaichao You"
  - "Zhuohan Li"
  - "Mingsheng Long"
  - "Jidong Zhai"
  - "Joseph Gonzalez"
  - "Ion Stoica"
affiliations:
  - "Tsinghua University"
  - "UC Berkeley"
  - "University of Chicago"
  - "Independent Researcher"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764823"
code_url: "https://github.com/heheda12345/Jenga-SOSP25-AE"
tags:
  - llm-inference
  - memory
  - caching
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Jenga 的出发点是：PagedAttention 默认所有层都共享同一种 page 格式，但现代 LLM 的每层状态大小和 token 依赖关系已经不再统一。它用基于 LCM 的两级分页分配器和按层定制的 prefix cache 策略替换这一假设。在 vLLM 中，这让异构模型能容纳更大的 serving batch，并在不损伤低负载延迟的前提下把吞吐提升到 1.39x-2.16x。

## 问题背景

论文抓住的是一个越来越常见、但底层 runtime 还没有跟上的变化。现有 serving 引擎默认每一层都会为每个 token 产生同构的缓存状态，而且所有层都需要保留同样多的历史 token。这对早期全 attention Transformer 是成立的，但对今天的异构模型已经不成立：VLM 混合文本 KV cache 与不同尺寸的 vision 或 cross-attention 状态，Gemma-3 与 Ministral 混合 full attention 和 sliding-window attention，Jamba/Hymba 又加入更大的状态空间层。在这种模型上，统一 page 布局会产生严重浪费：论文报告 Llama 3.2 11B Vision 在 MMMU-pro 上有 79.6% 的内存浪费，Gemma-3 在真实 trace 衍生工作负载上有 73.6% 的浪费。Prefix caching 也因此更难做，因为模型级命中率受最差那类层限制。

## 核心洞察

Jenga 的核心主张是：LLM serving 的内存管理应该跟踪 layer property，而不是把所有缓存状态都看成可互换的 KV page。论文把每种层抽象成三个行为：它的 `page_size`，生成未来 token 时真正还需要的 `active_pages`，以及怎样的缓存模式算作合法的 `possible_prefix` 命中。把这些属性显式化之后，runtime 就能把所有 page size 做最小公倍数形成全局大页，再切出各类小页，同时为不同 attention 机制定制 eviction 和 cache-hit 规则，并保持跨层命中平衡。

## 设计

Jenga 主要由三部分组成。第一部分是两级 allocator。全局 allocator 管理大小为所有 page size 的 LCM 的大页；每种层类型再各自维护小页 allocator，把大页切分成 full attention、sliding window、Mamba state、vision embedding 等不同规格的小页。与此同时，Jenga 根据 `active_pages` 在 token 不再参与未来计算时立即回收其页面，而不是把全部历史 KV 一直挂着。

第二部分是执行兼容性。Jenga 把物理布局从“先按层分，再按页分”改成“先按页分，再按层分”，但它没有要求重写 attention kernel。系统只需为每一层准备 `KV_cache_start_ptr`、执行时的 page size 和 page ID 等元数据，就能继续复用 vLLM/PagedAttention 的 worker。

第三部分是可定制的 prefix caching。Jenga 只更新当前 generation step 真正活跃页面的 last-access time，因此 sliding-window 层会自然优先淘汰旧 token，而 full-attention 层则保留整个活跃前缀。命中规则也按层定制：sliding-window 层只要求相关后缀仍在，local attention 只要求当前 chunk，Mamba 层则每 512 个 token 缓存一次状态。除此之外，Jenga 还增加了一个 common page pool，通过最近请求预测可能再次出现的公共前缀页面。

## 实验评估

实现大约是 4 KLOC Python，直接改在 vLLM 里。评估平台包含 H100 80 GB 和 L4 24 GB，模型覆盖 Llama 3.2 Vision、Gemma-3、Ministral、Llama 4、Jamba、PyramidKV 等多种异构模型，工作负载来自 MMMU-pro、MMLU-pro 和 arXiv-QA。主基线是 vLLM v0.8.3，只替换其中的 memory manager；另外还比较了两种更朴素的异构扩展方案 Static Partition 和 Max Page，因此核心对比相对干净。

主结果是有说服力的。Jenga 在 H100 上把端到端吞吐最高提升到 1.73x，在 L4 上最高提升到 2.16x，平均分别是 1.46x 和 1.65x。低负载时它并不靠牺牲单请求延迟换吞吐：以 Llama 3.2 Vision 为例，请求率较低时平均延迟与 vLLM 只差 4.2%。负载升高后，碎片减少转化成更大的 batch 和更低的排队延迟，TTFT 最多可降低 23.4x。分解实验也支持其机制解释：在 Ministral trace 上，vLLM 平均浪费 38.2% 的 KV 内存，而 Jenga 降到 0.04%；平均 decode batch size 提升到 5.39，而 vLLM、SGLang、TGI 大约只有 2.5-2.7。Prefix-cache 定制让命中率最高提升 1.60x、吞吐最高提升 1.77x。Llama 4 在单个 8xH200 节点上的最大上下文长度则从 vLLM 的 3.7M 提升到 14.7M。

## 创新性与影响

和此前 serving 工作相比，Jenga 的创新点不是“再加一个缓存小技巧”，而是把 page-based serving 从单一 KV 抽象推广成带类型的内存底座：分配、释放、淘汰和命中语义都由层的行为决定。这会影响需要同时支持 VLM、hybrid attention 和状态空间模型的 serving runtime，也会影响那些不断发明新 attention 或 KV 压缩方案、但不想重写 serving 栈的研究者。

## 局限性

论文也留下了一些明显边界。多模型 serving 在 speculative decoding 之外仍被明确留作 future work。Common-prefix predictor 默认短时间内会反复出现相同前缀；如果工作负载缺乏这种局部性，common page pool 的收益就会下降。部分实验使用的是模拟工作负载而非线上 trace，因此外推到真实生产环境时仍要保留谨慎。实现与覆盖面也有限：Jenga 主要作为 vLLM 的修改版本来评估，没有给出与 SGLang 或 TGI 的完整端到端比较；Hamba 没有进入评估，因为 vLLM 当时缺少必要 kernel；而像“每 512 个 token 缓存一次 Mamba 状态”这样的策略仍然带有启发式色彩。

## 相关工作

- _Kwon et al. (SOSP '23)_ - PagedAttention/vLLM 让持续式 LLM serving 变得可行，但它假设所有层共享统一的 page 格式和统一的 prefix-cache 语义。
- _Agrawal et al. (OSDI '24)_ - Sarathi-Serve 用 chunked prefill 改善吞吐与延迟折中，而 Jenga 修改的是这些调度策略之下的异构内存底座。
- _Zhong et al. (OSDI '24)_ - DistServe 把 prefill 与 decode 拆到不同资源上；Jenga 与其正交，关注的是单个引擎内部如何存放和复用异构缓存状态。
- _Yu et al. (OSDI '22)_ - Orca 推广了 transformer serving 的 continuous batching，但没有把“按层异构的内存行为”纳入其 batching 抽象。

## 我的笔记

<!-- empty; left for the human reader -->
