---
title: "Characterizing Mobile SoC for Accelerating Heterogeneous LLM Inference"
oneline: "HeteroInfer 先刻画手机 SoC 上 GPU/NPU 的形状敏感与带宽边界，再按 prefill 和 decoding 分别做张量划分与快速同步，把两类加速器协同用于 LLM 推理。"
authors:
  - "Le Chen"
  - "Dahu Feng"
  - "Erhu Feng"
  - "Yingrui Wang"
  - "Rong Zhao"
  - "Yubin Xia"
  - "Pinjie Xu"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
  - "Tsinghua University"
  - "SenseTime Research"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764808"
tags:
  - llm-inference
  - gpu
  - hardware
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HeteroInfer 的核心主张是，手机上的 LLM 推理不该在 GPU 和 NPU 之间二选一，而应该先测清两者的真实性能边界，再把它们协同起来。它利用 NPU 的 stage/order/shape 敏感性、unified memory 和分阶段划分策略，让 prefill 拿到更多有效算力，让 decoding 拿到更多有效带宽。在 Snapdragon 8 Gen 3 与 8 Elite 上，论文报告相对已有移动端引擎可获得 1.34x-6.02x 的端到端加速，同时不依赖会伤害精度的 activation quantization 或 sparsity。

## 问题背景

移动端 LLM 推理的价值很直接：它既能缩短响应路径，也能把用户数据留在本地。问题在于，现代手机 SoC 虽然已经同时集成 GPU 与 NPU，但现有推理引擎大多仍然只押注单一后端，例如 MLC、MNN 这类 GPU-only 方案，或者 llm.npu、PowerInfer-2 这类 NPU-only 方案。这种做法忽略了推理两个阶段的瓶颈并不相同：prefill 更偏计算密集，decoding 更偏带宽密集。

看起来最自然的答案是“那就让 GPU 和 NPU 并行”。但论文实测发现，这件事在手机上会被三个细节卡住。第一，NPU 的 FLOAT 性能会随着张量尺寸、操作数顺序和长宽比例剧烈变化。第二，移动端 GPU-NPU 同步大约要 400 微秒，已经接近 decoding 阶段单个 kernel 的执行时间。第三，单个处理器在 decoding 阶段只能跑到大约 40-45 GB/s，明显低于平台约 61.9 GB/s 的可达带宽上限。所以真正的难点不是“把任务丢给 NPU”，而是如何协调两个并不对称的加速器，而不把收益耗在形状病理和同步开销上。

## 核心洞察

论文最重要的洞察是，不要把 GPU 和 NPU 视作可替换的同类加速器，而要把它们当作彼此补短板的异构单元。Prefill 阶段，NPU 仍然承担主力计算，而 GPU 负责吸收那些会让 NPU 表现失常的张量形状和更适合 GPU 的算子。到了 decoding 阶段，异构协同追求的也不是更多 FLOPs，而是让两个处理器同时拉取内存流量，把 SoC 推到更接近带宽上限的位置。这要求系统基于“测得的硬件行为”来做划分，并借助 unified memory 把同步压缩到微秒级。

## 设计

HeteroInfer 把 CPU 明确限制为控制面，只负责 kernel launch、同步和调度 bookkeeping。在 layer level 上，它把大多数 Matmul 交给 NPU，把 RMSNorm、SwiGLU 等更适合 GPU 的算子交给 GPU，并对部分 Matmul 用 `([K, N] x [N, M])^T` 的等价变换重排顺序，让 NPU 更符合 weight-stationary 的执行偏好。

真正关键的是 tensor-level GPU-NPU 并行。weight-centric partition 会沿行维切开权重矩阵，把子矩阵分别交给 GPU 和 NPU，再合并部分输出；这对 prefill 和 decoding 都有帮助。activation-centric partition 则专门处理动态 prompt 长度：它把标准长度块留给 static-graph NPU，只把不规则剩余部分交给 GPU，避免在线生成 NPU graph 或做大量 padding。hybrid partition 会把少量 padding 与 weight-centric 切分结合起来，确保两个处理器都不空转。

为了决定每个算子走哪条路径，系统先离线 profile 不同 shape 下的延迟、带宽和同步代价，再由 solver 在 GPU-only、NPU-only、weight-centric、activation-centric 与 hybrid 之间选择关键路径最短的方案。为保证这些计划真的划算，HeteroInfer 还维护了一个同时映射到 CPU、GPU、NPU 地址空间的小型共享 buffer pool，并用“预测睡眠 + 短轮询完成标志位”替代重型 fence，同步开销因此被压到足够低，细粒度 GPU-NPU 协作才在 decoding 阶段变得可行。

## 实验评估

实现上，HeteroInfer 运行在 Snapdragon 8 Gen 3 与 8 Elite 上，GPU kernel 用 OpenCL，NPU 后端用 Qualcomm QNN，并采用 W4A16 以在保持精度的同时控制模型大小。论文前面的 characterization 已经支撑了设计方向：GPU 吞吐会随张量尺寸近似线性上升直到饱和，NPU 对 stage/order/shape 非常敏感，而 GPU+NPU 并发 decoding 能把带宽从 GPU-only 的约 43 GB/s 拉高到 59.5 GB/s，已经接近平台 61.9 GB/s 的实测上限。

在目标场景下，端到端结果很有说服力。针对 multi-turn dialogue、GSM8K 和 LongBench 这三类工作负载，HeteroInfer 相对已有移动端引擎报告了 1.34x-6.02x 的延迟下降。Prefill 吞吐超过 1000 tokens/s，其中 InternLM-1.8B 达到 1092 tokens/s；decoding 最高达到 51.12 tokens/s。面对 sequence length 525 的动态 prompt，异构分区分别比在线生成 NPU graph 和纯 padding 快 2.24x 与 2.21x。Fast synchronization 也不是边角优化：它让 tensor-level 执行的平均 prefill 速度再提高 24.3%，并把 decoding 速度最高拉高到 4.01x。论文还测了与手机游戏并行运行时的干扰：游戏 FPS 保持稳定，prefill 只慢 2.2%，decoding 慢 17.7%，而端到端能耗比 GPU-only 低 55%。主要保留意见是，实验仍然以 batch-1、Qualcomm 手机为主。

## 创新性与影响

这篇论文的贡献不在于提出新的 quantization 或 kernel，而在于给移动端异构 SoC 总结出一套可执行的系统方法论：先诚实地刻画硬件，再把 prefill 与 decoding 当作两个不同的问题处理，最后用 profiler-solver 回路把标准 LLM 算子协同映射到 GPU 和 NPU。它既给移动端 runtime 作者提供了不牺牲精度的加速路线，也给 SoC 设计者提出了统一跨加速器调度、shared-memory 管理和轻量同步原语这些明确诉求。

## 局限性

HeteroInfer 很依赖当前移动端 NPU 的若干属性：static graph、systolic array，以及明显的 tensor-shape 性能病理。换一个 SoC 或模型家族，仍需要重新做离线 profiling 和 solving。工作负载模型也比较窄：全文都采用 batch size 1，论文也没有报告长时间交互下的持续热约束行为或更复杂的多会话争用。最后，一些 baseline 通过改变模型结构或使用更低精度 activation 路径来换取速度，因此这些比较有参考价值，但并非完全一致条件对照。更现实的一点是，decoding 已经非常接近 DRAM 上限，纯软件的额外收益可能不会太大。

## 相关工作

- _Wang et al. (MMAsia Workshops '24)_ — MNN-LLM 主要优化 GPU-only 的移动端推理，而 HeteroInfer 认为真正缺失的增益来自跨加速器协同。
- _Xu et al. (arXiv '24)_ — llm.npu 重点挖掘 NPU 能力，但 HeteroInfer 表明 NPU-only 执行仍会同时浪费计算弹性与 DRAM 带宽。
- _Xue et al. (arXiv '24)_ — PowerInfer-2 面向手机做了 NPU-heavy 执行和模型侧改造，而 HeteroInfer 保持标准模型结构，只对常规算子做 GPU-NPU 划分。
- _Song et al. (HPCA '20)_ — AccPar 研究异构加速器上的 tensor partition，而 HeteroInfer 把这类思路进一步落到 unified-memory 移动 SoC、static NPU graph 与微秒级同步之上。

## 我的笔记

<!-- 留空；由人工补充 -->
