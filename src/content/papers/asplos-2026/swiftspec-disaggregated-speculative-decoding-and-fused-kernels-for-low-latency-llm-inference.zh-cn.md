---
title: "SwiftSpec: Disaggregated Speculative Decoding and Fused Kernels for Low-Latency LLM Inference"
oneline: "SwiftSpec 把 draft 与 target 拆到不同 GPU 组上并保留 tree speculation 的 KV 复用，再用 fused kernels 压低单请求 LLM 解码延迟。"
authors:
  - "Ziyi Zhang"
  - "Ziheng Jiang"
  - "Chengquan Jiang"
  - "Menghan Yu"
  - "Size Zheng"
  - "Haibin Lin"
  - "Xin Liu"
  - "Henry Hoffmann"
affiliations:
  - "Bytedance Seed, Bellevue, WA, United States"
  - "University of Chicago, Chicago, IL, United States"
  - "Bytedance Seed, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790246"
code_url: "https://github.com/ByteDance-Seed/SwiftSpec"
tags:
  - llm-inference
  - gpu
  - disaggregation
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

SwiftSpec 研究的是一种很具体、但越来越真实的 serving 场景：一个 LLM 请求独占整台多 GPU 节点，而且每个 token 的延迟都很重要。它的答案不是只改 speculative decoding 算法，而是同时改运行时与 kernel：把 draft model 和 target model 分到不同 GPU 组上并行执行，用 evolving tree cache 保住 tree speculation 的 KV 复用，再用面向小 batch 的 fused kernels 去掉通信与同步开销。论文在 8xH800 上报告 Llama-3-70B 达到 347 tokens/s，平均比最强开源基线快 1.75x。

## 问题背景

这篇论文抓住的是交互式 LLM 系统里一个常被忽略的极端工况。像 coding assistant、机器人推理和低延迟 AI 搜索这类应用，经常愿意为单个请求分配整台 8-GPU 节点，因为集中式 batching 会把尾延迟拉高。在这种场景下，大家自然会想到 speculative decoding：让小 draft model 先猜多个 token，再让大 target model 一次验证多个候选，从而减少 target 调用次数。

但现有方案没有把这个思路真正推到“最低延迟”。第一，draft 往往仍在关键路径上。很多系统还是先 draft、再 verify，等于把小模型额外插入每一轮解码。第二，tensor parallelism 对 draft 和 target 的收益不对称。大 target model 继续加 GPU 还有明显收益，小 draft model 很快就到拐点，后面增加 GPU 主要换来的是 all-reduce 和同步开销。论文的 Table 1 很直观地支持了这一点：Llama3-70B 随 GPU 数增长还有较大降时延空间，而 1B、3B、8B 这些 draft 级模型几乎很快就平台化了。

更麻烦的是，tree-based speculative decoding 一旦想并行化，就会碰到 KV-cache 一致性问题。target 验证出来的新路径可能会推翻 draft 之前扩出来的大量分支；如果 cache 不能随 reroot 正确重组，就只能丢掉已算好的 KV 再重算。与此同时，单请求 serving 的内部 batch 其实很小，作者指出 batch size 超过 16 收益已很有限。在这么小的 batch 下，GEMM、attention 和 all-reduce 都变成 latency-bound，kernel launch、barrier 和等待首个输入的时间占比很高。也就是说，问题既不是单纯的算法问题，也不是单纯的 kernel 问题，而是两层错配叠在一起。

## 核心洞察

论文最值得记住的判断是：要把 speculative decoding 真正做成低延迟系统，必须同时把 draft 从关键路径上移走，并且让这种异步执行不会破坏 tree speculation 的有效性。换句话说，核心不是“把 draft 和 target 放到不同 GPU 上”这么简单，而是“让它们分开之后，仍能共享一个可持续演化的 speculative 状态”。

SwiftSpec 因此提出三个互相咬合的部件。第一是 disaggregated tree generation：draft GPU 组在 target 验证第 `n-1` 轮时，提前生成第 `n` 轮的候选树。第二是 evolving tree cache：每次 target 返回已验证 token 后，系统把这些 token 对应的 KV 状态并入 prefix cache，把仍然有效的子树压紧到后面的 tree cache，只有真正无效的分支才被丢弃。第三是 latency-optimized kernels：既然单请求场景的小 batch 已经让通信和同步成为主瓶颈，就不要把 all-reduce、attention 与点操作拆成多个独立 kernel，而是直接把 NCCL LL/LL128 风格的低延迟通信嵌进计算路径里。

## 设计

运行时的基本结构是把一台 8-GPU 节点拆成两个 tensor-parallel 组，一个跑 draft model，一个跑 target model。每轮中，draft worker 先扩展当前树里概率最高的叶子若干次，再接收上一轮 target 返回的 verified tokens，对草稿树执行 reroot，并从更新后的树中挑一个大小为 `bs` 的子树发给 target 验证。与此同时，target worker 只负责批量验证收到的候选 token，并把最终接受的路径发回 draft。这样，传统 speculative decoding 里串行的 draft/verify 被改成了异步流水。

draft tree 的扩展规则是最大似然驱动的。每个节点存储 log-softmax 值，根到叶子的路径权重是这些值的和，系统用优先队列维护最有希望的叶子，因此可以用 `O(k log s)` 的代价挑出最可能的扩展对象。实现上，论文把 target batch size `bs` 和 draft width `w` 都设为 8，并通过 profiling 选择 tree depth `d`，使“一轮 draft 扩展时间”尽量接近“一轮 target 验证时间”。只有这样，两组 GPU 才能真正并行，而不是一边长期等待另一边。

真正让这个调度成立的是 evolving tree cache。作者维持一个很清楚的不变式：prefix cache 连续存放已经被 target 验证通过的 token 的 KV 状态；tree cache 紧跟其后，连续存放仍然保留的 speculative 子树节点。每当 target 返回新的 verified tokens，draft worker 就沿着这条路径向下走，把新确认的 token 提升进 prefix，把最后一个确认节点下面仍然有效的子树重新紧凑地搬到 tree cache 前部。若最后确认的 token 根本不在当前草稿树里，系统才从这个 token 重新起一棵新树。关键收益是：即便 target 否掉了一部分猜测，只要某个子树仍然可能继续使用，其 KV 状态就全部保留下来，不需要重算。

论文还处理了一个很容易被忽略的工程细节：draft 侧 attention 需要 non-square mask。因为 draft 在扩展树叶时，当前要计算 logits 的那些叶子只应该看到自己的祖先节点和已验证前缀，而不是一个普通的方形 causal mask。作者因此为 draft model 实现了支持如 `(4, 10)` 这类形状的 attention kernel。

kernel 层面的设计同样是围绕小 batch 低延迟展开。SwiftSpec 直接使用 NCCL 的 LL 和 LL128 原语：GEMM 与后续 all-reduce 融合，attention 在单个 kernel 内完成跨 thread block 的同步与聚合，SwiGLU 则把两次矩阵乘、sigmoid 和点积合成一个 operator。论文没有把这部分写成“可选优化”，而是给出完整实现：大约 3 KLOC 的 CUDA/C++ kernels，加上大约 4 KLOC 的 C++/Python runtime。

## 实验评估

实验设置与论文目标高度一致。所有对比都在一台通过 NVLink 互联的 8xH800 80GB SXM 节点上完成，覆盖五组 target/draft model family 与六个数据集，每个数据集取 80 个 prompt，共 480 个查询。为了把绝对解码速度推高，作者对 transformer 层统一使用 4-bit AWQ 量化，embedding 和 LM head 保持 BF16，并确保 SwiftSpec 与基线在单模型计算上等价。

核心结果是端到端单请求 decoding speed。论文报告 SwiftSpec 平均比 SpecExec 快 1.75x，在可比设置下平均比 SGLang 快 2.23x；对于 Llama-3-70B，Figure 7 还显示 SwiftSpec 在全部 480 个请求的速度分布上都更快，不只是均值更高。作者特别强调 p95：在这个模型上，SwiftSpec 相对最强基线至少有 1.7x 的 95th-percentile speedup，这和它要解决的 tail-sensitive interactive serving 目标是对齐的。

ablation 很有说服力，因为它把“并行 tree generation”和“kernel fusion”拆开看。以 Qwen2-72B 为例，改成并行 draft/target 之后，平均 acceptance length 的确下降了，但幅度不大，作者总结为平均只少 9%。与此同时，draft inference time 从 3.72 ms 降到 3.25 ms，而 target time 几乎不变，只从 10.34 ms 到 10.48 ms。结果是整体速度从 200 提升到 274 tokens/s，也就是 1.37x。这个结果说明，在单请求场景里，把 draft 移出关键路径，比一味追求最高 acceptance length 更重要。

kernel 微基准则支撑了第三个设计点。fused GEMM-all-reduce 在 attention block 上把延迟降低 23%-43%，在 MLP block 上对较小模型降低 16%-25%。attention kernel 相比 FlashAttention 在代表性 context length 下节省 30%-56%，而 fused SwiGLU 在 1B、3B 等小模型上把延迟再压低 39%-50%。不过作者也诚实展示了边界：在最大 70B 模型上，SwiGLU 这部分并不总能赢过更成熟的 baseline kernel。

## 创新性与影响

相较于 _Miao et al. (ASPLOS '24)_ 的 SpecInfer，SwiftSpec 的新意不在“tree speculation 更好”这个算法结论，而在“怎样把 tree speculation 变成真正面向最低单请求时延的多 GPU 系统”。它把 draft/target 异步化、cache 一致性和小 batch kernel 这三件事放进同一个设计里，而不是只做其中一项。

相较于 _Butler et al. (arXiv '24)_ 的 PipeInfer，SwiftSpec 不是简单的设备间流水线版本，而是进一步支持 tree-based speculation，并且显式处理 reroot 后的 KV 重组。相较于 _Ye et al. (MLSys '25)_ 的 FlashInfer，SwiftSpec 也不是通用 attention engine，而是专门针对“一个请求吃满一台节点”的 serving 场景，把跨 GPU 通信与计算融合到同一个低延迟路径里。对后续工作来说，这篇论文最可能留下的影响是一个设计原则：单请求低延迟 LLM serving 不能只靠更好的 draft model，还需要运行时和 kernel 一起围绕小 batch 重构。

## 局限性

论文证据最扎实的范围，就是它自己定义的目标范围。所有主要结果都来自单节点、8xH800、NVLink 互联、greedy decoding 的设置，因此对更弱互联、跨节点部署、混合租户或更复杂 serving 目标的结论还主要停留在推断层面。作者讨论了低端 GPU 和 PCIe 场景的潜在适用性，但没有给出对应实测。

另一个边界是 kernel 的适用区间。作者明确写到，这些 fused kernels 是为小模型和小 batch 的低延迟 serving 优化的；当 batch 变大、通信与 launch 开销被摊薄后，像 FlashInfer 这样的 throughput-oriented kernels 可能更好。SwiGLU 在 70B 上不占优，已经提前暴露了这一点。

最后，SwiftSpec 仍然依赖 profiling。GPU split、tree depth `d` 以及一些内部参数都需要按模型对做预先测量后再选；而与 EAGLE3 的比较也只能局限在公开可得的 Llama-3.3-70B-Instruct 上。这不影响论文的主结论，但说明它离“无调参、即插即用”的通用 serving substrate 还有距离。

## 相关工作

- _Miao et al. (ASPLOS '24)_ — SpecInfer 证明了 tree-based speculative verification 的价值，而 SwiftSpec 进一步把它改造成可在不同 GPU 组上异步执行的系统。
- _Butler et al. (arXiv '24)_ — PipeInfer 也让 draft 与 verification 重叠执行，但它更偏 sequence-style speculation；SwiftSpec 处理的是更复杂的 tree speculation 与 reroot 后 KV 复用。
- _Zhong et al. (OSDI '24)_ — DistServe 做的是 prefill/decode disaggregation，SwiftSpec 则把 disaggregation 放在 speculative decode 内部的 draft/target 边界上。
- _Ye et al. (MLSys '25)_ — FlashInfer 提供高效 attention engine，而 SwiftSpec 专注于超低 batch 的 serving，并把通信直接融合进 attention 与 GEMM。

## 我的笔记

<!-- 留空；由人工补充 -->
