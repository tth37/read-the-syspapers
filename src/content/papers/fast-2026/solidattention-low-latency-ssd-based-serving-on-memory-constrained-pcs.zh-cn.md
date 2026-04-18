---
title: "SolidAttention: Low-Latency SSD-based Serving on Memory-Constrained PCs"
oneline: "SolidAttention 把稀疏注意力、SSD 友好的 KV 布局、推测预取和 DAG 调度一起设计，让 128k 上下文 LLM 在内存受限 PC 上最高快 3.1x。"
authors:
  - "Xinrui Zheng"
  - "Dongliang Wei"
  - "Jianxiang Gao"
  - "Yixin Song"
  - "Zeyu Mi"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems (IPADS), Shanghai Jiao Tong University"
conference: fast-2026
category: ai-era-storage
tags:
  - llm-inference
  - storage
  - caching
  - memory
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

SolidAttention 是一个面向 AI PC 的 SSD-backed LLM inference engine，目标是在内存放不下长上下文 KV cache 的情况下，仍然把本地推理延迟压下来。它的关键做法不是单独改一个稀疏注意力算法，而是把注意力选择、KV 布局、预取和调度一起设计：用交错的 K/V 布局做粗粒度传输，用历史选择结果做推测预取，再把 GPU 计算和 SSD I/O 按微任务重叠。对 `128k` 输入，它最高带来 `3.1x` 吞吐提升，并把 KV cache 内存占用压低约 `98%`，同时保持接近原模型的精度。

## 问题背景

这篇论文瞄准的是一个很具体、但越来越现实的部署场景：在内存受限的个人电脑上本地运行长上下文 LLM。作者指出，这个场景和数据中心 serving 的默认假设并不一样。很多出货 PC 仍然只有 `8-16 GB` DRAM，以及 `6-8 GB` VRAM；但长上下文模型却越来越默认 `128k` context。对一个 `8B` 模型来说，仅 KV cache 就可能超过 `16 GB`，达到量化后模型权重体积的 `4x` 以上。于是，“把整个 KV cache 都留在内存里”这个常见前提，在本地 AI PC 上并不成立。

看起来显然的两个方向都不够理想。第一种是激进的 KV-cache quantization，它确实省内存，但论文认为这种方法很容易伤害精度，后面的实验也验证了这一点，尤其是在 KV 中存在 outlier 时更明显。第二种是把 KV cache 放到 SSD 上，再结合 dynamic attention sparsity，只按需取回重要块。问题在于，已有 SSD-based 方案大多是 throughput-oriented 的，默认可以靠多个并发请求把 I/O 延迟藏在别的计算后面；而本地 AIPC inference 往往 batch size 只有 `1`，这种隐藏窗口根本不存在。

论文更锋利的判断是，真正的冲突来自 sparse attention 和 SSD 的物理特性不匹配。稀疏注意力天然会产生不规则、细粒度的访存，而 SSD 只有在较大、较顺序的传输下才能跑出高带宽。如果系统只是把原有稀疏算法照搬到 SSD 后端，而不重新设计数据布局和调度，结果就会是 SSD 带宽利用率低、decode 阶段频繁阻塞。

## 核心洞察

这篇论文最值得记住的主张是：SSD-backed sparse attention 只有在“注意力机制”和“存储路径”共同设计时才会真正低延迟。SolidAttention 的重点并不是提出新的 block selection 规则，而是想办法在不牺牲 dynamic attention sparsity 精度收益的前提下，把生成出来的访问流改造成 SSD 擅长处理的形态。

围绕这个目标，作者给出了三个相互配合的判断。第一，应该放大传输粒度，但不要放大语义选择粒度。也就是说，不能简单把 token block 做得更大，否则 representative vector 会越来越粗糙、召回率下降；更好的办法是把每个 token 的 `K` 和 `V` 交错存放并一起搬运。第二，相邻迭代之间的 block 选择具有很强的时间局部性，论文测得相似度大约有 `81%`，因此可以利用历史选择结果做 speculative prefetch。第三，GPU 计算和 SSD I/O 不能按“整层串行”的视角去安排，而要拆成依赖明确的微任务，让缺失块加载、投影、attention 和写回在 DAG 上细粒度重叠。

## 设计

SolidAttention 保留了 block-wise sparse attention 的基本骨架，但把它重新调成面向存储的形态。KV cache 被分成三类块：处理 attention sink 的 init blocks、覆盖最新上下文的 local blocks，以及通过 query 和 representative similarity 动态选出来的 selected blocks。代表向量的提取方式大体沿用了 InfLLM 一类工作，因此论文真正的新意不在“怎么挑块”，而在“挑完之后怎么高效搬和算”。

第一部分是 `KV Consolidator`。传统实现里，`K` 和 `V` 是分别生成、分别存储的。SolidAttention 把它们按 token 粒度交错，直接把这种 interleaved layout 作为传输和计算单位。这样做的好处是：在不增加每个选择块内 token 数量的前提下，把单次传输大小翻倍、I/O 次数减半，因此不会像简单增大 block size 那样损失召回率。为了避免运行时再做一次昂贵重排，系统在模型初始化时就把 `K` 和 `V` projection weights 预先拼接，让一次矩阵乘法直接产出交错的 KV。注意力 kernel 只需要按 `2H` 的固定 stride 读取，论文报告这带来的额外延迟不超过 `2%`。

第二部分是 `Speculative Prefetcher`。难点在于，后续层到底会选哪些块，只有算出那一层的 query 之后才知道。SolidAttention 利用时间局部性，记录每层上一轮 decode 的选择结果，并把这些 selected blocks 连同必选的 init/local blocks 一起提前从 SSD 预取出来。若预测错了，系统也不做全局重排。它利用 self-attention 的一个重要性质：全局 token 顺序其实可以任意，只要每个 token 的 `K` 和 `V` 仍然对齐即可。于是，缺失块可以直接覆盖错误预取的块，misprediction 就从一次昂贵的缓存整理，变成一次轻量 overwrite correction。

第三部分是 `SSD-aware Scheduler`。作者把一个 attention layer 拆成 `q proj.`、`kv proj.`、`select`、`prefetch`、`load`、`attention`、`store` 等微任务，再在这些微任务之间建依赖 DAG。调度器优先执行 critical path 上的任务，并尽量提前发起 I/O，让缺失 selected block 的加载和 GPU 计算并行。它还会计算 latest start time，对已经 ready 的任务做优先级排序，尽量避免关键路径被拖慢。另一项优化是复用同步点：非关键的 store 可以和关键的 prefetch/load 共用 CPU-GPU handshakes，而不是单独再同步一次；在 unified memory 平台上，这些同步甚至还能进一步减少。

## 实验评估

实验设置和论文宣称的目标场景是对齐的。SolidAttention 构建在 `llama.cpp` 和 `liburing` 之上，总实现约 `25k` 行代码，分别跑在一台带 `RTX 4070 Laptop GPU` 的 CUDA laptop 和一台带 `Intel Arc 140T` integrated GPU 的 SYCL laptop 上。评测模型包括 `Llama-3.2-3B`、`Llama-3.1-8B` 和 `Qwen-2.5-7B`，权重都是 INT4、KV cache 保持 FP16。所有实验都固定 batch size 为 `1`、最大输出长度为 `512`，并限制 DRAM 使用为 `16 GB`。这套配置明确就是在考察“低并发、本地长上下文推理”。

端到端结果很有说服力。在 CUDA backend 上、`128k` 输入时，SolidAttention 相比 `Offload+Sparse` 分别为三种模型带来 `2.8x`、`3.1x` 和 `2.4x` 的吞吐提升；和 FlexGen 相比，在 `16k` context 时最高快 `58.9x`，而 FlexGen 在 `16k` 以上还会直接 OOM。到了 SYCL backend，它相对 `Offload+Sparse` 的收益仍达到 `2.1x`、`2.5x` 和 `1.9x`。内存节省同样关键：因为系统只为单层、`1k` context budget 的 KV cache 分配 buffer，所以在三种主模型上把 KV 内存压到原来的大约 `1/62`，对更大的 `Qwen2.5-14B` 也能做到约 `98%` 的 KV 内存下降。精度方面，SolidAttention 在 OpenCompass 和 LongBench 上都基本贴近原始 `llama.cpp`，而 INT4 KV quantization 的退化明显更大，尤其是 `Qwen-2.5-7B`。

更重要的是，消融实验基本把机制链条补齐了。Speculative prefetching 在 SYCL 上把阻塞延迟最高降低 `3.1x`，在 CUDA 上最高降低 `3.9x`。Interleaved KV layout 最多把 attention latency 再降 `22%`。Fine-grained overlap 最多带来 `25%` 的性能提升，而 synchronization reuse 又能在 SYCL 平台上额外降低 `22%` attention latency。我认为这些结果基本支撑了论文中心论点。需要保留的一点是，FlexGen 原本只支持某些模型和 CUDA，作者为了比较自行扩展到了 Llama/Qwen，所以这部分对比不像 `Offload` 和 `Offload+Sparse` 那样完全天然。

## 创新性与影响

相对于 _Tang et al. (ICML '24)_ 和 _Xiao et al. (NeurIPS '24)_，SolidAttention 的贡献不在于再发明一种新的 sparsity rule，而在于为 block-wise sparsity 搭了一个 storage-conscious 的执行底座。相对于 _Sheng et al. (ICML '23)_，它的创新点在于明确提出：低并发的本地 decode 不是 cloud throughput serving 的缩小版，目标函数和系统瓶颈都不一样。相对于 _Chen et al. (FAST '25)_，它优化的是即时的 GPU-SSD KV 传输与调度，而不是依赖多请求共享前缀的云端多级缓存。

因此，这篇论文更像是在回答“consumer SSD 能不能变成 LLM KV 的有效外存层”这个系统问题。对 on-device、edge、AIPC 这类部署来说，它的影响可能会大于对稀疏注意力算法本身的影响，因为它证明了只要软件栈尊重 SSD 的传输粒度、可预取性和同步成本，消费级存储并不一定只能带来灾难性的 decode latency。

## 局限性

这套设计的胜利区间其实比较窄，论文对此也算坦诚。它最强的场景是单用户、本地、低并发的 inference；对于多租户 serving、大 batch，或者本来就有足够并发来掩盖 I/O 延迟的系统，论文没有给出太多答案。实现本身也不轻：interleaved weights、历史驱动的 speculative prefetch、overwrite correction、DAG scheduling 和 synchronization reuse 必须同时配合，工程复杂度不低。

性能也明显依赖 SSD 余量。在有后台 I/O 干扰时，SolidAttention 的吞吐在 `4 GB/s` 带宽型干扰下下降 `58%`，在 `800k` 随机读 IOPS 干扰下降 `54%`。论文还显示，一旦 context budget 提高到 `4k`，I/O 就重新变成瓶颈，这也是它最终选择 `1k` budget 的原因。所以，这个系统在论文测试的本地 PC 包络内确实有效，但如果 SSD 带宽很紧张，或者任务必须保留更大的上下文预算，它的隐藏延迟逻辑就会明显变弱。

## 相关工作

- _Tang et al. (ICML '24)_ — Quest 推广了 query-aware 的 block sparsity，而 SolidAttention 保留这种按块选择思路，但把数据布局和预取策略重新设计成面向 SSD。
- _Xiao et al. (NeurIPS '24)_ — InfLLM 提供了 representative-vector 驱动的 block selection 和内存内长上下文外推；SolidAttention 则把 SSD offloading 本身变成了一等系统问题。
- _Sheng et al. (ICML '23)_ — FlexGen 同样尝试把 offloaded KV 访问和计算重叠，但它依赖 token 级访问与并发隐藏，在低并发本地 decode 下很容易失效。
- _Chen et al. (FAST '25)_ — IMPRESS 面向云端、多请求共享前缀的多级 KV 存储；SolidAttention 则聚焦单用户 decode latency 和直接的 GPU-SSD 传输效率。

## 我的笔记

<!-- 留空；由人工补充 -->
