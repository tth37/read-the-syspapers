---
title: "MoDM: Efficient Serving for Image Generation via Mixture-of-Diffusion Models"
oneline: "MoDM 缓存最终图像，用更便宜的 diffusion model 细化 cache hit，并在线重分配 GPU，在尽量保住大模型质量的同时提升吞吐。"
authors:
  - "Yuchen Xia"
  - "Divyam Sharma"
  - "Yichao Yuan"
  - "Souvik Kundu"
  - "Nishil Talati"
affiliations:
  - "University of Michigan, Ann Arbor, MI, USA"
  - "Intel Labs, Los Angeles, CA, USA"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3760250.3762220"
code_url: "https://github.com/stsxxx/MoDM"
tags:
  - ml-systems
  - caching
  - gpu
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

MoDM 认为 diffusion serving 里真正应该缓存的不是某个模型内部的 latent，而是最终生成的图像。请求命中缓存时，系统先用 CLIP 找到视觉上最接近的新旧图像，再向该图像重新注入噪声，把生成过程跳回到一个中间时间步，然后只让一个更小的模型补完剩余 denoising。与此同时，全局监控器会根据负载在大小模型之间在线切换 GPU，因此它比单模型 serving 在吞吐和 SLO 上稳得多，同时图像质量又明显好于直接使用小模型的方案。

## 问题背景

这篇论文解决的是文本生成图像服务里一个很直接但一直没有被真正化解的矛盾：高质量图像通常来自大 diffusion model，但这类模型每次推理都要跑几十步 denoising，所以延迟很高；小模型和蒸馏模型虽然更快，却会明显损失图像保真度。对服务提供者来说，这意味着一旦请求率上升，就必须在质量和响应时间之间做一个很难看的静态取舍。

已有缓存系统能缓解一部分开销，但远远不够。像 Nirvana 这样的工作缓存的是中间 latent 表示，确实能让后续相似请求跳过一部分计算，但这些缓存条目和模型强绑定，几乎不能被别的模型复用。于是，系统无法自然地形成“cache miss 用大模型、cache hit 用小模型”的混合服务路径。作者还给出一个很具体的空间对比：以 Stable Diffusion-3.5-Large 为例，缓存多份 latent 大约需要每张图 `2.5 MB`，而只缓存最终图像约为 `1.4 MB`。更重要的是，即便命中率已经很高，先前工作的总计算节省仍然有限，所以在突发流量下依旧容易出现长队列和 SLO 违约。

因此，论文真正关心的问题不是“怎样把一个 diffusion model 再压快一点”，而是“怎样构造一个能够在线适配延迟与质量、又不会把缓存绑死在单一模型上的 serving stack，并且在请求率变化时保持稳定”。

## 核心洞察

MoDM 最值得记住的洞察是：最终图像才是不同模型之间可复用的边界。如果缓存里存的是完成态图像和它的 embedding，那么这个缓存对象就不再依赖某个特定模型的内部表示，后续请求既可以由大模型补全，也可以交给更便宜的小模型做 refinement。latent caching 做不到这一点，因为 latent 本身就是模型私有格式。

第二层洞察来自 diffusion 过程本身。论文引用的经验事实是，前面的 denoising 步主要决定图像的大体结构，后面的步骤更多是在补细节。如果缓存中的旧图像已经和新 prompt 在视觉上足够接近，那么系统就可以往这张旧图里重新加噪，让它回到某个中间时间步，然后跳过前 `k` 步，只执行剩余的 denoising。这样一来，昂贵的大结构已经由旧图“继承”下来，小模型只需要负责最后的细修。

这个想法只有在资源分配也跟着改变时才真正成立。cache miss 仍然必须交给大模型，因为它需要完整从零生成；cache hit 则是另一类工作负载，只要质量损失被控制在界内，就应该尽量转移给小模型。MoDM 的贡献就是把这套观察落成一个完整的服务策略。

## 设计

MoDM 的设计核心有两个控制点：request scheduler 和 global monitor。request scheduler 收到 prompt 后，先用 CLIP 生成文本 embedding，然后去搜索缓存中的历史图像 embedding。只有当余弦相似度超过阈值时，请求才会被认定为 cache hit。和已有工作不同，这里的检索是 text-to-image，而不是 text-to-text；作者用 CLIPScore 和 PickScore 的分布说明，视觉对齐比单纯的 prompt 文本相似更能反映“取回来的图是否真的适合拿来继续生成”。

命中缓存后，系统并不会直接返回旧图，而是按照 diffusion 的噪声日程重新向图像注入噪声，把它送回一个中间时间步，再从那里继续生成。MoDM 把可跳过的步数 `k` 限制在 `{5, 10, 15, 20, 25, 30}` 这六个离散值里，并依据检索相似度用一个经验启发式来选 `k`。论文把目标质量约束写成相对完整大模型生成至少保留 `alpha = 0.95` 的质量；在留出的样本上，这个启发式最终达到基线 CLIP 分数的 `99.7%`，同时减少了大量 denoising 工作。

第二部分是资源管理。大模型 worker 优先处理 cache miss，因为这些请求需要完整的 `T = 50` 步生成；小模型 worker 则集中处理 cache hit refinement。global monitor 会持续记录请求率、cache hit rate，以及不同 `k` 取值形成的工作量分布，然后计算有多少 GPU 应该运行大模型、多少应该运行小模型。在 quality-optimized mode 下，它会在满足 hit/miss 工作量约束的前提下尽量多保留大模型；在 throughput-optimized mode 下，它把所有 hit 都交给小模型，并按照加权后的 hit/miss 工作负载比例分配 GPU。最后，再用 PID controller 平滑这些调整，避免负载变化时频繁抖动。

缓存维护策略反而很朴素。MoDM 没有使用复杂的 utility-based policy，而是采用 FIFO 风格的 sliding window。理由是，作者在 DiffusionDB 上看到超过 `90%` 的 cache-hit 请求检索到的图像，都来自此前四小时内生成的内容。论文还把“只缓存大模型输出”与“大小模型输出都缓存”视为一个可调设计点：缓存所有图像会提高 hit rate 和吞吐，但会带来轻微的 FID 退化。

## 实验评估

实现上，MoDM 使用 Python 和 PyTorch，scheduler、monitor、worker 分别作为独立进程运行，节点之间通过 PyTorch RPC 通信。实验覆盖两类大模型 Stable Diffusion-3.5-Large 与 FLUX.1-dev，以及两类小模型 SDXL 和 SANA-1.6B。主要数据集是带真实时间局部性的 DiffusionDB，以及更像离线评测集、局部性较弱的 MJHQ-30k。

吞吐结果是论文最醒目的部分。在以 Stable Diffusion-3.5-Large 作为大模型基线时，MoDM 在 DiffusionDB 上的归一化吞吐达到 `2.5x`（配 SDXL）和 `3.2x`（配 SANA）；在 MJHQ 上，增益下降到 `2.1x` 和 `2.4x`，但仍然很可观。若把 FLUX 当作大模型基线，MoDM 依旧能达到 `2.4x-2.9x`，这说明它的收益并不局限于单一模型家族。

更有说服力的是 SLO 结果。在阈值设为“大模型推理延迟的 `2x`”时，vanilla serving 和 Nirvana 在 4 张 A40 上大约超过每分钟 5 个请求、或在 16 张 MI210 上超过每分钟 14 个请求后，就开始出现大量 SLO 违约；MoDM 在同样条件下可以分别撑到每分钟 10 个请求和 22 个请求。若把阈值放宽到 `4x`，MoDM 在 16 张 MI210 上还能继续支撑到每分钟 26 个请求。附录中的 p99 tail-latency 图也给出同样结论：随着负载升高，基线的 p99 很快超过 1000 秒，而 MoDM 在更宽的负载区间里都保持稳定。

质量部分则更细腻，也因此更可信。以 DiffusionDB 为例，MoDM-SDXL 的 CLIPScore 基本与大模型基线持平（`28.70` 对 `28.55`），同时 FID 明显优于直接运行 SDXL（`11.85` 对 `16.29`）。但它并没有完全追平大模型或 Nirvana 的 FID（分别是 `6.29` 和 `9.01`）。所以论文真正证明的是：MoDM 把质量-性能前沿往外推了，而不是让这个权衡彻底消失。能耗结果进一步强化了这个 serving 结论：相对 vanilla Stable Diffusion-3.5-Large，采用 SDXL 时节能 `46.7%`，采用 SANA 时节能 `66.3%`。

## 创新性与影响

和 _Agarwal et al. (NSDI '24)_ 相比，MoDM 最大的新意是把缓存对象从 latent 换成最终图像，于是缓存终于能够跨模型族复用，并自然接上“小模型做 refinement”的路径。和 _Ma et al. (CVPR '24)_ 这类通过中间特征缓存来加速 diffusion 的工作相比，MoDM 更像一篇完整的 serving systems 论文：它的贡献不只是采样更快，而是把检索、`k` 选择、GPU 在线分配和混合模型执行串成了一个服务栈。和 _Ahmad et al. (MLSys '25)_ 这类 query-aware model scaling 工作相比，MoDM 提供的是一种以缓存视觉上下文为中心的“小模型何时足够安全”的判据。

因此，这篇论文对两类读者都很有价值：一类是运营图像生成 API 的工程团队，另一类是关注多模型 AI serving 的系统研究者。它把 diffusion inference 从“固定模型优化”重新表述成了“动态资源管理”问题，这一点很有启发性。

## 局限性

MoDM 对时间局部性依赖很强。FIFO 缓存之所以有效，是因为 DiffusionDB 显示大多数可复用内容都出现在四小时窗口内；到了 MJHQ，这种局部性弱很多，收益也随之下降。系统还依赖针对具体模型组合做离线 profiling，并使用基于 CLIP 的经验阈值与 `k` 选择启发式，因此即便缓存格式本身是 model-agnostic 的，可移植性也远不是“开箱即用”。

质量仍然是一笔真实存在的账。MoDM 明显优于单独使用小模型，但它的 FID 仍然比大模型基线差，有时也不如 Nirvana。如果部署方更关心分布保真度而不是吞吐，这个差距就不能忽略。最后，论文没有单独量化动态切换模型、预热缓存以及维护 embedding 的运维成本；这些成本也许在实践中可以接受，但作者在实验里基本把它们当作背景开销处理，没有把它们作为一等瓶颈来分析。

## 相关工作

- _Agarwal et al. (NSDI '24)_ — Nirvana 用 latent caching 加速 diffusion serving，而 MoDM 直接改变了缓存对象，从而支持跨模型复用和小模型 refinement。
- _Ma et al. (CVPR '24)_ — DeepCache 在单一 diffusion model 内部复用中间特征；MoDM 则缓存最终图像，并围绕模型混用和请求路由构造完整 serving policy。
- _Lu et al. (ECCV '24)_ — RECON 通过检索 concept prompt trajectories 加速 text-to-image synthesis，而 MoDM 更关注生产级 serving，包括显式 cache management 与 SLO 感知的 GPU 分配。
- _Ahmad et al. (MLSys '25)_ — DiffServe 根据查询选择模型规模，而 MoDM 与之互补，它利用缓存下来的视觉上下文来判断何时可以安全地用更便宜的 refinement。

## 我的笔记

<!-- 留空；由人工补充 -->
