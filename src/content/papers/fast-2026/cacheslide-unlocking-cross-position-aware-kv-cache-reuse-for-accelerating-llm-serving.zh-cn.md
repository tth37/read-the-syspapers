---
title: "CacheSlide: Unlocking Cross Position-Aware KV Cache Reuse for Accelerating LLM Serving"
oneline: "CacheSlide 用 CCPE、选择性纠正和 spill-aware paging 复用发生位置滑移的固定提示段 KV cache，把延迟最高降到 4.3x。"
authors:
  - "Yang Liu"
  - "Yunfei Gu"
  - "Liqiang Zhang"
  - "Chentao Wu"
  - "Guangtao Xue"
  - "Jie Li"
  - "Minyi Guo"
  - "Junhao Hu"
  - "Jie Meng"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Jinan Inspur Data Technology Co., Ltd"
  - "Peking University"
  - "Huawei Cloud"
conference: fast-2026
category: ai-era-storage
code_url: "https://github.com/SJTU-Storage-Lab/CacheSlide"
tags:
  - llm-inference
  - caching
  - memory
  - storage
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CacheSlide 面向一种很常见的 agent prompt 形态：可复用的固定段会随中间更新段一起发生绝对位置滑移，但它们之间的相对顺序基本不变。它把低位置敏感度编码 `CCPE`、top-k 选择性纠正 `Weighted Correction Attention` 和 spill-aware 的 KV 运行时 `SLIDE` 组合起来，比 prefix caching 或通用 PIC 复用掉更多 prefill 工作。论文在三个模型和三类 agent workload 上报告了 `3.11-4.3x` 的延迟下降和 `3.5-5.8x` 的吞吐提升。

## 问题背景

论文关注的是 agent 场景下的 LLM serving。这里的 prompt 往往不是“稳定前缀 + 新用户输入”这么简单，而是把 system prompt、长期记忆、过往工具调用结果等固定段，与最新的 reasoning step、memory update、function arguments 等动态段交织在一起。大部分内容其实可以复用，但这些可复用段通常被长度不断变化的更新段隔开。

这会同时击穿两类主流 KV cache reuse 策略。Position-Dependent Caching，也就是 prefix caching 一类方法，只能在固定绝对位置复用，因此在 agent prompt 里往往只能重用 system prompt。Position-Independent Caching 虽然允许任意位置复用，但它会把旧段搬到新位置，再通过部分 token 重算去修补位置错位。论文认为这带来两层代价：一层是 positional mismatch 导致的精度下降，另一层是系统层面的开销，因为旧 KV page 的加载和修正后 KV 的写回通常按层串行，直接落在 prefill critical path 上。

作者还验证了一个看似自然的替代思路：window padding，也就是把动态段长度固定住，让固定段不要移动。结果也不好。如果窗口太小，agent 会丢掉重要信息；如果窗口太大，固定段仍然会发生足够明显的位置漂移，导致缓存相似度下降。论文因此提出，agent 真正需要的既不是“只能复用前缀”，也不是“支持完全任意搬移”，而是针对“相对顺序稳定、绝对位置滑移”的一类 reuse。

## 核心洞察

这篇论文最重要的判断是：agent prompt 暴露出的复用模式，其实比既有工作假设的更窄，也更容易利用。可复用段不是无约束地到处移动；它们通常保持相对顺序不变，只是被中间更新段推着整体前后滑动。论文把这个模式定义为 `Relative-Position-Dependent Caching` (`RPDC`)。

这个定义之所以重要，是因为它改变了“到底需要修什么”。如果 positional encoding 的选择和分配方式足够温和，使得被复用 chunk 在实际推理中的位置与缓存时的位置足够接近，那么固定段内部的 attention，以及固定段之间的 cross-attention，理论上都可以近乎无损地复用。真正需要额外恢复的，只剩固定段和最新更新段之间的 cross-attention。换句话说，问题不再是“为了任意搬移而重算足够多 token”，而是“先把固定段对齐到足够接近，再只做小范围纠正”。

## 设计

CacheSlide 由三个部分组成。第一部分 `CCPE`（`Chunked Contextual Position Encoding`）负责编码侧对齐。系统假设同一类 agent task 的 prompt 可以按模板切成按序排列的 reuse chunks 和 recompute chunks。它先用 `CoPE` 做 task-specific pretraining，统计最常见的 positional pattern，再在后续加载缓存 KV 时，把这些学到的编码范围分配给重用 chunk。目标不是让位置完全一样，而是把位置差压到足够小，从而维持高 `CKSim`。

第二部分 `Weighted Correction Attention` 负责补上 CCPE 不能自动恢复的那部分注意力。第一层里，CacheSlide 会把整条 prompt 全量重算一次，测量每个 token 在“缓存 KV”和“重算 KV”之间的偏差，再选出漂移最大的 top-k token。之后的层里，它只重算这些 token，用 learned weights 融合重算得到的 KV 和缓存 KV，并且每四层检查一次 `CKSim`，判断某个 token 是否已经足够收敛，可以从 active correction set 里移除。论文给出的最佳工作点大约是 top-k `0.26`、`CKSim` 阈值 `0.12`。这正体现了它的总体策略：不是大面积重算，而是挑出真正关键的一小部分做修补。

第三部分 `SLIDE` 是系统实现上的关键，它避免纠正逻辑把自己变成新的存储瓶颈。作者在 `vLLM 0.8.5` 上实现它：先为 selected tokens 预分配额外 KV pages，把被修正的 token 迁移到这些页面中，使“加载旧 KV”和“写入新 KV”不必在层内串行；decode 阶段继续复用这些映射，优先做 in-place overwrite。若内存压力触发 spill，系统会把含 selected tokens 的页面标成 dirty，优先驱逐 clean pages，再按 selected-token count 排序驱逐 dirty pages，以便尽量合并写入、降低 SSD write amplification。

## 实验评估

实验使用三个模型：`Mistral-7B`、`MPT-30B` 和 `Llama-3 70B`；三个 agent workload：Reflexion 对应的 `HotPotQA`、MemGPT 对应的 `Multi-Session Chat`、以及 SWE-Agent 对应的 `SWE-Agent-Bench`；硬件则是一台带 A100 GPU、`500 GB` DRAM 和 `2 TB` NVMe SSD 的服务器。对比对象包括全量重算、`ContextCache`、`PromptCache`、`CacheBlend` 和 `EPIC`。核心结果相当强：跨模型和 workload，论文报告相对这些 PIC/PDC baseline 实现了 `3.11-4.3x` 的延迟下降和 `3.5-5.8x` 的吞吐提升，同时落在最优的 accuracy-TTFT frontier 上。相对 `ContextCache`，它把 TTFT 压低 `2.4-3.3x` 且几乎不损失精度；相对 `CacheBlend`，它把 TTFT 再降低 `1.21-2.11x`，同时精度也更高。

系统层面的消融同样支撑了设计链条，而不是只靠 headline number。`SLIDE` 把 layer-wise parallel latency 降低 `26.7-51.5%`，把 write stalls 降低 `66.9-73.5%`，并把 SSD write amplification 降低 `3.11-3.62x`。在 parallel inference 和 beam search 下，随着压力增大，它相对最佳 baseline 的优势还会继续扩大，在 batch size `6` 时大约达到 `2.3x`，在 beam width `6` 时达到 `2.1x`。这说明论文不只是提出了一个 prompt-level caching 思路，而是把“修正后的 KV 如何在 paged runtime 里流动”也真正做成了系统设计。

不过这里有一个我认为必须保留的 fairness caveat：CacheSlide 通过 adapter-based continued pretraining 启用了 `CoPE`，而 baselines 则保持各自原生的 positional encoding。也就是说，这里的收益一部分来自 RPDC 机制本身，一部分来自修改后的模型编码栈。论文对这个设置是明确说明的，但这也意味着这些增益并不完全等价于“纯缓存管理带来的提升”。

## 创新性与影响

相对于 _Gim et al. (MLSys '24)_，CacheSlide 并不是靠为同一段文本维护很多绝对位置版本来实现复用，而是定义了一个更窄但更常见的结构化场景，并直接利用这种结构。相对于 _Yao et al. (EuroSys '25)_ 和 _Hu et al. (ICML '25)_，它不如通用 PIC 那样泛化，但这恰恰也是它的优势来源：需要修复的位置漂移更小、需要重算的 token 更少、load/write 路径也更容易做干净的系统优化。相对于 _Yu et al. (EuroSys '25)_ 这类 prefix-only 的 stateful serving 工作，它把 agent prompt 视作一类值得单独优化的系统目标，而不是 prefix cache 的边角案例。

因此，这篇论文不只是一个小优化。它同时贡献了新的问题定义（`RPDC`）、具体的复用机制（`CCPE` + `Weighted Correction Attention`），以及能把这些机制落到延迟和 SSD 写放大收益上的运行时设计（`SLIDE`）。做 agent serving、prompt caching 或 storage-aware LLM runtime 的研究者，都会直接引用这篇工作。

## 局限性

CacheSlide 最强的假设是结构规律性。`CCPE` 依赖 prompt 能按任务模板切成 reuse/recompute chunks，还要在单任务模式下学习主导性的 positional pattern。这很适合重复执行同一种 agent workflow，但对于 heterogeneous、变化频繁、chunk boundary 不稳定的 prompt，论文给出的证据明显少很多。

纠正逻辑本身也需要调参。论文把 top-k `0.26` 和 `CKSim` `0.12` 找作最佳区域，这说明方法对 workload 仍有一定敏感性。主图中的比较还大多在 batch size `1` 下完成，因此“accuracy-TTFT 最优”这个结论最强地成立于低并发 serving；更高 batch 的实验主要是在验证 `SLIDE` 受压时的系统表现，而不是完整的质量表现。最后，由于 CacheSlide 依赖 `CoPE` adapter 和 task-specific preprocessing，它的部署成本高于纯 runtime-only 的 cache layer，而论文也没有完全量化：如果底座模型必须严格 frozen，最终还能剩下多少收益。

## 相关工作

- _Gim et al. (MLSys '24)_ — PromptCache 支持模块化 attention reuse，但它仍然是 position-dependent 的，需要为不同绝对位置维护额外版本；CacheSlide 避开了这部分存储代价。
- _Yao et al. (EuroSys '25)_ — CacheBlend 是典型的 PIC 设计，要在任意搬移之后修复 positional drift；CacheSlide 则先把场景收窄到 RPDC，再提前降低 drift。
- _Hu et al. (ICML '25)_ — EPIC 形式化了 position-independent context caching，而 CacheSlide 认为 agent prompt 往往具有更强的相对顺序结构，可以更激进地利用。
- _Yu et al. (EuroSys '25)_ — Pensieve 做的是 stateful prefix caching；CacheSlide 处理的是可复用内容不只存在于前缀的多段 agent prompt。

## 我的笔记

<!-- 留空；由人工补充 -->
