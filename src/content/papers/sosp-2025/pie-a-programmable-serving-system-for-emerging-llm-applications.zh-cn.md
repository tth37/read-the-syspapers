---
title: "Pie: A Programmable Serving System for Emerging LLM Applications"
oneline: "Pie 把固定的 LLM serving loop 改成可编程 inferlet，让应用直接控制 KV 页、生成步骤与工具 I/O。"
authors:
  - "In Gim"
  - "Zhiyao Ma"
  - "Seung-seob Lee"
  - "Lin Zhong"
affiliations:
  - "Yale University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764814"
code_url: "https://github.com/pie-project/pie"
tags:
  - llm-inference
  - caching
  - scheduling
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Pie 认为，新一代 LLM 应用已经不适合被塞进一个封闭的 prefill-decode 循环。它把 LLM serving 暴露成一组细粒度 handler，由用户程序 inferlet 组合调用，从而在同一运行时内直接控制 KV cache、解码步骤和外部 I/O。对普通 text completion，它只带来 3-12% 的延迟代价；但对更复杂的 workflow，它能带来 1.1x-2.4x 更低延迟和 1.3x-3.4x 更高吞吐。

## 问题背景

这篇论文的出发点，是现代 LLM 应用和主流 serving stack 之间已经出现明显错位。vLLM、TGI 一类系统默认每个请求就是一个 prompt，应当在全局策略控制下沿着固定的 prefill-and-decode 流水线前进。这个假设对纯文本续写足够有效，但一旦应用要做分支推理、显式操纵 attention 状态，或者把生成过程和工具调用、外部计算交织起来，单体式循环就开始限制表达能力和效率。

作者把这种限制归纳为三个具体问题。第一，KV cache 管理由系统隐式决定，通常靠全局启发式完成，因此 Graph-of-Thought、Recursion-of-Thought、beam search、attention sink 等需要细粒度缓存控制的技术，往往只能通过修改 serving 系统内部代码来实现。第二，predict-then-sample 的生成循环结构是固定的，所以 speculative decoding、grammar-constrained decoding、带状态的搜索过程很难按请求定制。第三，tool use 和 agentic workflow 往往必须在每一步把控制权交还给客户端，这不仅增加网络往返延迟，还常常迫使服务器丢掉已有状态，并在下一次请求中重新 prefill。

## 核心洞察

Pie 最重要的判断是，serving 系统真正应该托管的单位不是 prompt，而是 program。只要底层引擎暴露出合适的低层原语，应用控制逻辑就可以移到核心推理后端之外，同时不必放弃共享后端的执行效率。在 Pie 里，应用能够显式操作 `KvPage`、`Embed` 之类资源，也能直接编排 embedding、forward、sampling、通信和网络 I/O。

这个想法成立的关键，在于 Pie 把“可编程性”和“执行效率”拆开了。inferlet 决定下一步做什么，而系统仍然能观察这些 API 调用、虚拟化底层资源，并把来自多个 inferlet 的兼容 GPU 工作重新批处理。于是，应用获得了足以表达自定义解码逻辑和缓存策略的控制力，而 serving 系统仍然保留了共享后端应有的吞吐能力。

## 设计

Pie 把 LLM 前向过程拆成三类 API：embed、forward 和 sample。围绕这些 API，它定义了两类核心资源：`Embed` 用来保存 token embedding，`KvPage` 用来保存连续的一段 KV cache，组织方式类似 PagedAttention。inferlet 需要显式申请和释放这些资源，也可以通过导出和导入 `KvPage` 在不同 inferlet 之间共享缓存状态。

编程模型本身是单线程、事件驱动的，并通过异步 API 调用实现并发。凡是需要 GPU 处理的调用都会带上 command queue，这样运行时就能看见依赖关系和优先级。论文强调，吞吐之所以没有随着“拆掉单体生成循环”而明显下降，关键就在这里：Pie 可以做横向 batching，把不同 queue 中同类型调用合并；也可以做纵向 batching，把同一 queue 中连续且不冲突的同类调用合并。

系统实现上，Pie 分成三层。application layer 用 wasmtime 在 WebAssembly 中运行 inferlet，利用 Wasm 的轻量隔离和低启动开销。control layer 直接处理非 GPU API，虚拟化 `Embed` 和 `KvPage`，管理 queue 优先级，并用 work-conserving 策略自适应地把 GPU 工作成批发给后端。inference layer 则通过专门的 handler 执行这些 batch，当前实现主要基于 PyTorch 和 FlashInfer，论文还描述了一个原生 C++/CUDA 版本。Pie 总共提供 42 个 API，其中 18 个直接面向 LLM 执行；它还用 trait 机制描述不同模型支持的 API 家族，再在 Rust support library 里把 autoregressive generation、sampling policy 和 fork-join 之类常见模式重新封装成更高层接口。

## 实验评估

实验的说服力在于，它同时检验了表达能力和代价。Pie 跑在 GCP `g2-standard-32` 加一张 NVIDIA L4 GPU 的环境上，使用 BF16 的 Llama 3 1B、3B、8B 模型。对比基线包括 vLLM、SGLang、LMQL，以及在相关场景下的 StreamingLLM。作者还特意让 Pie、vLLM 和 SGLang 共享 FlashInfer 后端，以尽量把差异限定在系统架构而不是 kernel 实现上。

表达能力方面，Table 2 本身就很有信息量：普通 text completion 只需要 38 行 inferlet 代码，而 speculative decoding、beam search、Tree-of-Thought、Graph-of-Thought，以及多个 agentic workflow 也只需要几十到几百行。性能方面，Pie 的收益主要出现在真正需要 programmability 的任务上。对 agentic workflow，Pie 在 ReACT 上最多把延迟降到基线的 85%，把吞吐提高到 130%；论文给出的绝对结果分别是 ReACT 的 4.27 s 和 29.94 agents/s、CodeACT 的 3.18 s 和 40.18 agents/s、Swarm 的 6.14 s 和 5.21 agents/s。对于一个可以利用应用语义做缓存保留、提前触发 API 调用、主动丢弃 KV 的代理 workflow，叠加优化后吞吐可达到 vLLM 基线的 3.5 倍。ToT、RoT、GoT、SKoT 一类 deliberate prompting 策略则获得了最高 28% 的延迟下降和 34% 的吞吐提升。即便是已有系统也支持的功能，Pie 也基本能做到接近或匹配现有最优；在 attention sink 上，它甚至比原始 StreamingLLM 实现达到 1.5x 更低延迟和超过 30x 的吞吐。

可编程性的代价确实存在，但并不大。论文报告 Pie 在标准 text completion 上有 3-12% 的延迟开销。以 8B 的 Llama 3 为例，单 token 输出时间从 vLLM 的 64.06 ms 上升到 Pie 的 65.59 ms，只增加 2.39%；在 1B 模型上则从 16.83 ms 增加到 18.75 ms，增幅 11.41%。作者进一步拆解后发现，主要代价并不是 Wasm 运行时本身，也不是层间边界，而是失去了单体式生成循环中 embedding、sampling 与 forward pass 的流水化机会。

## 创新性与影响

Pie 的创新点不在于又发明了一种更快的 attention kernel，或者更聪明的 cache allocator。它真正贡献的是一种架构：把 LLM serving 变成一个可编程底座，而且这个底座暴露的抽象足够低层，能表达真正新的行为。因此，这篇论文既是机制论文，也是重新定义问题的论文。它提出了 inferlet、command queue、handler-level batching 这些具体机制，但更重要的主张是：现代 LLM 应用不该被迫伪装成普通 prompt completion。

这会影响至少三类后续工作。第一类是需要按应用定制策略的 LLM serving 系统；第二类是今天仍要为 round-trip 和 re-prefill 付费的 agentic framework；第三类是想尝试新解码逻辑或新 attention 机制、却不想每做一次实验就分叉整个 serving engine 的研究者。如果 Pie 的接口或思想被采纳，未来很多工作就可以在 inferlet 这一层竞争，而不是反复对底层后端做侵入式改造。

## 局限性

论文自身的限制也很明确。Pie 面向的是 Transformer 风格 LLM，而当前实现对 Llama family 的支持最成熟。实验部署本质上也是单后端、单节点环境；对于多 GPU、多节点场景，论文只在 discussion 中提出未来方向，并没有实证展示 `KvPage` 的 locality、全局调度和 SLO 约束在分布式环境里会如何表现。

系统层面还有几项不能忽视的代价。允许用户 inferlet 做网络 I/O、读取 token distribution，会让安全问题比封闭式 serving 更复杂。资源竞争目前通过简单的 FCFS 式策略处理，必要时甚至会终止新近创建的 inferlet 来腾出容量，这显然不是公平性设计的终点。最后，Python inference layer 的反序列化成本是可测的，而细粒度 API 结构也确实放弃了一些单体实现里的优化，尤其是 embedding 与 sampling 的 pipeline。论文对这些开销做了诚实量化，但这也意味着 Pie 更适合作为“为复杂 workload 提供弹性控制的底座”来理解，而不是所有场景下都能替代最快封闭式 text generation 路径的通用方案。

## 相关工作

- _Kwon et al. (SOSP '23)_ - vLLM/PagedAttention 让 KV cache 管理更高效，但 serving loop 仍是单体式的，缓存策略也主要由系统统一决定，而不是由应用逐步控制。
- _Lin et al. (OSDI '24)_ - Parrot 用 semantic variable 改善 LLM 应用的缓存复用；Pie 则进一步把执行流程和缓存原语下放给应用，让 workflow 本身可编排。
- _Gim et al. (MLSys '24)_ - Prompt Cache 证明了模块化 attention reuse 的价值；Pie 把导出、导入和 mask cache 的能力做成应用可编程 API，从而把这类机制泛化了。
- _Beurer-Kellner et al. (PLDI '23)_ - LMQL 主要编程的是输出约束和生成语义，而 Pie 编程的是 serving 过程本身，包括资源管理、控制流和 I/O。

## 我的笔记

<!-- empty; left for the human reader -->
