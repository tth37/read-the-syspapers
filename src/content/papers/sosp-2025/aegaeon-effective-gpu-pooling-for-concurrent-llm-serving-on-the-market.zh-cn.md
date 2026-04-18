---
title: "Aegaeon: Effective GPU Pooling for Concurrent LLM Serving on the Market"
oneline: "Aegaeon 把多模型 LLM serving 的 autoscaling 下沉到 token 级，并用分离式调度与亚秒级模型和 KV cache 切换提升单 GPU 的池化效率。"
authors:
  - "Yuxing Xiang"
  - "Xue Li"
  - "Kun Qian"
  - "Yufan Yang"
  - "Diwen Zhu"
  - "Wenyuan Yu"
  - "Ennan Zhai"
  - "Xuanzhe Liu"
  - "Xin Jin"
  - "Jingren Zhou"
affiliations:
  - "School of Computer Science, Peking University"
  - "Alibaba Group"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764815"
tags:
  - llm-inference
  - gpu
  - scheduling
  - datacenter
  - memory
category: llm-serving
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Aegaeon 通过把 autoscaling 从请求边界下沉到 token 边界，让模型市场里的 GPU pooling 真正变得有效。它拆分 prefill 与 decode，分别采用不同调度策略，并用组件复用、显式内存管理和细粒度 KV cache 同步把切换成本压低。结果是在实验里达到 2-2.5x 更高的可持续到达率或 1.5-9x 更高的 goodput，并在 beta 部署中把 GPU 需求降低了 82%。

## 问题背景

这篇论文研究的是一个普通 LLM serving 工作很少完整覆盖的场景：云端模型市场同时托管大量模型，流量呈现明显长尾，而且热门模型也会突发。作者给出的生产统计很直接：在 Alibaba Cloud Model Studio 中，94.1% 的模型只贡献 1.35% 的请求，但如果仍给它们预留专属 GPU，这些冷门模型却会占掉 17.7% 的 GPU。问题因此不只是“单模型推理够不够快”，而是稀疏调用与粗粒度资源保留之间存在结构性错配。

已有两类 GPU pooling 方案都很快碰到边界。第一类 multiplexing 受显存限制，一张 80 GB GPU 通常只能容纳两三个 14B 级模型。第二类 request-level auto-scaling 虽然绕过了显存上限，但仍受 active model count 约束，因为 LLM 请求持续时间长。论文形式化给出 `E[m] = M * (1 - e^-lambda*T)`，并举例说明：100 个模型、总到达率只有 3.7 req/s 时，平均仍有 46.55 个模型处于 active 状态。只要切换还要等请求结束后才做，新请求就会被长请求堵住，形成 head-of-line blocking。再加上 TTFT/TBT 的双重 SLO，错误的切换决策会同时伤害首 token 和逐 token 延迟。

## 核心洞察

论文的核心主张是：autoscaling 必须成为 token 级调度原语。只有这样，系统才能在 token 生成步骤之间回收 GPU，而不是等整条请求结束后才腾出资源，从而打破现有 request-level serverless 方案的 active-model-count 上限。

但这只有在另外两个条件同时满足时才成立。第一，prefill 和 decode 必须分开调度，因为它们的时延结构和 slack 完全不同。第二，完整的 scale-down/scale-up 路径必须便宜到可以放在关键路径上，否则 token 级控制只会引入额外开销。Aegaeon 因而把 phase-specific scheduling 和 full-stack 的切换优化绑在一起设计。

## 设计

控制路径从 proxy 和 Redis 同步开始，把请求送入两类 GPU 分区：prefill instances 与 decoding instances。论文认为这种 disaggregation 能避免统一启发式在 prompt 突发和 decode 连续执行之间左右失衡。

在 prefill 阶段，Aegaeon 使用 grouped FCFS。相同模型的请求被合并进有上限的 group，用一次 scale-up 服务多个 prompt，同时把 group 放到最轻的队列上，以尽量保持接近到达顺序。实现上 prefill batch size 固定为 1，因为 prefill 时延基本随 prompt 长度线性增长。

在 decode 阶段，Aegaeon 使用 weighted round-robin。每个 decoding instance 维护一个同模型 batch 的 rotating work list，并按 token slack 和整轮切换开销分配时间配额。这样做的效果是把等待时间摊进多个 decode step，而不是集中成一次明显卡顿，同时仍然给其他模型预留被切进来的机会。

真正让这套控制策略成立的是数据路径优化。论文指出，原始 vLLM 上一次 13B 模型的 preemptive switch 最多可达 26.9 秒，所以 Aegaeon 复用 executor 组件、用自管理 VRAM buffer 避免碎片和垃圾回收、在主机侧保留带 page-locked staging buffer 的 model cache 并支持预取、用 slab-allocated unified cache 存放异构 KV blocks，再用 CUDA events 协调 KV swap-in/swap-out。论文报告这些改动去掉了 80% 以上的 scale-up 延迟，并把端到端 preemptive autoscaling 延迟最多降低 97%。

## 实验评估

主评估使用两台节点、共 16 张 H800 80 GB GPU，每台配 2 TB DDR5 和 192 个 Xeon Platinum 8469C CPU，在 ShareGPT 及其变体上服务 6B-14B 模型，默认 SLO 是 TTFT 10 s、TBT 100 ms。基线包括 ServerlessLLM、MuxServe，以及带 oracle 最短作业优先调度的 ServerlessLLM+。

结果支持论文的核心论点。在每个模型 0.1 req/s 时，Aegaeon 的 goodput 约为 ServerlessLLM 的 2x，并且只用 10 个 decoding instances 就能支撑最多 70 个模型，相当于每张 GPU 服务 7 个模型。在每个模型 0.5 req/s 时，优势扩大到 2.5x，因为 request-level 的 head-of-line blocking 更严重。面对更长输入或更长输出的数据集，Aegaeon 仍然领先，最高达到 2.5x 的 goodput 提升。MuxServe 在这个区间内始终追不上，因为它在真实显存压力下不会把超过两个模型放进同一张 GPU。

分解实验也和机制解释一致。由于预取存在，大约一半 autoscaling 几乎瞬时完成，其余情况通常也在 1 秒以内；KV cache transfer 的额外开销低于 1 秒/请求，碎片率保持在 20% 以下。系统在 4xA10 节点和 72B、TP=4 的大模型上仍然有效，不过在最严格 SLO 下，static multiplexing 会因为完全不付切换代价而追平。生产部署中，Aegaeon 把 GPU 使用量从 1,192 张 H20 降到 213 张，同时把平均利用率从 13.3%-33.9% 提高到 48.1%，论文也没有报告观测到的 SLO 违约。

## 创新性与影响

Aegaeon 更像是一个面向多模型 LLM serving 的新机制，而不只是更快的冷启动系统。相对于 _ServerlessLLM_，它把控制点从请求结束前移到 token 边界；相对于 _MuxServe_，它绕开了静态共置的显存天花板；相对于 _DistServe_，它把 prefill/decode 拆分从单模型吞吐优化改造成多模型公平性和切换摊销的基础结构。这让它对云推理平台以及后续的 LLM 调度、autoscaling 和内存管理工作都很有参考价值。

## 局限性

Aegaeon 需要足够的时延 slack。它的收益在 TTFT/TBT 预算较宽松时最明显，因为系统可以把一部分 slack 花在切换上；在论文最严格的 SLO 设置里，MuxServe 能追平它。主实验同时依赖高端 GPU、大容量主机内存和较快的 host-device 数据路径，因此同样的成本结构能否完整迁移到更弱部署上，论文并没有完全证明。

此外，控制策略上仍有空白。主评估里的 prefill/decode 分区是静态的，配额规则也是启发式，公平性只通过总体 SLO attainment 间接体现。论文也没有量化预取失误、故障恢复或多租户隔离，这些在更通用的公有云部署里都会变得重要。

## 相关工作

- _Fu et al. (OSDI '24)_ - ServerlessLLM 加速的是 request-level 的 serverless LLM serving，而 Aegaeon 把控制点前移到 token 边界，并优化了携带 KV state 的重复 preemptive switch。
- _Duan et al. (ICML '24)_ - MuxServe 通过把多个模型常驻在显存里做 multiplexing，Aegaeon 则通过积极切换模型来突破常驻共置模型数的显存上限。
- _Zhong et al. (OSDI '24)_ - DistServe 证明了拆分 prefill 和 decode 对 LLM serving 有价值，而 Aegaeon 把这种拆分进一步变成多模型 token 调度与 SLO-aware pooling 的基础。
- _Zhang et al. (OSDI '25)_ - BlitzScale 关注利用 host caching 加速 live autoscaling，而 Aegaeon 处理的是更完整的 preemptive 路径，包括 engine reuse、碎片控制与 KV cache 同步。

## 我的笔记

<!-- empty; left for the human reader -->
