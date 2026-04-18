---
title: "HEPIC: Private Inference over Homomorphic Encryption with Client Intervention"
oneline: "HEPIC 只把 HE 的密文管理交给客户端，并用流水化与选择性干预把这种交互做得比 fire-and-forget HE 和混合 MPC 更快。"
authors:
  - "Kevin Nam"
  - "Youyeon Joo"
  - "Seungjin Ha"
  - "Hyungon Moon"
  - "Yunheung Paek"
affiliations:
  - "Dept. of ECE & ISRC, Seoul National University, Seoul, Republic of Korea"
  - "Ulsan National Institute of Science and Technology, Ulsan, Republic of Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790170"
tags:
  - security
  - ml-systems
  - scheduling
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

HEPIC 的核心主张是：同态加密上的私有推理不必死守 fire-and-forget。它只让客户端参与密文管理，比如 refresh、scheme switching、parameter switching 和数据重排，同时把真正的推理主体仍然留在密文域里完成。关键贡献是把这种干预做成可选择、可流水、可调度，因此交互的收益大于交互的代价。

## 问题背景

论文瞄准的是两类主流私有推理方案之间的空档。纯 HE 的 fire-and-forget 系统在客户端提交加密输入后就不再需要参与，但代价是服务器必须独自承担所有昂贵的密文管理步骤：bootstrapping、scheme conversion、parameter conversion，以及加密域里的 rotation。像 LOHEN 这样的系统虽然通过分层切换改善了精度与性能的平衡，但复杂度本质上仍然压在服务器端，因此要付出更大的参数、更高的计算量和更重的内存压力。

MPC 型系统则走向另一端。它们本来就让客户端和服务器共同参与推理，因此可以用更轻量的密码学子协议替代一部分昂贵的 HE 内核。但论文认为，这条路在真实部署里同样有明显问题：客户端预处理存储很大，通信延迟很重，而且客户端与服务器算力不对称、协议依赖严格，导致大量 stall。真正的问题因此变成：能不能保留 HE 推理的精度优势，同时只引入最有价值的那部分交互？

## 核心洞察

最关键的洞察是，密文管理是一个非常适合拿来做客户端干预的边界，因为这些操作无论放在客户端还是服务器上，语义都是相同的。这样一来，HEPIC 就可以只把这部分工作挪到客户端，而不必重写整套推理算法。和 MPC 那种“协议要求你必须互动”不同，这里的交互是 programmable 的：开发者可以决定在哪些位置介入、介入多频繁，从而在服务器计算、通信开销和密文参数之间主动权衡。

这个观察和更小的 HE 参数结合起来后才真正有力量。只要服务器不再需要每次都本地完成 refresh，它就可以使用更小的密文，从而降低单次操作成本，并释放更多 ciphertext-level parallelism。难点在于，朴素地引入交互会重新制造 MPC 式的停顿。因此，HEPIC 真正重要的命题不是“让客户端协助”，而是“让这种协助细到 polynomial 粒度、适合流式传输、而且只在值得的时候发生”，这样它就能和服务器计算重叠，而不是把系统重新串行化。

## 设计

HEPIC 保留了标准流程：客户端加密输入，服务器执行网络，最终结果仍然只有客户端能解密。算术层使用受 Cheetah 启发的 coefficient encoding，非算术层使用 BFV-PBS。真正的新动作是，某些中间密文会被送回客户端做基于重新加密的管理：用客户端 refresh 替代服务器侧 bootstrapping，用 decrypt-and-re-encrypt 完成 scheme 或 parameter switching，并通过明文域重排来替代加密域 rotation。服务器在发送这些中间值前会先加上 additive one-time-pad noise，这和已有 hybrid PI 的半诚实安全做法一致。

这套设计能跑起来，关键在于 overlap。当一个密文马上要发往客户端时，HEPIC 会省掉 relinearization，因为它在重新加密前不会再参与下一次乘法。这样系统就能以 polynomial 粒度做流水线：客户端可以更早开始处理，服务器也能更早消费返回数据。更小的参数还带来更多密文实例，因此不同操作之间也能并行重叠。论文再配合 streaming transfer，避免每次往返都重新停下来。

为了让这套方案在现实机器上稳定工作，论文又加了两个调度器。Cache-Aware Task Allocator（CATA）优先选择最粗、但又放得进 cache 的并行粒度；如果整密文并行会把 cache 撑爆，它才退回到 polynomial、RNS-limb 或 coefficient 级别。Cost-Aware Client Intervention Scheduler（CACIS）则在不同的 `N` 和额外参数 `d` 上搜索，其中 `d` 表示两次客户端干预之间允许服务器自己做多少次 bootstrapping；它的目标是最小化客户端计算、服务器计算和通信三者中的最大值。

## 实验评估

实验平台故意设置成不对称：客户端是一台 Intel Atom 平板，服务器则分别使用 Xeon Gold CPU 和 NVIDIA A6000 GPU。工作负载覆盖 CIFAR-10 与 ImageNet 上的六个 CNN，每个模型用 1,000 个验证集查询取平均。对比对象包括最强的 HE 基线 LOHEN、单方案 HE 基线 NeuJeans 与 SHE，以及作者自己把 Swift、Cryptonite 和 Cheetah 的优化揉合出来的 `Hybrid+`。更重要的是，论文把所有系统都对齐到大约 40-bit precision 和相同的安全目标，因此比较相对公平。

总体结果很强：HEPIC 的端到端延迟相对 LOHEN 提升 `2.20x-41.93x`，相对 `Hybrid+` 提升 `1.09x-10.42x`，而准确率与未加密模型相比的损失仍然控制在 `0.1` 个百分点以内。对论文论点最关键的是 WAN 结果。`Hybrid+` 从 LAN 切到 WAN 后平均慢了 `2.03x`，而 HEPIC 只慢了 `1.20x`，这直接支持了作者关于 streaming 和 selective intervention 能减轻交互代价的主张。服务器更强时也是类似故事：HEPIC 仍然能从 CPU 到 GPU 获得平均 `3.70x` 的收益，说明 CACIS 会主动重新平衡任务分配。

内存结果同样支持论文论点。在最重的 `IMO` 工作负载上，`Hybrid+` 的峰值内存达到客户端 `128GB`、服务器 `412GB`；LOHEN 是 `26.4MB` 和 `52.8MB`；HEPIC 则是客户端 `13.6MB`、服务器 `23.2-47.8MB`。ablation 也和设计目标对得上：CATA 在受限 cache 下带来 `2.12x-3.34x` 提升，而 CACIS 相比“非选择性地到处干预”又额外带来 CPU 上 `1.07x`、GPU 上 `3.28x` 的提升。

## 创新性与影响

相对 _Nam et al. (USENIX Security '25)_，HEPIC 的创新不是再做一轮更好的分层参数配置，而是直接打破了 fire-and-forget 这个默认前提，同时又保持整体计算仍然是 HE-based。相对 _Huang et al. (USENIX Security '22)_ 和 _Fu et al. (TIFS '25)_，它没有全面拥抱 HE/MPC 混合执行，而是只挑出那个“语义上可以无痛移动”的密文管理边界。相对 _Garimella et al. (ASPLOS '23)_，它认真接受了真实客户端/服务器不对称这个批评，但给出的答案不是更重的 MPC 工程，而是选择性干预与调度。

因此，这篇论文的重要性在于开辟了第三个设计点：它位于被动的 HE 与高度交互的 MPC 之间，把交互变成可选、可调、只在值得的时候使用的资源。

## 局限性

这篇论文仍然工作在 semi-honest 模型下，并继承了以往 hybrid PI 里“用 mask 保护中间值”的假设，因此它并没有解决 malicious client 或 malicious server 场景。实验对象也全部是 CNN 推理；论文虽然认为该设计可以推广到其他神经网络，但并没有用 transformer 或 RNN 做实证。

此外，论文强调的 programmable 也不是零成本。CACIS 依赖对客户端、服务器和网络延迟的较准确建模，而这些模型显然和具体 backend 强相关。系统还默认客户端在推理期间保持在线，并且能持续跟上选择性重加密与流式传输。最后，如果未来 FHE accelerator 真把服务器侧 bootstrapping 大幅做便宜，这个平衡点可能会变化。

## 相关工作

- _Nam et al. (USENIX Security '25)_ — LOHEN 在 fire-and-forget HE 推理里优化分层 scheme 与 parameter switching，而 HEPIC 进一步追问这些密文管理步骤是否根本不该全部留在服务器端。
- _Huang et al. (USENIX Security '22)_ — Cheetah 为两方私有推理提供高效的算术 building block；HEPIC 借用了 coefficient encoding 的思路，但没有把整套设计变成 MPC 风格的全面交互。
- _Garimella et al. (ASPLOS '23)_ — Cryptonite 重点揭示了 hybrid PI 在真实客户端/服务器不对称下的内存与通信问题；HEPIC 则从 HE 这边回应同一个部署痛点。
- _Fu et al. (TIFS '25)_ — Swift 通过优化算术层和非算术层协议来加速 hybrid PI，而 HEPIC 试图尽量保住 HE 执行路径的简洁性，只引入它能明确论证合理的那部分交互。

## 我的笔记

<!-- 留空；由人工补充 -->
