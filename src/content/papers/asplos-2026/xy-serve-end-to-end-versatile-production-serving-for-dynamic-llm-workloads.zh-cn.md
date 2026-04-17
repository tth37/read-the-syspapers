---
title: "XY-Serve: End-to-End Versatile Production Serving for Dynamic LLM Workloads"
oneline: "XY-Serve 把混合的 prefill、decode、verify 工作流压缩成统一瓦片和元原语，让动态 LLM serving 在 tile-based 加速器上仍能保持高效。"
authors:
  - "Mingcong Song"
  - "Xinru Tang"
  - "Fengfan Hou"
  - "Jing Li"
  - "Wei Wei"
  - "Yipeng Ma"
  - "Runqiu Xiao"
  - "Hongjie Si"
  - "Dingcheng Jiang"
  - "Shouyi Yin"
  - "Yang Hu"
  - "Guoping Long"
affiliations:
  - "Huawei Technologies Co., Ltd., Beijing, China"
  - "Tsinghua University, BNRist, Beijing, China"
  - "Shanghai AI Laboratory, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762228"
tags:
  - llm-inference
  - hardware
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

XY-Serve 把生产级 LLM serving 看成一个 workload 规整化问题。它先把混合的 prefill、decode、verify 工作转换成统一的 token chunk、tile 级任务表，以及两套面向硬件的执行基元：处理各种注意力形态的 Meta-Attention，和处理动态形状线性层的 SmoothGEMM。这样即便 prefix reuse、chunked prefill 和 speculative decoding 让运行时高度不规则，底层内核仍然能保持高效。

## 问题背景

论文首先指出，现代 LLM serving 软件栈和 AI 加速器编程模型之间存在明显错位。真实部署越来越常同时打开 automatic prefix caching、chunked prefill、speculative decoding，以及 prefill/decode 分离或混合执行等机制。结果是运行时会变得非常不规则：prefix reuse 会让有效 prompt 长度任意变化，speculative decoding 会引入 verify 阶段和不规则 mask，chunked prefill 又会把长 prefill 与对延迟敏感的 decode 混在一起。

这类动态性在 tile-based 加速器上尤其麻烦。论文以 Ascend NPU 为主要目标，强调这类硬件偏爱固定 tile、规整访存以及可预测的负载分配。线性层中的动态 GEMM 形状会降低利用率，不规则注意力布局会打破已有 fast path，而如果为每一种 prefill/decode/verify 组合都单独写优化，复杂度会迅速失控。论文还指出，简单回退到按 batch 分开执行也不理想，因为 split、rearrange 和 merge 的额外内存开销在混合阶段执行中可能超过 `50%`。

## 核心洞察

这篇论文最值得记住的主张是：现代 LLM serving 看起来很杂乱的动态性，其实可以在执行前被压缩成少数几种统一元原语。与其把 prefix reuse、speculative decoding、chunked prefill 分别当成独立内核问题，不如先把运行时变化规整化，再交给少量高度优化的执行路径。

这个命题成立的关键在于，复杂度被上移到了运行时抽象层。调度在 token 粒度发生，每个 chunk 再被压缩成记录阶段边界、序列长度和 tile 分配的紧凑表结构。之后，Meta-Attention 看到的是 tile 化的 GEMM-Softmax-GEMM 工作流加上 K/V cache 与 mask 元数据，SmoothGEMM 看到的是受限的 tile 形状加虚拟 padding。论文的核心判断是：要恢复效率，靠的不是继续堆特例内核，而是先把动态 workload 重新抽象。

## 设计

控制路径从 token-wise scheduling 开始。新请求先经过 automatic prefix caching，因此真正进入活跃队列的只是未命中的 prompt token。随后，XY-Serve 按固定 budget 组 chunk，一个 chunk 里可以同时含有 prefill、verify 和 decode token。prefill 会被优先考虑以改善首 token 延迟，但系统也会预留 slot 给 decode 和 speculative token，避免长 prefill 压住正在输出的请求。之后，每个 chunk 会被压缩成 `Token-Table` 和 `Task-Table`。

对 Attention 而言，运行时记录阶段偏移、token 数、历史 `kvLen` 和 `tileSize`，再把每个阶段逻辑上分解成 tile，按估计负载 `tileSize x kvLen` 排序，并用对称 round-robin 方式分配到各个 AI core 上。对线性层而言，当前 chunk 的所有 token 会先拼接，再映射为 `QKV`、`OProj`、`GateUp`、`Down` 的结果矩阵分块；因为实际需要支持的形状家族有限，所以任务顺序可以离线调优、在线复用。

Meta-Attention 是数据路径核心。它保留 block-wise 的 K/V cache 管理来维持吞吐，但在块部分匹配失败时通过 copy-on-write 恢复 token-wise reuse，从而避免“尾块无法复用”的问题。对 speculative decoding，它只把真正特殊的 `specLen x specLen` 区域当作 mask 处理，而不是物化整张不规则 mask；之后再根据 workload 选择两级、三级或四级 pipeline。SmoothGEMM 在线性层上采取同样策略：只优化少量固定 tile 形状，再用片上虚拟 padding 与 selective HBM read/write 承接不规则输入。

## 实验评估

实验对一篇同时覆盖 serving 与 kernel 的论文来说算是比较扎实。内核层面，Meta-Attention 在多个动态场景下都超过了 Ascend NPU 的 `PFA` 和 `IFA` 基线：在 coding 与 conversation trace 的混合 prefill/decode/verify batch 中平均分别提升 `11%` 与 `26%`；在任意长度 prefix reuse 场景下平均提升 `22.4%`；在长序列 chunked prefill 中最高提升 `22.2%`；在 verify 场景下平均提升 `28.6%`；在不同 batch size 与上下文长度组合的 decode 场景下平均提升 `12.9%`。SmoothGEMM 相比 torch-npu linear 平均快 `14.6%`。

端到端结果更能说明问题。与 Ascend vLLM 在 vLLM nightly benchmarks 上相比，即便还没有打开 prefill-chunked batching 和 P/D/V fusion，XY-Serve 的 achieved QPS 也能最高提升 `79%`，同时平均 `TTFT` 降低 `64%`、平均 `TBT` 降低 `57%`；把这些动态调度特性打开后，QPS 提升进一步达到 `89%`，平均 `TBT` 降幅达到 `69%`。在一个平均输入长度为 `2169`、模型规模为 66B 的内部 workload 上，整套优化相对 vLLM-APC 基线的提升达到 `95%`。我认为这些实验基本支撑了论文的中心论点，不过覆盖面仍偏 Ascend 生态，GPU 对比也更窄，只展示了与 `A800` 大致相当的端到端 MFU/MBU，以及 decode 阶段最高 `17%` 的 MBU 优势。

## 创新性与影响

相对于 _Kwon et al. (SOSP '23)_，XY-Serve 的重点并不是提出一个更好的 KV-cache allocator，而是把 cache 结构放进更大的执行抽象里，同时覆盖 prefix reuse、speculative decoding 与 chunked prefill。相对于 _Agrawal et al. (OSDI '24)_，它的新意也不只是 chunked-prefill 调度本身，而是提出 mixed prefill/decode/verify execution 可以被压缩成统一的 meta-primitives，并且依然对硬件友好。因此，这篇论文更像一个面向动态 LLM inference 的 serving substrate，而不是单点内核技巧。

## 局限性

XY-Serve 用不少机制换来了规整性，包括 token-wise scheduling、task decomposition、task reordering、copy-on-write 的 K/V 管理、多种 attention pipeline，以及离线形状调优。论文很好地证明了这些复杂度带来的性能收益，但对维护这样一套多层系统的工程成本讨论不多。

它的适用范围也有边界。最强结果主要集中在 Ascend NPU 上的单模型 serving，GPU 部分更多是在证明方法能迁移，而不是已经形成成熟的 GPU 生产栈。内部 workload 的描述也比较高层，论文并没有真正展开 multi-model routing、autoscaling 或 fleet-level admission control 等更大规模部署问题。

## 相关工作

- _Kwon et al. (SOSP '23)_ — PagedAttention 通过改进 KV-cache 分配让连续 LLM serving 变得可行，而 XY-Serve 在类似缓存布局之上继续处理 mixed-stage execution 和 kernel regularization。
- _Agrawal et al. (OSDI '24)_ — Sarathi-Serve 证明了 chunked prefills 对吞吐/延迟权衡的价值；XY-Serve 则把 serving substrate 扩展到 prefix reuse、verify 阶段以及面向硬件的任务表。
- _Yu et al. (OSDI '22)_ — Orca 推广了 transformer serving 的 iteration-level scheduling，而 XY-Serve 进一步把分解粒度下沉到 token-wise chunk 与面向内核的 task decomposition。
- _Zhong et al. (OSDI '24)_ — DistServe 将 prefill 与 decode 拆到不同节点上，而 XY-Serve 明确支持 combined 与 disaggregated 两种 P/D/V 角色，并专注于让它们都能在加速器上高效运行。

## 我的笔记

<!-- empty; left for the human reader -->
