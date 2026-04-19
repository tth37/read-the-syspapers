---
title: "Stateful Large Language Model Serving with Pensieve"
oneline: "Pensieve 把多轮对话的 KV 状态留在 GPU/CPU 两级缓存里，并用支持非连续内存的多 token attention 避免每轮都重跑整段聊天历史。"
authors:
  - "Lingfan Yu"
  - "Jinkun Lin"
  - "Jinyang Li"
affiliations:
  - "New York University"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696086"
tags:
  - llm-inference
  - caching
  - gpu
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pensieve 把多轮聊天服务从「每轮把整段历史再 prefill 一次」改成了真正有状态的 KV 复用系统。它把会话历史放进 GPU/CPU 两级缓存，在必要时只重算被丢掉的前缀，并把 vLLM 的 PagedAttention 推广成可处理非连续上下文的多 token attention kernel。论文在 ShareGPT 和 UltraChat 上报告，13B 模型吞吐可提升 1.14-1.70x，70B 模型最高可到 3.0x。

## 问题背景

现有 LLM serving engine 基本都是跨请求无状态的。对多轮对话来说，这意味着每次用户追问时，系统都得把完整聊天记录重新拼进 prompt，再把整段历史从头 prefill 一遍。随着对话变长，真正拖慢系统的很快就不再是 decode，而是重复处理历史上下文。论文用一个 batch=32、每个请求生成 200 个 token 的例子说明，只要历史上下文增长到几千 token，prefill 成本就会明显压过 generation。

看起来最直接的办法是缓存旧的 KV state，但真正落地会碰到三个障碍。第一，GPU 内存太紧。论文给出的 13B、40 层、hidden size 5120 的例子里，一个 token 跨所有层的 KV 状态大约就要 0.78 MB，所以显存里根本放不下太多活跃会话。第二，若按整段会话来 swap，空间利用率差，恢复延迟也大。第三，一旦有些历史 token 被换到 CPU 或直接丢弃，剩余上下文在逻辑上仍是一整段历史，但在物理上已经碎片化，而现有 prefill kernel 默认上下文在 GPU 上是连续存放的。

## 核心洞察

Pensieve 最关键的判断是：会话历史不该只被当作单次请求的临时工作区，而该被当成可管理的 cache。只要系统在 token chunk 粒度上管理 KV，把更老、且重算更便宜的部分优先逐出，大多数后续轮次就不必再重放整段聊天记录，而是直接复用已有 attention state。

这里最重要的是「从前面丢」。原因不复杂：在 causal attention 下，越靠后的 token 需要看见的历史越长，所以重算成本更高；越靠前的 token 反而更便宜。Pensieve 因此把最近活跃时间和重算代价结合起来排序，让系统优先丢掉历史前端那些便宜 chunk。等下一轮请求到来时，再把缺失前缀补算回来，把 CPU 里的中段换回 GPU，把 GPU 里还在的尾段继续复用。模型语义不变，变的只是 KV state 的存放位置。

## 设计

Pensieve 的总体结构是一个 scheduler 配多个 worker，每个 worker 负责一张 GPU。它采用 iteration-level batching，但和 ORCA、vLLM 不同，Pensieve 不把 prefill 与 decode 拆成两条完全分离的执行路径。批里已有请求各贡献一个刚生成的 token，新到请求则贡献整段 prompt token。这样做的价值在于，系统不必为了少量新请求单独启动小型 prefill kernel，而能把新老请求合到一个执行步里，提高 GPU 利用率。

KV state 存在两级缓存中：GPU 是第一层，CPU 是第二层。Pensieve 把 KV 按 32-token chunk 分组，并给每个 chunk 计算 retention value：一边考虑该 chunk 的重算成本，一边考虑该会话离上次活跃过去了多久。分数低的 chunk 先被逐出。当 GPU 可用空间跌到例如 25% 以下时，系统会提前把选中的 chunk 异步换到 CPU，让逐出延迟尽量被正在进行的 GPU 计算掩蔽掉；同时还会保留 10% 的 GPU slot 给正在 decode 的请求，降低运行中被迫挂起的概率。

如果 CPU cache 也满了，Pensieve 就进一步丢弃 chunk，而且尽量从会话历史的前端开始丢。下一轮同一会话再来请求时，已经丢掉的那部分会从持久化保存的原始对话文本中取回，直接 prepend 到新 prompt 前面重新计算；留在 CPU 的中间段则按 layer 逐步换回 GPU，并用 GPU event 和模型执行做流水重叠。于是，一次请求看到的逻辑上下文会变成四段：重算前缀、从 CPU 换回的中段、仍留在 GPU 的后段，以及最新 prompt。

最难的一步是如何在这种碎片化上下文上做 attention。vLLM 的 PagedAttention 已经能处理非连续 KV cache，但它只适用于 decode 时每个请求恰好一个 query token 的情形。Pensieve 基于 PyTorch fused attention 和 NVIDIA Cutlass 做了新的 multi-token attention kernel，让 prefill 也能在非连续 KV 上运行，并同时支持 ragged query 长度与 fused causal masking。对于「前缀被丢、后面还在」这种情况，Pensieve 会把请求拆成两个共享同一底层上下文的子请求，从而避免额外拷贝。

## 实验评估

实验平台是 Azure NC A100 v4，配 A100-80GB GPU、24 核 AMD EPYC CPU，以及每张 GPU 220 GB 的 CPU 内存，并且对所有系统统一给 40 GB/GPU 的 KV cache 预算。工作负载来自两个多轮对话数据集：ShareGPT 有 48,159 段对话、平均 5.56 轮；UltraChat 有 1,468,352 段对话、平均 3.86 轮。模型覆盖 OPT-13B/66B 和 Llama 2-13B/70B。值得注意的是，论文把 Llama 2-13B 改成了 10 个 KV heads 的 GQA 版本，这会让缓存更省空间，也更贴合 Pensieve 的设计优势。

核心结果基本支持论文主张。单卡上，在 ShareGPT 中，Pensieve 对 OPT-13B 在 120 ms/token 下的吞吐达到 vLLM 的 1.36x、TensorRT-LLM 的 1.14x；对 Llama 2-13B 在 180 ms/token 下分别达到 1.70x 和 1.58x。四卡 ShareGPT 上，Pensieve 对 OPT-66B 在 200 ms/token 下达到 vLLM 的 2.04x、TensorRT-LLM 的 1.64x；对 Llama 2-70B 在 400 ms/token 下分别达到 3.0x 和 2.47x。趋势也和机制一致：ShareGPT 的平均轮数更高，所以收益比 UltraChat 更明显；带 GQA 的 Llama 模型 KV 更省，因此收益也更大。

微基准同样很关键。Pensieve 的 multi-token kernel 基本追平理想的连续内存 attention，而「先 copy 成连续再算」和「多轮调用单 token PagedAttention」两种替代方案都有明显额外开销。缓存策略方面，Pensieve 在高负载下比朴素 LRU 更好，CPU cache hit rate 最多高出 4.4 个百分点，重算的 KV token 数量最多少 14.6%。不过评估也有一个明显空白：论文只和无状态基线比较，没有直接对比后续出现的 stateful attention-cache 系统。

## 创新性与影响

Pensieve 的创新点不在模型算法，而在 serving substrate。它把三个通常分开讨论的问题绑在一起解决：按重算成本做 cache eviction、把 KV 在 GPU/CPU 间异步迁移，以及让 prefill 能在非连续内存上执行的 attention kernel。正是这三个部分一起成立，才让「缓存聊天历史」从一句正确但空泛的话，变成了一个真正可运行的系统。

这篇论文最可能影响的是后续的 LLM serving engine、KV offload 系统，以及面向多轮聊天的推理栈。凡是想在不改变模型输出的前提下复用 attention state 的工作，都很难绕开它；而对系统研究者来说，它也提供了一个很具体的例子，说明 batching、内存布局与 kernel 设计必须联动考虑。

## 局限性

Pensieve 的收益高度依赖多轮会话的时间局部性。用户思考时间一拉长，cache hit rate 就会下降；论文在平均 600 秒 think time 下仍优于 vLLM，但优势已经明显收窄。它也不处理跨用户共享，只把系统 prompt 的复用留给人工指定，因此对更一般的 prefix sharing 问题并没有给出统一解法。

实验范围也有限。论文选择的基线很强，但都是无状态系统，所以我们无法从文中判断它相对 CachedAttention 这类后续 stateful 系统还能领先多少。Llama 2-13B 还被改成了 GQA 版本，这会放大缓存密度优势。除此之外，评估基本局限在 A100 级硬件、两个数据集，以及最多 16,384 token 的上下文。

## 相关工作

- _Kwon et al. (SOSP '23)_ - vLLM 在单次请求内部引入 paged KV memory，而 Pensieve 把这种状态跨请求保留下来，并补上了多 token prefill 的 attention 路径。
- _Yu et al. (OSDI '22)_ - ORCA 奠定了 iteration-level batching 的基础，但它仍把请求视为无状态对象，也没有处理多轮对话中的 cache recovery。
- _Gao et al. (USENIX ATC '24)_ - CachedAttention 同样面向多轮会话，不过它按整段会话管理缓存；Pensieve 则在 token chunk 粒度上从前端逐出，并在需要时补算前缀。
- _Gim et al. (PMLSys '24)_ - PromptCache 复用的是应用显式声明的 prompt 模块，而 Pensieve 针对的是自然增长的会话状态，不要求用户事先写出 schema。

## 我的笔记

<!-- 留空；由人工补充 -->
