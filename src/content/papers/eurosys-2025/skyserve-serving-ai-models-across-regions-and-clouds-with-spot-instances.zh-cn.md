---
title: "SkyServe: Serving AI Models across Regions and Clouds with Spot Instances"
oneline: "SkyServe 把 spot GPU 从不敢用变成能上线：副本跨区域跨云分散放置，用少量额外 spot 做缓冲，只有在 spot 真空时才临时补 on-demand。"
authors:
  - "Ziming Mao"
  - "Tian Xia"
  - "Zhanghao Wu"
  - "Wei-Lin Chiang"
  - "Tyler Griggs"
  - "Romil Bhardwaj"
  - "Zongheng Yang"
  - "Scott Shenker"
  - "Ion Stoica"
affiliations:
  - "UC Berkeley"
  - "ICSI"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3717459"
code_url: "https://github.com/skypilot-org/skypilot"
tags:
  - llm-inference
  - datacenter
  - gpu
  - fault-tolerance
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的判断很直接：spot GPU 不是天生不适合做 AI serving，真正有问题的是大家把它当成单区域里的廉价补充资源来用。SkyServe 提出的 `SpotHedge` 会把副本分散到不同 region 和 cloud，用少量额外的 spot 副本顶住预emption窗口，再在 spot 真的拿不到时短暂拉起 on-demand。结果是，在真实云上和重放 trace 里，它都能把成本压到接近纯 spot 的一侧，同时把可用性和延迟拉回到可上线的水平。

## 问题背景

AI 模型服务的成本高，原因并不神秘：GPU 很贵，而流量又有突发性，所以运维方往往被迫为了峰值提前备很多副本。Spot instance 看起来像天然解法，论文里给出的价格范围是 on-demand 的 8%-50%。问题在于，GPU 的 spot 市场和大家熟悉的 CPU spot 市场不是一回事。

作者把现有方案失灵的原因拆成三层。第一，单一区域里的 spot GPU 经常不是被抢占，而是根本拿不到。论文分析的一条 AWS trace 里，某个 region 跨所有 zone 都拿不到 spot GPU 的时间占 33.1%。第二，抢占在同一区域里具有明显相关性，多个 zone 会在很短时间内一起掉容量，所以把副本均匀铺在同一区域的几个 zone 里，并不能真正隔离风险。第三，大模型副本的冷启动时间太长，抢占告警救不了场。作者实测，在预装镜像的情况下，拉起实例并把 Llama-2-7B 的 vLLM endpoint 部署好也要 183 秒，已经超过 AWS 的 2 分钟告警，更别说 GCP 和 Azure 只有几十秒。

于是，老办法两头不讨好。纯 spot 部署在抢占或缺货时会直接掉服务能力。静态 spot/on-demand 混部虽然听起来稳一点，但在 spot 健康时要一直养着贵得多的 on-demand 副本，在 spot 不健康时又未必补得回来。论文真正要证明的是，spot GPU serving 能否成立，取决于 placement、缓冲和 fallback 能不能被统一设计。

## 核心洞察

作者最关键的洞察是：应该优先用廉价的 spot 多样性去对冲风险，再用昂贵的 on-demand 做兜底，而不是反过来。一旦副本分散到更宽的 failure domain，抢占相关性会下降，可搜索的替代容量也会一下子变大。此时只要额外保留少量 spot 副本作为缓冲，大多数抢占都能在冷启动期间被吃掉；on-demand 不必常驻，只需在 spot 突然变得不可得时临时补位。

所以问题不该表述成「固定保留多少 on-demand 比例」，而应该表述成三个在线决策：当前需要多少 ready replicas、要多配多少额外 spot 副本来吸收抢占、这些副本现在该放在哪些 zone、region 和 cloud。换句话说，这篇论文把资源配比问题改写成了 failure-domain-aware 的控制问题。

## 设计

`SpotHedge` 由两个互相咬合的机制组成。第一个是 dynamic placement。系统把可用 zone 分成两组：当前可投放的 `ZA` 和近期高风险的 `ZP`。某个 zone 一旦发生副本被抢占，就暂时从 `ZA` 挪到 `ZP`；如果后来又能在该 zone 成功拉起并准备好副本，就把它移回 `ZA`。后续新 spot 副本优先从 `ZA` 里选，策略上会兼顾更低成本，并尽量避免继续把副本堆到已经放了很多实例的 zone。若 `ZA` 里剩下不到两个 zone，系统会把 `ZP` 中的 zone 重新放回候选集合，避免整套服务被迫蜷缩到单个 zone 上。

第二个机制是 dynamic fallback。设 autoscaler 给出的目标 ready 副本数为 `N_tar(t)`，额外的 spot 缓冲数为 `N_extra(t)`。SkyServe 会尽量维持 `N_tar + N_extra` 个 spot 副本处于运行或拉起过程中。若 spot 副本被抢占，系统就临时补 on-demand 副本来覆盖丢失的 ready capacity，同时继续尝试把缺掉的 spot 补回来。等 spot 副本重新 ready 之后，多出来的 on-demand 会被回收。这样得到的不是静态的混部比例，而是会随 spot 市场状态变化的动态组合。

系统实现上，SkyServe 包含 service controller、autoscaler 和 load balancer。Controller 负责实例生命周期、readiness probe 与回收；autoscaler 根据负载推导 `N_tar`；load balancer 只把请求发给 ready 副本。重要的是，它并不改写 vLLM、TGI、Triton 这类 inference engine，而是包在这些现有引擎外围做副本级调度与运维控制。

## 实验评估

实验分成两部分。第一部分是真实云上的端到端实验，合计运行约 22 小时、处理 133k 个请求、总花费约 4.1k 美元。主要配置是在 8 张 A10G 的 `g5.48xlarge` 上用 vLLM 提供 Llama-2-70B 服务；另一组则在 4 张 T4 上跑带 SpotServe 的 OPT-6.7B。工作负载来自 Chatbot Arena trace，因此既有突发流量，也有长短不一的生成请求。

最重要的结果是，SkyServe 不是单纯把价格做低，而是在低成本下保住了服务质量。相较研究系统和生产风格 baseline，论文报告 P50、P90、P99 延迟平均降低 2.3x、2.1x、2.1x；与纯 on-demand 部署相比，平均成本下降 43%。在 Llama-2-70B 的端到端实验中，SkyServe 的请求失败率维持在 0.34%-0.62%，而 ASG 在 spot 波动时达到 36%，AWSSpot 达到 49%-94%，MArk 达到 6.8%-79%。作者也明确指出，一些 baseline 在某些时段看起来更便宜，并不是策略更好，而是因为它们压根没有维持足够的 ready replicas。

第二部分是基于 AWS/GCP 真实 spot trace 的重放实验，这部分更清楚地说明了机制本身。SpotHedge 在多组 trace 上做到 99%-100% availability，相对 Even Spread 平均延迟降低 1.1-3.0x，相对 Round Robin 降低 1.0-1.8x；成本则约为纯 on-demand 的 42%-55%，同时与带未来信息的 Omniscient offline optimal 只差 5%-20% 的相对成本。这个结果基本把论文主张钉实了：真正起作用的是跨 failure domain 放置、副本级的少量 spot 缓冲，以及按需出现的 on-demand fallback。

## 创新性与影响

这篇论文的创新点不在于重新造一个 inference engine，也不只是又写了一个 autoscaler。它的贡献是把 spot GPU serving 里原本分散讨论的三个难题放到同一个控制面里处理：抢占相关性、长冷启动，以及 spot/on-demand 的动态混合。和 SpotServe 这类专注于副本内部并行策略的工作相比，SkyServe 处理的是更外层的 provisioning 与 placement 问题。

这会让两类人都受益。对系统研究者来说，论文给出了一条更可信的论证路径：spot GPU 不是不能用，而是必须扩大 failure domain 并把 fallback 变成动态机制。对工程实践者来说，它也足够落地，因为 SkyServe 并不要求改模型内核或推理框架，更多是在现有 serving stack 上面补上多区域、多云和动态兜底这一层。

## 局限性

论文最有说服力的结果建立在一个前提上：模型推理时间以秒计，因此跨区域 RTT 相对较小。若应用对 TTFT 极其敏感，或者强依赖本地 region 的极低交互时延，那么把请求发往远端 region 的代价可能会比论文里显得更重。作者承认这一点，但没有做更系统的量化评估。

此外，`SpotHedge` 终究是启发式策略，不是在线最优控制。像 `N_extra` 该设多少、何时把 `ZP` 重新并回候选集合、autoscaling 窗口多长，这些都主要来自经验和测量。最后，论文虽然覆盖了真实云实验，但范围仍有限：云厂商和 region 数量不算多，模型配置只有两组，并且隐含依赖一个重要假设，即跨区域的 on-demand GPU 仍然买得到。若 fallback 本身也缺货，论文没有进一步给出更强的解决办法。

## 相关工作

- _Miao et al. (arXiv '23)_ - SpotServe 解决的是副本内部模型并行如何承受抢占，SkyServe 则解决副本应该放在哪里，以及 spot 和 on-demand 应该怎样动态组合。
- _Zhang et al. (ATC '19)_ - MArk 研究的是 spot/on-demand 混部的推理服务，但它依赖更接近 CPU 场景的假设；SkyServe 说明这些假设放到 GPU serving 上会失效。
- _Yang et al. (ASPLOS '23)_ - Snape 借助云内部可见性的 spot obtainability 信号做推理服务优化，而 SpotHedge 更强调不依赖 provider 内部信息的在线放置与 fallback。
- _Harlap et al. (ATC '18)_ - Tributary 面向有延迟 SLO 的弹性服务使用 spot 资源，SkyServe 则把重点放在 GPU 大模型副本的长冷启动和跨 failure domain 的相关抢占。

## 我的笔记

<!-- 留空；由人工补充 -->
