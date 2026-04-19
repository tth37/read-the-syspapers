---
title: "CacheBlend: Fast Large Language Model Serving for RAG with Cached Knowledge Fusion"
oneline: "CacheBlend 把多段可复用 RAG 上下文的 KV cache 先拼起来，再只重算少量高影响 token 的 KV，在几乎不掉质量的前提下把 TTFT 降低 2.2-3.3x。"
authors:
  - "Jiayi Yao"
  - "Hanchen Li"
  - "Yuhan Liu"
  - "Siddhant Ray"
  - "Yihua Cheng"
  - "Qizheng Zhang"
  - "Kuntai Du"
  - "Shan Lu"
  - "Junchen Jiang"
affiliations:
  - "University of Chicago/CUHK Shenzhen"
  - "University of Chicago"
  - "Stanford University"
  - "Microsoft Research / University of Chicago"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696098"
code_url: "https://github.com/LMCache/LMCache"
tags:
  - llm-inference
  - caching
  - gpu
  - datacenter
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CacheBlend 要补的是 prefix caching 太保守、full KV reuse 太冒险之间的空档。它先复用每个上下文块的预计算 KV cache，再只对真正受跨块注意力影响的少量 token 做 selective recompute，并把这段额外工作和 KV 加载流水化。论文在四个数据集、三个开源模型上报告 TTFT 降低 2.2-3.3x，而且质量损失很小。

## 问题背景

RAG 这类系统经常把多个检索到的文本块连同用户问题一起送进 LLM。模型必须先完成整段输入的 prefill，生成 KV cache，之后才能吐出第一个 token，所以长上下文会直接把 TTFT 拉高。论文给出的背景数字是，约 4K token 的输入在单张 A40 上做 prefill，Llama-34B 约需 3 秒，Llama-70B 约需 6 秒。

直觉上当然应该复用 KV cache，但现有两类办法都不够用。Prefix caching 很稳，因为前缀的 KV 不受后缀影响，所以结果和 full recompute 一致；可是在 RAG 里，真正有用的上下文往往分散在多个 chunk 中，只有第一个 chunk 能被它复用。另一条路是类似 PromptCache 的 full KV reuse，它通过位置修正让 chunk 的 KV 能放到非前缀位置，不过这样仍然缺失前面 chunk 到后面 chunk 的 cross-attention，而多跳问答偏偏最依赖这种跨块关联。

## 核心洞察

这篇论文最重要的判断是，想把质量拉回 full prefill，并不需要把整段输入再跑一遍。Full KV reuse 真正错得厉害的，不是所有 token，而是那些特别依赖前序 chunk 信息的少数 token。只要把这些 token 的 KV 在每一层补算回来，forward attention matrix 就能逼近 full recompute，而成本仍然更接近 reuse。

作者之所以敢这样做，有两条经验观察支撑。第一，attention 本身是稀疏的，所以真正出现大 KV deviation 的 token 往往只占 10%-15%。第二，相邻层里高偏差 token 的排序有明显相关性，所以系统可以逐层逼近该重算的位置，而不必先知道完整正确答案。

## 设计

CacheBlend 从每个可复用文本块各自独立预计算的 KV cache 出发。服务请求时，它先把这些 chunk 的 KV 拼起来，并为非前缀块恢复正确的位置编码；之后不是做一次完整 prefill，而是逐层执行 selective KV recompute。在某一层里，系统只为选中的 token 计算 `Q`、`K`、`V`，再把新算出的条目与其余 token 的复用条目合并，然后照常走 attention。于是如果重算比例是 `r%`，额外计算量大致也是 full prefill 的 `r%`。

真正难的是，怎样在不知道 full recompute 结果的情况下，找出那些 high-KV-deviation tokens。CacheBlend 的办法是 gradual filtering。第一层先根据 token 级别的 attention deviation 选出一批略多的候选；之后几层只对这些候选继续重算，并不断收缩集合，直到接近目标比例。它依赖的是多层连续筛选后的稳定性。

系统层面的配合同样关键。CacheBlend 把第 `i` 层的 selective recompute 和第 `i+1` 层的 KV 加载做成流水线，这样只要重算时间不超过加载时间，额外计算几乎就能被隐藏在存储访问之后。控制器会结合离线测得的模型 prefill 时间、存储吞吐和最低质量要求来选 recompute ratio 与存储介质。论文中的经验下限是 15%。

## 实验评估

实验覆盖 Mistral-7B、Yi-34B、Llama-70B；硬件是带 A40 GPU、128 GB RAM 和 1 TB NVMe SSD 的 Runpod 机器。工作负载包括 2WikiMQA、Musique、SAMSum、MultiNews，以及由 top-6 检索 chunk 构造出来的扩展 RAG traces。

最核心的结论很稳定。相对 full KV recompute，CacheBlend 在不同模型和任务上把 TTFT 降低 2.2-3.3x，同时把吞吐提升 2.8-5x。按论文的汇总图，F1 或 Rouge-L 相比 full recompute 和 prefix caching 的差距通常控制在 0.02 以内；若拿它和 full KV reuse 比，延迟几乎一样，但问答任务能多出 0.1-0.2 的绝对 F1，摘要任务能多出 0.03-0.25 的 Rouge-L。

实验设计有一处还刻意帮了 baseline。Prefix caching 的对照实验假设从 RAM 或 SSD 加载到 GPU 没有任何额外延迟，这在真实系统里其实很难成立。敏感性分析也支持论文机制。以 Yi-34B 为例，只要重算 5%-18% 的 token，质量损失最多只有 0.002，但仍可获得 4.1-6.6x 的 TTFT 改善。

## 创新性与影响

这项工作的创新点不只是把 KV cache 用到非前缀位置，因为 PromptCache 已经试过那条路。CacheBlend 真正补上的，是如何把缺失的 cross-attention 用 selective recompute 捞回来，并且让这部分补算足够便宜，能被存储加载流水线掩蔽掉。这样一来，KV reuse 不再只是模板型 prompt 的优化，而开始适用于真正多块上下文协同的 RAG，对企业文档问答、知识库助手、长上下文 serving 尤其有价值。

## 局限性

论文明确承认，这套方法目前只验证了 transformer 架构，并且依赖 chunk reuse。如果请求之间几乎没有共享上下文，或者多数请求本来就是单块前缀复用，那 CacheBlend 的优势会明显缩小。Token 选择策略也主要建立在经验事实之上，而不是严格最优性证明。实验范围相对有限，只有三种模型、四个数据集，以及单节点 vLLM 部署；更换 serving engine 或跨节点共享 KV 仍留给后续工作。

## 相关工作

- _Gim et al. (arXiv '23)_ - PromptCache 允许 KV 在非前缀位置复用，但依然缺失 cross-attention；CacheBlend 针对的正是这部分误差。
- _Jin et al. (arXiv '24)_ - RAGCache 主要做面向前缀的 RAG KV 复用与管理，而 CacheBlend 关注的是多块文本在同一输入中融合时的非前缀复用。
- _Liu et al. (arXiv '23)_ - CacheGen 关注更快的上下文加载与压缩存储，CacheBlend 与它互补，因为后者解决的是多个已加载 chunk 的 KV 应该怎样融合才不伤质量。
- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention 优化的是 serving substrate 与 KV 内存管理，CacheBlend 则直接建立在这个 substrate 之上，继续削减复用上下文时的 prefill 成本。

## 我的笔记

<!-- 留空；由人工补充 -->
