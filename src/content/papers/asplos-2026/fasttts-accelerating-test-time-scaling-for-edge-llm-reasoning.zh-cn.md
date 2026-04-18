---
title: "FastTTS: Accelerating Test-Time Scaling for Edge LLM Reasoning"
oneline: "FastTTS 用 speculative beam extension、prefix-aware scheduling 和非对称 KV 分配，把 verifier-guided TTS 压进 24GB 边缘 GPU。"
authors:
  - "Hao Mark Chen"
  - "Zhiwen Mo"
  - "Guanxi Lu"
  - "Shuang Liang"
  - "Lingxiao Ma"
  - "Wayne Luk"
  - "Hongxiang Fan"
affiliations:
  - "Imperial College London, London, UK"
  - "Microsoft Research, Beijing, China"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790161"
tags:
  - llm-inference
  - gpu
  - scheduling
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FastTTS 把 verifier-guided 的 test-time scaling 当成单张边缘 GPU 上的 serving 问题来处理。它用 speculative beam extension 隐藏 beam straggler，用 prefix-aware scheduling 保住动态 prefix sharing，再用非对称 KV 分配协调 generator 和 verifier。结果是在 RTX 4090 上相对 vLLM 基线把 goodput 平均提高到 `2.2x`，并把完成延迟降低 `38%-68%`。

## 问题背景

论文的出发点是边缘推理里的一个现实矛盾。消费级 GPU 往往只有 `8-24 GB` 显存，所以端侧通常只能部署 `<= 7B` 的小模型，这些模型在复杂推理上明显落后于云端大模型。TTS 试图通过增加推理时计算来弥补这件事，但若直接套到现有 serving 栈上，系统代价会失控。论文的动机实验显示，基于 vLLM 的朴素实现为了追上云模型准确率，延迟会到约 `200 s`，几乎把算法价值全部吃掉了。

原因在于 verifier-guided TTS 不是普通的自回归解码。generator 会并行扩展多条 reasoning path，verifier 给中间步骤打分，然后高分路径继续分叉。这个循环同时制造三类瓶颈：beam 长度不规则会产生 straggler 和 GPU 空等；beam 之间虽然共享 prefix，但共享关系只在运行时才出现，若调度不利用它就会频繁驱逐和重算 KV cache；generator 和 verifier 还必须共置在一张消费级 GPU 上，极小的显存预算会进一步压缩批量能力与吞吐。作者强调，这些问题会跨多种 TTS 变体反复出现，因此真正要做的是 verifier-guided 树搜索的边缘运行时。

## 核心洞察

FastTTS 的核心洞察是：多数有效 TTS 方法共享同一个 generation/verification 骨架，而这个骨架在运行时恰好有几个可利用的可预测性。上一轮 verifier score 足以作为 speculative 候选选择的廉价代理；beam 间 prefix overlap 只要调度顺序正确，就能转化成真实的 KV cache 重用；generator 与 verifier 对 KV-cache 大小的敏感度又明显不同。于是，瓶颈不只是搜索算法，而是运行时没有把这些结构映射成高效的 GPU 执行。

其中最重要的是两模型的不对称性。论文的 profiling 显示，verifier 的大批量 prefill 在不到 `1 GB` 的 KV cache 下就能接近 `80%` 峰值吞吐，而 generator 的 decoding 想达到类似相对吞吐，需要大约 `5-10x` 更多 KV 空间。再考虑到较短 beam 会先结束并腾出执行槽位，系统上的答案就很明确：用这些空槽位去 speculative 地跨过 straggler，把 beam 顺序改成更利于 prefix reuse 的顺序，并把显存优先分给当前更敏感的一侧，而不是平均分配。

## 设计

FastTTS 以 vLLM `0.9.2` 为底座实现，总代码约 `6,500` 行 Python，generator 与 verifier 运行在独立 worker process 中。第一项优化是 Speculative Beam Extension。在一轮 reasoning step 里，系统继续为未完成 beam 正常生成 token；当某些 beam 较早结束时，它把新空出的 batch 槽位用于 speculative 地扩展更有希望的 beam，候选由上一轮 verifier score 决定。等真正 verifier 运行后，FastTTS 只验证非 speculative 前缀，并在复制分支时裁掉 speculative continuation，尽量保持与原搜索算法等价。基于同一思路，LookAhead Verification 把“当前 step”和“已经 speculative 出来的下一 step”合并成一次 verifier 请求，以复用 verifier 的 KV cache。

驱动这一机制的是 two-phase scheduler。正常情况下，Continuous Beam Batching 尽量把当前请求的所有活跃 beam 持续留在 batch 中，以降低单请求延迟；若等待队列为空，就进入 speculative phase；若新请求到来或内存压力升高，speculative 工作会被立即丢弃。论文在这里的重点很明确：它不是偷偷拿交互性换吞吐。

另外两项优化直接面向内存浪费。Dynamic Prefix-Aware Scheduling 把 beam 排序问题写成“最小化相邻 batch 的 KV-cache 驱逐量”，并用一个 greedy heuristic 在不打乱父节点顺序的前提下尽量把同父 beam 排在一起。Asymmetric Multi-Model Memory Allocation 则用 roofline-guided 延迟模型和一轮很小的线性搜索，决定 verifier 与 generator 各拿多少 KV cache；如果显存极端紧张，FastTTS 还会把这个方案与 CPU offloading 的预测延迟比较后再选。

## 实验评估

这篇论文的实验设置和主张的目标场景是对齐的。主平台就是单张 RTX 4090、`24 GB` 显存和一颗 Intel Xeon Silver 4310 CPU。作者测试了三种 generator/verifier 组合：`1.5B+7B`、`7B+1.5B` 与刻意压缩显存预算的 `1.5B+1.5B`，工作负载则是 AIME 2024 与 AMC 2023 上的交互式单请求（`batch size = 1`）。此外还有 HumanEval 和更小显存 GPU 的补充实验。

主结果基本支撑了中心论点。跨多种 search algorithm，FastTTS 相对基线的 precise goodput 提升为 `1.2x-3.9x`。在论文重点分析的 beam search 设置下，FastTTS 在 beam 数 `8-512` 范围内平均取得 `2.2x` 的 goodput 提升，最高达到 `5.4x`，同时把 end-to-end completion latency 降低 `38%-68%`。延迟分解也不是摆设：verifier latency 降低 `75%-85%`，和 LookAhead Verification 的局部性故事一致；generator latency 降低 `36%-66%`，和 speculative execution 加内存管理的机制一致。

算法质量部分也比较克制。Top-1 accuracy 基本保持不变，在 AIME 上甚至略升；Pass@N 在大 `N` 时与基线接近，在小 `N` 时略高。作者把后者解释为调度副作用，而不是宣称搜索算法更强，这个说法是可信的。补充实验虽然没有主实验那么深入，但方向一致：在 RTX 3070 Ti 与 4070 Ti 上，FastTTS 仍有 `1.4x-1.6x` 提升；在 HumanEval 上有 `1.3x-1.8x` 提升。ablation 也与设计相符：speculation 往往贡献最大，prefix-aware scheduling 在紧内存时最重要，而当工作集大多已能放进 KV cache 时，内存优化的边际收益会变小。

## 创新性与影响

和 _Kwon et al. (SOSP '23)_ 相比，FastTTS 不是另一个通用 serving substrate，而是建立在这类底座之上的 TTS 专用运行时层。和 _Agrawal et al. (OSDI '24)_ 相比，它处理的也不是请求流，而是单个 reasoning 请求内部的搜索树。和 _Fu et al. (arXiv '24)_ 相比，FastTTS 更进一步，把 beam search 本身当成可调度的系统工作负载。因此，这篇论文对两类人都有价值：一类是想把 edge agent 真正跑起来的工程团队，另一类是把 reasoning runtime 当成独立研究对象的系统研究者。

## 局限性

论文的适用范围其实比动机部分更窄。FastTTS 围绕 discriminative PRM 设计，明确没有把 generative PRM 或 MCTS 这类更昂贵的搜索形式纳入重点。最扎实的实验也集中在数学与代码推理、`batch size = 1` 的交互式场景，因此对多用户混合流量和复杂服务队列说得不多。部署上也不是零成本：系统依赖 profiling 与轻量性能模型，prefix-aware scheduler 是 greedy heuristic 而非全局最优，而且 ablation 已经表明，一旦显存足够充裕，若工作集大多能留在 KV cache 中，它的一些关键收益就会明显减弱。FastTTS 因而最适合的，正是论文锁定的资源受限边缘场景。

## 相关工作

- _Kwon et al. (SOSP '23)_ — PagedAttention 让 LLM serving 的 KV-cache 管理变得可行，而 FastTTS 在其之上增加了面向树状 reasoning 的 beam 级调度和 verifier 感知执行。
- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 通过 chunked prefill 改善标准 LLM serving 的吞吐/延迟权衡，而 FastTTS 处理的是单个 reasoning 请求内部不规则的 verifier-guided search。
- _Fu et al. (arXiv '24)_ — Certaindex 关注 query 级别的 LLM reasoning 效率，FastTTS 则更深入到 beam 级 straggler、动态 prefix reuse，以及 generator/verifier 共置问题。
- _Sheng et al. (ICML '23)_ — FlexGen 通过 CPU 与 SSD offloading 扩展可用内存，而 FastTTS 关注的是在单张边缘 GPU 上更高效地分配有限的 KV-cache 预算。

## 我的笔记

<!-- 留空；由人工补充 -->
