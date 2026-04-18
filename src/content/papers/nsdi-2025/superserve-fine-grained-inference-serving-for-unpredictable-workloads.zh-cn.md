---
title: "SuperServe: Fine-Grained Inference Serving for Unpredictable Workloads"
oneline: "SuperServe 把一个共享权重的 SuperNet 常驻显存，通过原地激活 SubNet 和基于 slack 的调度，在突发推理流量下动态交换精度与吞吐。"
authors:
  - "Alind Khare"
  - "Dhruv Garg"
  - "Sukrit Kalra"
  - "Snigdha Grandhi"
  - "Ion Stoica"
  - "Alexey Tumanov"
affiliations:
  - "Georgia Tech"
  - "UC Berkeley"
  - "Adobe"
conference: nsdi-2025
category: llm-and-ml-training-serving
tags:
  - ml-systems
  - scheduling
  - datacenter
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SuperServe 用一个常驻的、共享权重的 SuperNet 取代传统的模型切换，把“选模型”变成网络内部的原地 SubNet 激活。`SubNetAct` 能在 1 ms 以内切到指定深度/宽度配置，`SlackFit` 则根据最早截止请求的剩余 slack 在线决定精度档位和 batch size。两者结合后，系统在覆盖大范围精度-延迟点时可把显存成本降低最多 2.6x，并在 Azure 风格轨迹上做到同等 SLO attainment 下最多 4.67% 更高的平均精度，或同等精度下 2.85x 更高的 SLO attainment。

## 问题背景

这篇论文关注的是生产环境里的在线推理服务，而不是离线推理。目标场景中的请求到达率会在亚秒级剧烈波动，但请求本身又带着很紧的延迟目标，例如 10-100 ms 的 SLO。系统一方面要尽可能满足这些请求的 deadline，另一方面又希望在满足延迟的前提下返回更高精度的模型结果，同时还要节省 GPU 显存这种稀缺资源。

作者把现有方案概括为三难选择：延迟、精度、资源效率。较早的 serving 系统一般固定部署一个模型，因此在突发流量时要么直接违背 SLO，要么只能长期选择保守、低精度模型。更新的自动化系统允许在多个模型之间切换，但这又把问题转移到了模型加载延迟上。论文中的 Figure 1a 显示，把模型加载到 GPU 显存里的时间通常远大于一次推理时间，而且模型越大，这个差距越明显。作者在 Microsoft Azure Functions 轨迹上的模拟进一步表明，只要 actuation delay 有 100 ms，SLO miss 就可能比理想的 0 ms 策略高出 75x。

SuperNet 看起来像是解决办法，因为一个训练好的 SuperNet 本身就覆盖了很多 latency-accuracy 点。但 prior NAS 工作在 serving 阶段依然会把这些 SubNet 静态抽取成一个个独立模型。这样一来，系统还是只能在“两害相权”里做选择：要么把很多模型同时常驻在显存里浪费资源，要么按需换入换出，从而在流量尖峰时付出加载代价。论文真正针对的不是某个调度器不够聪明，而是把“模型选择”表示成“加载不同模型文件”这件事本身就错了。

## 核心洞察

论文最重要的洞察是：在推理服务里，模型选择应当被表示成一个已部署网络内部的控制流决策，而不是在多个独立模型二进制之间做切换。既然训练好的 SuperNet 已经包含了所有可选的 SubNet 结构，系统完全可以把整个 SuperNet 常驻下来，再根据每个请求当前需要的延迟-精度点，动态决定走哪些层、用多少通道或注意力头。

这个改写的价值在于，它把 actuation delay 从请求关键路径上基本拿掉了。只要“切换模型”退化成选择一个深度/宽度控制元组，而不再需要拷贝权重，调度器就可以依据队列的实时状态做反应，而不是押注未来流量。作者进一步指出，query slack 足以作为在线信号：当 slack 缩小时，系统应当切到更低延迟的 SubNet，并且通常配合更大的 batch；当 slack 充裕时，则应当机会主义地提升精度。之所以这套逻辑成立，是因为 pareto-optimal 的 SubNet 往往满足一个有用结构：较低精度的 SubNet 常能在接近的延迟预算内支撑更大的 batch，从而把吞吐换回来。

## 设计

核心机制是 `SubNetAct`。它会对一个训练好的 SuperNet 自动插入三类控制流算子。`LayerSelect` 决定哪些 block 被执行，相当于动态控制网络深度。对于 CNN SuperNet，它按 stage 选择深度；对于 transformer SuperNet，它采用论文中的 "every-other" 策略来选层。`WeightSlice` 则在层内部选择权重切片，例如卷积层前若干通道，或多头注意力中的前若干 heads，从而实现宽度缩放。这两个算子结合起来，就能用一个 `(D, W)` 控制元组来唯一指定要激活的 SubNet，并且整个过程都在同一个常驻 SuperNet 里原地完成。

第三个算子 `SubnetNorm` 用来解决卷积型 SuperNet 的一个准确性问题。如果不同 SubNet 直接共享同一份 BatchNorm 统计量，精度会明显下降，因为每个 SubNet 对应的均值和方差分布并不相同。因此 `SubnetNorm` 会为每个 SubNet、每个归一化层预先保存对应的统计量，而继续共享主干权重。论文指出，这部分非共享统计量的内存开销大约比共享层小 500x，因此它并没有破坏显存收益，却避免了精度坍塌。对于使用 LayerNorm 的 transformer SuperNet，则不存在同样的问题。

在 `SubNetAct` 之上，论文设计了在线调度策略 `SlackFit`。离线阶段，它先借助 NAS 结果把搜索空间限制到 pareto-optimal 的 SubNet 上，把候选集合从大约 10^19 个架构降到约 10^3 个。之后再对不同 `(SubNet, batch size)` 组合做 profiling，并按延迟划分为一系列 bucket。在线阶段，SuperServe 把请求放到全局 EDF 队列里；每当有 worker 空闲时，`SlackFit` 查看最早截止请求的剩余 slack，挑选一个“不超过该 slack 且最接近它”的延迟 bucket，形成对应 batch，并把它发给某个 worker。系统整体结构就是 router、scheduler 和 GPU worker；`SubNetAct` 的算子嵌入在 TorchScript IR 中，整套实现约 17.5k 行 C++，组件之间通过 gRPC 通信。

## 实验评估

机制层面的结果先证明 `SubNetAct` 的价值。与把若干独立 ResNet 或静态抽取出的 SubNet 分别部署相比，它在覆盖相近精度范围时可把显存占用降低最多 2.6x，同时还能暴露数百个更细粒度的运行点。更关键的是激活延迟几乎可以忽略。Figure 5b 给出的结果是 SubNet 激活低于 1 ms，而传统模型加载需要数百毫秒。正因为这一点，系统能在较窄的精度区间里把可持续吞吐范围扩展到大约 2,000-8,000 QPS。

端到端实验使用了一个在 ImageNet 上训练的 ResNet-based SuperNet 和一个在 MNLI 上训练的 transformer-based SuperNet，运行平台是 8 张 RTX2080Ti 和 24 个 CPU cores。真实工作负载来自 Microsoft Azure Functions trace，作者从中选取了 32,700 个 workload，并把原始 24 小时轨迹压缩到 120 秒。与 `Clipper+` 和 `INFaaS` 相比，SuperServe 在 CNN 场景下最有优势：它达到 0.99999 的 SLO attainment，在相同 SLO attainment 下精度高 4.65%，在相同平均 serving accuracy 下 SLO attainment 高 2.85x。对 transformer 工作负载，论文报告的是相同精度下 1.2x 更高的 SLO attainment，或相同 SLO attainment 下 1.72% 更高的精度。

合成轨迹进一步说明系统能处理更可控的 burstiness。对于不同平均到达率和不同 CV^2 的 bursty traces，SuperServe 始终保持大于 0.999 的 SLO attainment，并在 0.9999 SLO attainment 水平下比基线最多高 4.33% 的精度，或者在相同精度下把 SLO attainment 提高 2.06x。对于 arrival acceleration 更强的 time-varying traces，即使加速度达到 5,000 QPS^2，系统也还能维持 0.991-1.0 的 SLO attainment。微基准也值得注意：每 12 秒杀掉一个 worker 的故障实验中，系统仍可在容量降到 50% 时保持约 0.999 的 SLO attainment；扩展 worker 数量时，则能在 0.999 SLO attainment 下把吞吐提升到约 33,000 QPS。整体看，这些结果较好支撑了论文的中心论点，不过实验规模仍然局限在较小 GPU 集群和相对中等规模模型上。

## 创新性与影响

这篇论文的创新点不只是提出了一个新调度器，而是把 serving abstraction 本身改掉了。像 `INFaaS`、`Proteus` 这样的自动化 serving 系统，仍然在一组离散模型之间做选择，因此调度粒度和反应速度都会受到模型加载成本的约束。SuperServe 则把“模型切换”变成一个常驻 SuperNet 内部的快速控制动作，这才让真正 reactive 的在线决策变得可行。`SlackFit` 本身并不复杂，但它之所以有效，正是因为 `SubNetAct` 先把 actuation 代价降到了近乎零。

它最可能影响的是 ML systems 和 inference serving 社区中那些需要在同一任务上覆盖多个延迟-精度点的工作。论文没有去改进 SuperNet 的训练算法，而是补上了一个此前缺失的系统层拼图：怎样把 NAS 产出的 SuperNet 真正拿去承载突发在线推理。

## 局限性

这套方案依赖已经训练好的 SuperNet，以及离线 profiling 的稳定性。如果硬件环境发生显著变化，或者推理延迟分布发生漂移，`SlackFit` 依赖的 bucketization 就可能需要重新生成。论文也默认 worker 同构、推理延迟较可预测，而异构加速器支持只被当作未来工作简单提到。

实验范围也比论文动机显得更窄。评测主要是图像分类和文本分类的 SuperNet，运行在 8 张 RTX2080Ti 上，而不是更大规模集群或更重的生成式模型。故障实验展示的是通过切换到更低精度 SubNet 来做 graceful degradation，而不是一个完整的恢复协议。最后，`INFaaS` 的对比在目标函数上并不完全对齐：由于论文的请求模型没有逐请求 accuracy threshold，作者按“无约束”方式运行 `INFaaS`，这更能说明 SuperServe 在线优化精度的能力，而不完全是两个相同目标系统的正面对抗。

## 相关工作

- _Cai et al. (ICLR '20)_ - `Once-for-All` 训练一个 SuperNet 以覆盖多个部署点，而 `SuperServe` 关注的是运行时系统支持，使这些 SubNet 不必静态抽取就能在线激活。
- _Gujarati et al. (OSDI '20)_ - `Clockwork` 追求固定模型部署下的可预测 DNN serving，`SuperServe` 则关注在突发流量下动态切换不同 latency-accuracy 点。
- _Romero et al. (USENIX ATC '21)_ - `INFaaS` 在给定 accuracy constraint 时自动选模型，但仍然在离散模型之间切换；`SuperServe` 通过共享权重的原地 SubNet 激活绕开了加载延迟。
- _Ahmad et al. (ASPLOS '24)_ - `Proteus` 用每 30 秒一次的 MILP 做较粗粒度的 accuracy scaling，而 `SuperServe` 的目标是依靠近乎零成本的 actuation 实现亚秒级 reactive 控制。

## 我的笔记

<!-- 留空；由人工补充 -->
