---
title: "Wave: Leveraging Architecture Observation for Privacy-Preserving Model Oversight"
oneline: "Wave 从 GPU PMC 轨迹恢复 LLM 结构，再用 SMT 检查执行是否与宣称模型一致，在不暴露权重和提示词的前提下发现缩水部署。"
authors:
  - "Haoxuan Xu"
  - "Chen Gong"
  - "Beijie Liu"
  - "Haizhong Zheng"
  - "Beidi Chen"
  - "Mengyuan Li"
affiliations:
  - "University of Southern California, Los Angeles, CA, USA"
  - "Carnegie Mellon University, Pittsburgh, PA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790247"
code_url: "https://github.com/sept-usc/Wave"
tags:
  - llm-inference
  - security
  - observability
  - gpu
  - hardware
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Wave 把 GPU 当作 LLM 推理的“旁证设备”。它采集少量 GPU performance counters，先恢复正在执行的模型结构轮廓，再用 SMT 求解检查是否存在某个与这些计数一致、但又违反服务商承诺模型规模或配置的 canonical Transformer 执行。

## 问题背景

这篇论文面向的是外包推理场景：用户为某个宣称的模型付费，但看不到权重、内核实现，也无法审计部署代码。模型提供方若面临成本压力，就可能悄悄换成更小的模型、改变 batch 结构，甚至在不真正跑 GPU 推理的情况下伪造一部分 token，同时仍返回表面上“还过得去”的答案。只看输出的办法在这里都不够强：watermark 和时序侧信道都很间接，软件审计需要访问内部状态，而 zero-knowledge proof 目前又贵到不适合做日常监控。

作者想要的是一种既保护隐私、又难以伪造的运行时证据。GPU PMC 很有吸引力，因为它暴露的是聚合后的计算和访存行为，而不是模型权重或用户提示词。难点在于，PMC 给出来的是带噪声的 kernel 级轨迹，不是一份干净的架构日志；不可信的部署者还可以重命名 kernel、拆分或融合 GEMM、插入 padding，甚至重排执行顺序，来误导任何依赖 kernel 名称或单一阈值的监视器。

## 核心洞察

Wave 的核心论点是：decoder-only Transformer 推理会服从一组由硬件约束出的不变量，而这些不变量不会因为实现细节的小幅变化而消失。只要模型架构固定了层数、hidden size、FFN 宽度，以及 QKV/FFN 是否融合，执行过程就必然在 FLOPs、off-L1 内存流量、shared-memory 强度，以及 token 与 layer 的周期性重复上留下对应关系。

因此，验证者并不需要恢复权重，也不需要精确还原每个 kernel。它只需要先从 PMC 轨迹中恢复一个粗粒度的结构草图，再问一个更强的问题：在允许的攻击变换下，是否存在某个与观测计数一致的 canonical Transformer 解释，同时又违反了服务商的承诺？把“轨迹解释”和“形式化验证”拆成两个阶段，是 Wave 能把带噪侧信道变成监督机制的关键。

## 设计

Wave 首先假设 PMC 轨迹本身是可信的：硬件在执行期间采集计数，并通过未来的 TEE 或 GPU 根信任链路签名。部署者可以改变实际运行的模型，也可以操纵 kernel 结构，但不能伪造 GPU 报出的物理计数。原型只处理启用 KV cache 的单 GPU decode 阶段，明确不覆盖分布式推理、MoE，以及 vLLM、SGLang 这类高度优化的 serving engine。

第一阶段是 execution trace inference。Wave 把每个观测到的 kernel `k` 压缩成一个三维特征：FLOPs `F(k)`、shared-memory ratio `r_sh(k)` 和 off-L1 流量 `B_tot(k)`。这些特征来自九个 Nsight 指标，覆盖标量 FMA/ADD/MUL 桶以及 global/shared-memory 访问。随后，Wave 对特征流做自相关，识别两层嵌套周期：大周期对应“生成一个 token”的 kernel 序列，小周期对应“一个 Transformer layer”的结构。统计大周期数量可以恢复 token 数，从而发现简单的 token inflation；统计每个大周期里的小周期数量则可以恢复层数。

完成分段后，Wave 会依据 canonical layer 模板 `S* = (QKV, Attn, O, Add, FFN, Add)` 做层内角色分配。系统先根据 FLOPs 和 shared-memory 行为，把 kernel 分类为 matmul-like、attn-like 或 add-like；再结合 off-L1 流量和 FLOP 比例，区分 Q/K/V/O 与 FFN 的具体角色，同时容纳论文中看到的主要实现变体：QKV 可以 fused 或 split，FFN 可以是 2-gate 或 3-gate。基于这些角色，Wave 通过主导标量 FMA 桶恢复 dtype，用 projection store 估计 `b*d`，再从 projection load 解出 hidden size `d`，进而得到 batch size `b`、`d_ffn`，以及近似参数规模 `M = L(4d^2 + lambda*d*d_ffn)`。

第二阶段把这些观测变成正式 verifier。论文将 canonical 执行建模为一串矩阵乘法和加法，并为 FLOPs、global load、global write 建立解析的上下界。接着它定义一族主要由 split attack 构成的攻击模型，即把一个 canonical matmul 切成多个小 kernel，并用 `UndoAttack` 把候选观测序列映射回 canonical 序列。验证问题变成：是否存在某个观测序列 `S'` 及允许的攻击，使得 `PMC(S')` 在容忍范围内匹配真实轨迹，而恢复出的 `S*` 却违反了服务商承诺，无论这个承诺是下界检查 `M(S*) >= M_promise`，还是上界检查 `M(S*) <= M_promise`。如果 Z3 找到了这样的 witness，Wave 就返回 `Fail`；否则就在既定模型下通过验证。

## 实验评估

实验覆盖 RTX 4090、RTX 5080 和 H100 三种 GPU，软件栈是 CUDA 12.8、PyTorch 2.7.0 和 Nsight Compute 2025.x。作者在这些平台上实例化了 GPT-2、LLaMA 和 Qwen 的架构模板，hidden size 覆盖 `512-8192`，模型规模约从 `25M` 到 `10B`，并测试了最高到 `16` 的 batch size，默认大多使用 FP32。它本质上是一项“架构可观测性”研究，而不是在真实生产 checkpoint 或现代 serving stack 上做端到端 benchmark。

第一阶段作为 fingerprinting 工具表现不错。Wave 能依靠 fused-vs-split QKV 与 2G-vs-3G FFN 这两个模式，在三类 GPU 上区分 GPT-2 和 LLaMA/Qwen。它能稳定恢复 precision、batch size、层数和 token 数；在结构参数上，hidden size 的平均误差约为 `7%`，FFN 宽度约为 `3%`，整体模型规模约为 `11%`，而摘要里将关键参数恢复误差概括为平均 `6.8%`。Figure 4 还显示，实测的 QKV load-miss bytes 与理论曲线 `(d^2 + b*s*d) * D` 基本重合，这正是其参数恢复公式成立的经验基础。

第二阶段的结果更有研究原型色彩。对于 `44` 个详细模型配置的下界验证，求解器在三种 GPU 上都没有出现 false positive。主要失败来自 false negative：某些大 batch 情况下，实测 global load 偏离论文的容忍模型太多，作者推测这与权重被重复加载有关；他们还提到 `b = 1` 时偶尔会出现 global write 偏低的问题。至于上界验证，作者在 RTX 4090 上构造了一个单层、可随机切分线性层的 GPT-2-like 模型，在 `14` 个 split 配置里没有观察到 false positive 或 false negative，且每次检查都能在 `1` 分钟内完成。最大的现实问题是 profiling 成本：完整 Wave 指标采集即便在 H100 上也至少带来 `1196%` slowdown，而只监控一个硬件指标，开销仍有 `52%-1333%`。

## 创新性与影响

相对 _Sun et al. (CCS '24)_ 的 zkLLM，Wave 放弃了密码学意义上的精确正确性，换来一种更轻量的、基于硬件证据的“宣称模型是否真的被执行”检查。相对 _Tople et al. (ACNS '18)_ 的 VeriCount，它不是通用的可信资源计量，而是扎根于 Transformer 线性代数结构的 LLM 专用监督机制。相对 _Hu et al. (ASPLOS '20)_ 的 DeepSniffer，后者把 GPU 侧信号当作模型抽取攻击通道，而 Wave 则把同类信号反过来用于防御性验证。

所以这篇论文既像一个新机制，也像一个新 framing。它说明 PMC 不只是性能诊断工具或侧信道来源，还可能成为模型问责中的签名证据。做 GPU TEE、云端 attestation、以及 ML 审计流水线的人，都会把它当成一个具体而清晰的 design point，即便今天的原型还远谈不上可部署。

## 局限性

论文对限制讲得很坦白。Wave 不验证精确权重，不能区分 base model 与 fine-tuned variant，也不处理量化、operator fusion、continuous batching、分布式多 GPU 执行等生产环境常见优化。它主要聚焦 decode 阶段；作者虽然认为 prefill 可以扩展进去，但并没有真正验证这条路径。

更根本的问题是，Wave 依赖今天租户实际上拿不到的基础设施：低开销且可信的 PMC 访问接口、经过认证的轨迹传输路径，以及可能围绕 verifier 构建的 TEE 支持。当前原型依赖 Nsight Compute，开销高到不可能直接在线部署。它的形式化保证也只在攻击模型和噪声界成立时有效：如果真实部署用了 split attack 之外的变换，或者硬件噪声超出了设定范围，求解器就可能漏报违规执行。

## 相关工作

- _Sun et al. (CCS '24)_ — zkLLM 提供更强的端到端正确性保证，但需要承担 Wave 明确试图避免的密码学开销。
- _Tople et al. (ACNS '18)_ — VeriCount 依靠硬件/软件隔离做资源计量，而 Wave 试图直接从 GPU 执行轨迹中恢复 LLM 结构。
- _Hu et al. (ASPLOS '20)_ — DeepSniffer 说明硬件轨迹会泄露 DNN 架构线索；Wave 则把同类信号改造成 verifier，而不是 extraction attack。
- _Kumar et al. (AIMLSystems '21)_ — 这项基于 PMC 的 DNN layer-type side channel 支撑了 Wave 的前提：即便看不到权重，微架构计数器依然能暴露模型结构。

## 我的笔记

<!-- empty; left for the human reader -->
