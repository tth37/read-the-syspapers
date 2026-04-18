---
title: "DiffKV: Differentiated Memory Management for Large Language Models with Parallel KV Compaction"
oneline: "DiffKV 按头把 token 分成 K8V4、K4V2 或裁剪，让 key 比 value 保留更高精度，再用 GPU 端并行 compaction 把不规则 KV 压缩真正变成吞吐提升。"
authors:
  - "Yanqi Zhang"
  - "Yuwei Hu"
  - "Runyuan Zhao"
  - "John C.S. Lui"
  - "Haibo Chen"
affiliations:
  - "Huawei"
  - "The Chinese University of Hong Kong"
  - "Shanghai Jiao Tong University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764810"
tags:
  - llm-inference
  - memory
  - caching
  - gpu
category: llm-serving
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

DiffKV 的核心观点是，KV cache compression 不能把 key、value、token 和 attention head 一视同仁。它让 key 用比 value 更高的精度保存，按每个 head 的 token 重要性把缓存分成 K8V4、K4V2 和直接裁剪三档，再用 GPU 端 parallel KV compaction 管理由此产生的不规则布局。论文在多种 LLM 上报告了 2.7x-5.7x 的 KV cache 压缩率，并在几乎不损失生成质量的前提下把吞吐提高 1.9x-5.4x。

## 问题背景

这篇论文针对的是 LLM serving 中最直接也最顽固的瓶颈之一：KV cache。自回归推理时，KV cache 会随着序列长度和并发请求数线性增长，作者引用的已有观察指出，它往往会占到总显存开销的 90% 以上。于是系统能同时服务多少请求，很多时候并不是算力决定的，而是历史 token 能否继续驻留在显存里决定的。

现有方法主要走两条路：pruning 和 quantization。但两者大多都过于“均匀”。Pruning 方案会根据 attention score 丢掉不重要的 token，却通常给所有 head 或 layer 分配同样的缓存预算；quantization 方案则把所有 key 和 value 都压到同一个 bit width，默认它们在 attention 里的作用差不多。这会错过两个重要差异：第一，key 与 value 在注意力计算里的职责不同；第二，不同请求、不同 head 的信息密度并不一样，有的 prompt 可以激进压缩，有的则不能。

更棘手的是系统层面的后果。只要压缩策略真的开始因 head 和请求而异，显存布局就会变得不规则：有的 head 需要更多高精度页，有的只需要少量低精度页，还有些 token 会被直接裁掉。这时 allocator 不再面对“每个请求一个整齐的 KV cache”，而是每一步都要协调成千上万个异构内存区域。若内存管理跟不上，这种更聪明的压缩就只能节省字节，未必能真正换来吞吐。

## 核心洞察

论文最重要的命题是：KV cache compression 应该顺着 attention 本身的结构来做。Key 比 value 更重要，因为 key 参与 attention score 的计算，会通过 softmax 分母影响所有 token 的权重；而每个 value 只影响它自己那一项的加权求和。作者在 Llama3 上的实证也支持这一点：attention score 大约跨越 7 个数量级，而 value norm 只跨越约 2 个数量级，这说明保持 score 的精度，比精确保持 value 的幅值更关键。

但这只是第一层差异。第二层差异来自 token importance：不同 token 对输出的贡献高度不均匀。第三层差异来自 dynamic sparsity：这种不均匀程度会随着 attention head 和请求一起变化，同一个 head 在不同 prompt 下需要保留的关键 token 数量也会不同。DiffKV 的关键洞察不只是“做非对称量化”，而是把“key/value 差异”“token 重要性层级”“按 head 和请求动态分配预算”这三件事绑在一起。这样一来，不规则性就不再是副作用，而是进一步压缩的依据。

## 设计

DiffKV 采用两级量化加 pruning。最重要的 token 存为 K8V4，中等重要的 token 存为 K4V2，最不重要的则直接删掉。在 prompt phase 中，系统根据一个 token 被后续 token 关注到的程度来计算其重要性；若模型采用 GQA 或 MHA，则把对应 query heads 的分数用 max 聚合到同一个 KV head。最近的 64 个 token 总是保留在高精度，避免过早压缩。更早的 token 则与随序列长度缩放的阈值 `alpha_h / i` 和 `alpha_l / i` 比较，其中 `i` 是 token 位置，因此上下文越长，策略越激进。

到了 generation phase，逻辑相同，但以增量方式执行。一个 token 刚离开 recent window 时，DiffKV 会决定它该进入高精度区、低精度区，还是直接被剪掉。如果某个 tier 插入了新 token，系统还会检查该 tier 中当前最不重要的老 token，并在需要时把它从高精度降到低精度，或者从低精度继续删除，于是形成一条平滑的“高精度→低精度→裁剪”的退化路径。阈值由离线 profiling 在高信息密度的推理数据集上拟合得到；论文之所以只保留两级量化，是因为再增加层级会更快地抬高 metadata 和 memory-management 开销。

真正体现系统价值的是 GPU memory manager。DiffKV 提出 unified pages：页的格式在分配时才确定，因此每个页都能紧凑存放一种精度模式，而不必为所有 token 保留最坏情况布局。所有 page ID 保存在一个 circular free-page list 中，用 start/end pointer 跟踪分配和回收位置，从而能用 prefix sum 协调并行分配。它还把高精度和低精度页表合并成一个 bidirectional page table，让高精度页从左往右长、低精度页从右往左长。每个 head 先并行决定自己需要多少页，再由 GPU 上的协调阶段把这些需求映射到物理页。最后，自定义 attention kernel 会分别高效处理高精度页和低精度页，并用专门设计的数据布局保证访存尽量 coalesced。

## 实验评估

实验覆盖 Llama3-8B/70B、Qwen2.5-7B/32B，以及 QwQ-32B、R1-Distill-Qwen-14B、R1-Distill-Llama-8B 这三类 thinking models。大多数吞吐实验在 NVIDIA L40 上完成，另外还移植到 Ascend NPU，以说明论文的方法不依赖某一家加速器。

第一类结果验证了“key 要比 value 更高精度”这一直觉不是拍脑袋。K8V4 在 GSM8K 和 HumanEval+ 上基本能保持与 FP16 一致的质量，而镜像配置 K4V8 或 K2V4 会明显掉点，有些情况下甚至接近零准确率。这直接支撑了论文关于 key 更重要的论点。第二类结果验证 dynamic sparsity 优于静态按头均分预算的 pruning：在 Llama3-8B 上，DiffKV 在 GSM8K 中即便裁掉 50% token 仍能保持满精度，而静态 sparsity 在同等裁剪率下更早失真。

综合起来看，DiffKV 在非 thinking models 上只使用 FP16 KV memory 的 19.3%-36.7%，平均准确率仅下降 0.3%。在 thinking models 上，长链式推理会把压缩误差在 generation 中不断累积，但 DiffKV 依然能在 23.5%-29.4% 的显存占用下维持接近 FP16 的质量。系统性能方面，DiffKV 相对 vLLM 的吞吐提升达到 1.9x-5.4x；在 QwQ-32B 上，持续 batch size 从 2.7 提升到 15.9，吞吐达到 5.4x。更关键的是，memory manager 并没有吞掉这些收益：parallel KV compaction 在 prompt step 中占总延迟不到 0.2%，在 generation step 中不到 0.9%。

## 创新性与影响

这篇论文最有价值的地方在于，它把“压缩策略”和“系统机制”放到同一个问题里讨论。以往工作往往专注于挑更该删的 token，或者设计更省空间的低比特表示；DiffKV 则指出，这些选择必须和 allocator、page table、attention kernel 一起设计，因为 differentiated compression 天生会制造按 head 不规则的显存需求，而传统内存管理器无法有效利用这种不规则性。对真正做 LLM serving runtime 的人来说，这个结论很重要：未来 KV cache 的收益，很可能来自 compression policy、memory layout 和 runtime manager 的联合设计，而不是单点优化。

## 局限性

DiffKV 依赖离线校准，而且参数具有一定模型相关性。Qwen2.5-7B 就敏感到论文最终关闭了它的低精度量化路径。这并不否定方法本身，但说明它还不是完全 tuning-free 的通用方案。

实现复杂度也不低。论文里最强的性能结果建立在自定义 attention kernel、GPU 驻留的 memory-management data structures，以及对 vLLM 的深度集成之上。如果只在更高层框架里套用同样的压缩策略，质量收益大概率还能保留一部分，但吞吐收益未必能原样复现。最后，评测主要覆盖两级量化、FP16 权重和论文选定的 serving workload；对于多租户、prefix reuse 更强的部署形态，论文没有做深入分析。

## 相关工作

- _Kwon et al. (SOSP '23)_ - PagedAttention/vLLM 用分页把不断增长的 KV cache 管理得更高效，但它假设缓存格式基本规则，而不是像 DiffKV 这样按 head 混合精度并结合 pruning。
- _Lin et al. (arXiv '24)_ - QServe 证明了低比特 KV quantization 可以系统化落地，而 DiffKV 进一步让 key、value 和 token 之间使用不同精度，而不是给整份 KV cache 固定一个量化格式。
- _Li et al. (arXiv '24)_ - SnapKV 利用 attention importance 做 token pruning，但它对不同 head 的预算分配比 DiffKV 静态得多，无法同样细致地按 head、按请求自适应。
- _Liu et al. (arXiv '24)_ - KIVI 提供了无需调参的非对称低比特 KV quantization，而 DiffKV 在此基础上进一步加入分层 token 选择，以及能够利用不规则压缩布局的运行时内存管理。

## 我的笔记

<!-- 留空；由人工补充 -->
