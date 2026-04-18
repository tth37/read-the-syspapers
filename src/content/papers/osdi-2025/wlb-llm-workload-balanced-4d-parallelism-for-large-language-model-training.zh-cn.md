---
title: "WLB-LLM: Workload-Balanced 4D Parallelism for Large Language Model Training"
oneline: "WLB-LLM 用可变长 packing、outlier delay 与自适应 context sharding 取代“只按 token 均分”的 4D 训练，带来 1.23x 平均提速。"
authors:
  - "Zheng Wang"
  - "Anna Cai"
  - "Xinfeng Xie"
  - "Zaifeng Pan"
  - "Yue Guan"
  - "Weiwei Chu"
  - "Jie Wang"
  - "Shikai Li"
  - "Jianyu Huang"
  - "Chris Cai"
  - "Yuchen Hao"
  - "Yufei Ding"
affiliations:
  - "University of California, San Diego"
  - "Meta"
conference: osdi-2025
code_url: "https://github.com/Ash-Zheng/WLB-LLM-CP"
tags:
  - llm-training
  - gpu
  - scheduling
category: llm-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

WLB-LLM 按预测延迟而不是 token 数量来均衡长上下文 LLM training。它把 variable-length packing 与 outlier delay 用在 PP 层，把免 padding 的 per-document sharding 与自适应 CP 选择用在 CP 层，带来 1.23x 平均端到端提速。

## 问题背景

这篇论文研究的是现有 4D LLM training framework 的一个结构性误配：系统按 token 数量均分工作，但长上下文 transformer 的真实开销并不是按 token 均匀分布的。长上下文训练会把长度差异很大的 document 打包到同一个 sequence 中，再用 attention mask 阻止跨文档 attention。由于 attention 代价取决于 token 在各自 document 里的位置，长文档尾部 token 的计算量远高于短文档中的 token，因此“token 数相等”并不意味着“延迟相等”。

作者在一个内部 405B 训练任务上展示了这一点。该任务运行在 8K H100 GPU 上，context window 为 128K，最慢 GPU 的计算延迟是最快 GPU 的 1.44x。失衡主要出现在两个层面：固定长度 packing 会让某些 pipeline micro-batch 明显更重，而 context parallelism 按位置切 sequence shard，会让拿到文档尾部的 worker 做更多 attention 工作。把更多 global batch 一起重排虽然能改善一部分 balance，但既不能修复 sequence sharding 带来的文档内部失衡，也会破坏 dataloader 的随机性；550M 收敛实验表明，packing window 变大后 training loss 会升高。

## 核心洞察

论文最关键的洞察是：4D training 必须在“失衡产生的粒度”上做均衡。在 pipeline 层，要平衡的是 micro-batch 的预测总延迟，而不是 token 数或固定 sequence 长度；在 context parallel 层，要平衡的是 document 自身形成的 attention triangle，而不是打包后 sequence 上随手切出的等长片段。由此得到的运行时策略是：允许 variable-length micro-batch、只延迟极少数 outlier document，并且根据当前输入结构在 per-document sharding 和 per-sequence sharding 之间做选择。

## 设计

WLB-LLM 先把问题视为失衡传播。TP、CP 与 DP 通过 collective 同步，因此每组都会被最慢 worker 限制；PP 还会进一步放大这种影响。所以论文选择分别修复 PP 与 CP，而不是依赖单一 shuffle 策略。

在 PP 层，WLB-LLM 用 workload-aware variable-length packing 取代 fixed-length packing，目标是最小化最大 micro-batch 的总延迟，其中既包含 attention 的二次项，也包含 GEMM、collective、element-wise 的近线性项。在线 ILP 太慢，因此系统采用 greedy packer 配合多级 outlier queue：超过阈值 `L_i` 的长文档先进入等待队列，等到某一层凑齐“每个 micro-batch 一个 outlier”后再一起释放；其余文档则优先放入当前 workload 最小、且不超过长度上界的 micro-batch。

在 CP 层，WLB-LLM 引入免 padding 的 per-document sharding。它不再把整个 packed sequence 切成 `2 x CP_size` 个等长 chunk，而是把每个 document 本身切成 `2 x CP_size` 个 chunk，并把对称 chunk 对分给不同 worker，使每个 CP rank 获得相同 token 数与 attention 工作量。对于不能整除的长度，实现会把 document 拆成“可整除部分”和“余数部分”，前者做对称切分，后者 round-robin 分配。由于更细粒度切分会降低 kernel 效率，WLB-LLM 再根据离线 profiling 得到的 `Q_len`、`KV_len` 与 achieved TFLOPS，预测 per-sequence 和 per-document sharding 的 attention latency，并按 micro-batch 选择更快的方案。

## 实验评估

实验平台是 32 台节点、每台 8 张 H100 SXM 80GB GPU，通过 NVLink 与 RoCE 互联。作者评估了 550M 到 70B 的内部 LLaMA-like 模型，并覆盖 64K 与 128K context。对照组包括未优化的 `Plain-4D`，以及在单个 global batch 内做 greedy fixed-length packing 并固定 CP sharding 的 `Fixed-4D`。

跨全部设置，WLB-LLM 相比 Plain-4D 的端到端训练提速 1.23x，相比 Fixed-4D 提速 1.19x。7B-128K 的拆解很有代表性：一直使用 per-document sharding 只能得到 1.02x，自适应 CP sharding 提升到 1.05x，单独使用 PP 侧的 variable-length packing 与 outlier delay 则达到 1.28x，两者合并后为 1.33x。context 越长，收益越明显；在 7B 上从 32K 到 160K 时，加速从 1.03x 升到 1.40x。

优化分析同时比较了平衡程度、开销与收敛。Fixed-length ILP solver 虽能降低失衡，但在跨 4 个 global batch 时，每个 batch 的求解开销超过 25 秒；WLB-LLM 使用两个 outlier queue 时，imbalance degree 为 1.05，而 packing 开销只有 20 ms，不到单步时延的 0.65%。在 550M 收敛实验中，跨 8 个 global batch 的 packing 会让平均 training loss 上升 1.6%；WLB-LLM 则由于只延迟少量 token，loss 曲线基本贴近单 batch baseline，平均每个 token 仅延迟 0.5 次 iteration。

## 创新性与影响

相对于 _Narayanan et al. (SC '21)_，WLB-LLM 不是引入新的并行维度，而是让既有 4D parallelism 变得 input-aware。相对于 _Jiang et al. (EuroSys '24)_，它不是为多任务 workload 发明新 pipeline schedule，而是避免单个长文档拖慢同步式 LLM training step。随着 context window 继续增大，这种“修复真实 GPU 空转来源”的思路对长上下文训练框架会很有影响。

## 局限性

最明显的局限是范围。实验建立在作者内部训练栈和内部 LLaMA-like 模型之上，公开 artifact 也只覆盖 CP 优化，而不是整套系统。模型越大时，收益还会因为通信占比上升而下降。算法层面，WLB-LLM 仍依赖离线 profiling 和启发式 queue threshold；CP 选择器也只能对整个 sequence 做二选一。最后，PP 优化本质上还是通过延迟 outlier 来换取平衡，论文证明这种扰动足够小，但它依然是一个有代价的折中。

## 相关工作

- _Narayanan et al. (SOSP '19)_ — PipeDream 关注的是 pipeline 本身如何执行，而 WLB-LLM 关注的是在既定 pipeline 中流动的 variable-cost micro-batch 如何被均衡。
- _Narayanan et al. (SC '21)_ — Megatron-LM 奠定了大规模 tensor、pipeline 与 data parallel training 的基础，但它默认 batch 是按 token 均衡，而不是按真实 workload 均衡。
- _Jiang et al. (EuroSys '24)_ — DynaPipe 为多任务训练动态优化 pipeline schedule；WLB-LLM 则处理单一长上下文 LLM workload 内部由输入长度差异带来的失衡。

## 我的笔记

<!-- 留空；由人工补充 -->
