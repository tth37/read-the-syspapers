---
title: "IC-Cache: Efficient Large Language Model Serving via In-context Caching"
oneline: "IC-Cache 把历史请求-响应对变成 in-context 示例，再按预测质量和系统负载在大小模型间路由请求，以更低成本和更低延迟完成 LLM serving。"
authors:
  - "Yifan Yu"
  - "Yu Gan"
  - "Nikhil Sarda"
  - "Lillian Tsai"
  - "Jiaming Shen"
  - "Yanqi Zhou"
  - "Arvind Krishnamurthy"
  - "Fan Lai"
  - "Henry M. Levy"
  - "David E. Culler"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "Google"
  - "Google & University of Washington"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764829"
tags:
  - llm-inference
  - caching
  - scheduling
  - datacenter
category: llm-serving
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

IC-Cache 的核心主张是，历史 LLM 交互更适合被当作 demonstrations，而不是直接复用的缓存答案。它先检索少量高效用的 request-response pairs，把它们拼到新请求前面，让小模型模仿大模型，再用负载感知的 bandit 在不同模型之间路由请求。论文在 realistic traces 上报告了 1.4x-5.9x 的吞吐提升和 28-71% 的延迟下降，同时 judged quality 基本不受影响。

## 问题背景

LLM serving 一直被质量、延迟和成本三者挤压。大模型回答更好，但更慢、更贵；论文基于 Microsoft Azure trace 展示，分钟级峰值负载可达低谷的 25 倍，所以运营者不能简单把全部请求都扔给最贵的模型。

历史请求看起来是最自然的突破口：在 MS MARCO、Natural Questions 和 LMSys-Chat 上，超过 70% 的请求都能找到一个余弦相似度高于 0.8 的请求。但 semantic caching 不够。精确匹配很少，而直接返回最相似缓存答案会把 win rate 从 50% 拉低到 18%，因为语义接近的问题仍可能需要不同回答。真正的问题不是找到相似文本，而是把重复流量变成有用指导，而不是重复旧答案。

## 核心洞察

IC-Cache 的关键观点是，旧 request-response pairs 更适合当 demonstrations，而不是当答案。若这些样本来自更强模型，把它们拼到新 prompt 前面，就能帮助小模型模仿大模型的结构、推理方式和细节程度，从而把重复流量变成 live capability augmentation。

但 utility 不等于 relevance。一个语义相近的例子，可能因为答案质量差、和其他例子冗余，或者小模型本来就会，而几乎没有价值。因此 IC-Cache 把三件事绑在一起：按 predicted helpfulness 选例子、按质量和负载路由请求、并随着流量变化持续改进 cache。

## 设计

IC-Cache 部署在 vLLM、HuggingFace Runtime 或 LangChain 这类 backend 前面。每个请求都要经历检索 examples、选择模型、以及更新 example pool 三步。

Example Selector 是两阶段的。它先用 dense embeddings 找到语义相关候选，并用规模约为 `sqrt(N)` 的离线聚类保持检索可扩展；再用轻量 proxy model，根据 preference feedback 或抽样质量检查来估计这些候选对当前请求和目标模型的真实 helpfulness。系统选的是一组 examples，而不是简单的 top-k 相似项，并会在线调整全局 utility threshold，只有当额外 demonstrations 值回它们带来的 prompt 成本时才继续保留。

Request Router 是一个 contextual multi-armed bandit，上下文包含请求和选中的 examples，arms 则是候选模型。它用稀疏反馈在线更新，而不是为每个请求穷举标注所有模型。为应对突发负载，router 维护 serving load 的指数滑动平均，并只在超阈值时用 tanh bias 压低昂贵模型的选择分数。

Example Manager 负责长期 cache quality。它会在预期收益高于重放成本时离线 replay 老 examples 并保留更好的响应，再用一个一维 knapsack 在 example 大小和 offloading 价值之间做权衡来限制缓存大小。论文还加入了域隔离、客户端 PII 清洗和可选的差分隐私 synthetic cache。

## 实验评估

原型约 3 KLOC，使用 FAISS 检索、JAX router 和 gRPC 组件。实验在 16 张 A100 上完成，请求来自受 Microsoft trace 启发的 arrival trace，数据覆盖 conversation、search QA、translation、code generation 和 math reasoning 等数百万条请求，模型则包括 Gemini、DeepSeek-R1、Qwen2.5、Gemma-2 和 Phi-3。

端到端结果是，IC-Cache 在不损害 judged quality 的前提下，把吞吐提升 1.4x-5.9x，把延迟降低 28-71%。在线 trace 上，它相较 RouteLLM 在相近吞吐和延迟下还能给出 9% 更高的响应质量。在 Natural Questions 上，它在相同 50% win rate 下实现 2.3x 更高吞吐；在 MS MARCO 上，选择性路由的 Gemma-2-2B + IC-Cache 对 Gemma-2-27B 的 win rate 超过 50%。

分项结果也支持论文机制。两阶段 selector 的额外开销不到 1%。在无竞争测试下，Gemma-2-2B + IC-Cache 比 Gemma-2-27B 快 71%，并在相同资源预算下提供 5.1x 更高吞吐。对于部分 translation 和 code generation 任务，只需几万条 plaintext examples、总大小不到 20 MB，就已经接近饱和质量。

## 创新性与影响

IC-Cache 的新意在于它的系统化 framing：把历史流量看成在线蒸馏信号，并围绕这一点共同设计 example retrieval、model routing 和 cache maintenance。它不同于 semantic caching，后者重放旧答案；也不同于纯 router 工作，后者选模型，但不会改变小模型在推理时能看到什么。

因此，这项工作对多模型 LLM fleet、edge/cloud assistant，以及任何已经保存请求历史或偏好反馈的 serving 系统都有现实意义。

## 局限性

IC-Cache 最适合重复性高的 workload。如果流量高度新颖，或者语义相近的请求仍需要明显不同的输出，example pool 的价值就会下降。它也会增加 prefill 时间，因为每个 offloaded request 都多带了一些 demonstrations。

此外，这套设计依赖反馈质量和后台资源。Proxy model 与 bandit 需要 preference 或 judged-quality 信号，replay 假设离峰期有额外算力，而默认 plaintext cache 也带来隐私压力。论文给出了清洗和 DP synthesis 方案，但 DP cache 会损失一部分质量。多数实验也仍是把公开数据集映射到 realistic traces，而不是完整的生产部署。

## 相关工作

- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention 解决的是单个模型内部的 KV-cache 效率问题，而 IC-Cache 通过复用历史 request-response pairs 改变了“哪个模型可以服务这个请求”。
- _Ong et al. (arXiv '24)_ - RouteLLM 学习在大小模型之间做路由，但它既不会用 in-context examples 增强小模型，也不会在过载时显式调整决策偏好。
- _Zhao et al. (EMNLP '24)_ - LongRAG 检索的是外部文档来做长上下文问答，而 IC-Cache 检索的是历史模型交互，用来迁移回答结构和推理风格，而不只是补充静态文本。
- _Yu et al. (OSDI '22)_ - Orca 通过 continuous batching 提高 serving throughput，而 IC-Cache 与之互补，因为它扩大了便宜模型能够处理的请求集合。

## 我的笔记

<!-- 留空；由人工补充 -->
