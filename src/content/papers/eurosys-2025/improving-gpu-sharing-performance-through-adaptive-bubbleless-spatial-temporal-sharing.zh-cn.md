---
title: "Improving GPU Sharing Performance through Adaptive Bubbleless Spatial-Temporal Sharing"
oneline: "Bless 把 GPU 共享里的空泡当作可回收资源，用 kernel squad 调度和动态 MPS 上下文切换在不破坏配额保证的前提下降低多租户延迟。"
authors:
  - "Shulai Zhang"
  - "Quan Chen"
  - "Weihao Cui"
  - "Han Zhao"
  - "Chunyu Xue"
  - "Zhen Zheng"
  - "Wei Lin"
  - "Minyi Guo"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Microsoft"
  - "Alibaba Group"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696070"
tags:
  - gpu
  - scheduling
  - datacenter
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Bless 认为，多租户 GPU 共享做不好的根源，不只是配额切分不准，更是不同应用的 kernel 之间留下了大量没人接手的空泡。它把请求拆成短小的 kernel squad，在线估计哪种 spatial 或 spatial-temporal 配置能最快跑完，再通过预先建立的 MPS 上下文切换，让请求在不丢失配额保证的前提下吃掉空闲 SM。论文在 A100 上报告，相比已有方案，推理平均延迟可下降 21.1%-37.3%，而且不同配额下几乎不出现额外偏差。

## 问题背景

数据中心里越来越多 AI 服务并不需要独占整张 GPU，但现有共享办法各有硬伤。Temporal sharing 用时间片轮转，可 GPU kernel 既不可抢占、长度又很不均匀，于是应用很难精确拿到自己承诺的那部分设备时间。Spatial sharing 固定切出一部分 SM 给每个租户，预测性更好，可一旦某个租户的分区暂时没吃满，剩下的 SM 也只能闲着，形成空泡。至于完全不设限的共享，利用率看起来高，可多个应用的 kernel 自由交错后，单个请求的延迟既不好预测，也难以和配额对应起来。

论文用一个很直观的例子说明这个问题：VGG11 拿 1/3 GPU、ResNet50 拿 2/3 GPU，在同一张 A100 上处理并发请求时，同一个请求在 temporal sharing 下要 17.1 ms，在 spatial sharing 下是 11.5 ms；如果真能把空泡挤掉，延迟可以降到 10.1 ms，而且不会拖慢另一个应用。也就是说，目标并不只是提高 GPU 利用率，而是在维持每个应用隔离延迟目标的同时，把浪费掉的碎片时间重新拿回来。

## 核心洞察

Bless 最关键的判断是：配额不该通过固定分区来体现，而该通过请求进度来体现。运行时只要持续追踪每个请求离自己的隔离执行曲线还差多远，把落后最多的请求优先塞进下一轮 kernel squad，再为这一小撮 kernel 选一个最快的资源划分方式，就能一边守住配额目标，一边把别人暂时没用到的 SM 借过来。

这件事成立的前提，是并发 kernel 的行为虽然复杂，但还没有复杂到无法在线估计。Bless 不依赖重型硬件分析，也不要求改用户代码做 kernel preemption；它只需要离线测出 kernel 在不同 SM 预算下的持续时间，再根据这些数据快速判断当前 squad 是应该严格 spatial partition，还是应该让后半段 kernel 放开限制，去吃满整张卡上剩余的空闲资源。

## 设计

Bless 分成离线 profiling 和在线 runtime 两部分。profiling 阶段会测每个应用在配额 `n%` 下的隔离延迟、每个 kernel 在不同 SM 预算下的执行时间、请求执行到各个 kernel 时的累计进度，以及 kernel 的峰值 SM 占用。对 A100，论文把搜索空间压到 18 个分区，平均 profiling 只要 1.9 秒，但要求 profiling 所用 GPU 和线上部署是同型号。

在线阶段里，每个应用有自己的 FIFO 队列，而且同一时刻最多只让每个应用有一个活跃请求。multi-task scheduler 会同时维护每个请求的真实进度和期望进度，然后反复从相对最落后的那个请求里挑 kernel，直到凑满一个有上限的 kernel squad，或者碰到请求边界。这样一来，某个请求如果这一轮因为干扰落后，下一轮就会自动拿到更多调度份额。

接下来，execution configuration determiner 会在一个不算大的候选集合里搜索：完全不做 spatial restriction、严格做 spatial split，以及一种折中方案，也就是只对每个请求前半段 kernel 做限制，后半段放开。论文给了两个快速估计器来支撑这个搜索：严格隔离时用 interference-free predictor，平均误差 6.7%；允许重叠时用 workload-equivalence predictor，平均误差 7.1%。在 2,260 组 kernel squad 上，预测出的最优配置有 96.2% 和真实最优一致。

真正执行时，Bless 依赖 Nvidia MPS。系统先用 `cuCtxCreate_v3` 建好多组 SM affinity 不同的上下文，让请求前段 kernel 先在受限上下文里跑，等这部分结束后，再把后段 kernel 切到不受限上下文里，让它们去争用剩余空闲 SM。论文把这种做法称为 adaptive bubbleless spatial-temporal sharing。整套系统实现大约 5,000 行 C++，前端接口是 gRPC。

## 实验评估

实验平台是一台带 Nvidia A100、108 个 SM、40 GB 显存的服务器，CPU 是 AMD EPYC 7302。工作负载覆盖 VGG11、ResNet50、ResNet101、NasNet 和 BERT 的推理与训练，kernel 持续时间从 3 us 到 3 ms 不等。对比对象包括 Temporal sharing、MIG、GSlice、Unbound sharing，推理场景还加上 Reef+，训练场景则和 Zico 比较。公平性基线是 ISO，也就是应用在自己配额下用 MPS 独占运行时的延迟。

总体结果基本支撑论文主张。推理场景下，Bless 相比 Temporal、MIG、GSlice、Unbound 和 Reef+，平均延迟分别下降 37.3%、34.2%、21.1%、16.5% 和 13.5%。训练场景里，相比 Temporal、MIG、Unbound 和 Zico，epoch 延迟分别下降 26.5%、7.5%、12.5% 和 9.9%。收益在中低负载时更明显，因为这时候空泡多、可回收空间大；如果请求一直把 GPU 打满，Bless 和 GSlice 的差距就缩到 3% 以内，这和论文的基本前提是一致的。

Bless 在配额保证上也更扎实。九组不均匀配额的双应用部署里，它相对 ISO 的平均延迟偏差只有 0.6 ms，而 Temporal 是 14.3 ms，GSlice 是 2.1 ms。放到真实 trace 上看，在 Twitter trace 中，Bless 在均分配额时相对 Temporal、MIG 和 GSlice 分别降了 18.4%、20.5% 和 7.3%；在 1/3-2/3 配额下，相对 GSlice 再降 14%，而且没有额外偏离 ISO。换成 Azure serverless trace，这三个降幅分别是 49.3%、41.2% 和 32.1%。即便直接拿 QoS 指标压它，Bless 的平均违约率也只有 0.6%，Unbound 和 GSlice 分别达到 38.8% 和 50.1%。

## 创新性与影响

和 Bless 最接近的前作，各自只解决了问题的一部分。GSlice 做到了受控的 spatial partition，却无法把分区内部闲下来的 SM 再让出来。Reef 能给优先级更高的推理任务做精细控制，但它本质上是偏置式共享，代价由共置任务承担。Orion 对 interference 的刻画更细，不过 Bless 进一步把空泡本身变成了调度对象。它真正新的地方，是把基于进度的公平调度、轻量级在线配置搜索，以及基于 MPS 的上下文切换拼成了一个完整系统，把原本静态的 spatial sharing 变成了可自适应的 spatial-temporal sharing。

这使得它对两类读者都有价值。对数据中心运营者来说，论文给出了一种不必在利用率和可预测性之间二选一的共享路径。对后续 GPU 多租户研究来说，kernel squad 也是一个很有用的抽象，因为公平、预测和资源重配置终于能在同一个调度单位上汇合。

## 局限性

Bless 不是任意 GPU 工作负载都能直接套上的调度器。它假设应用是 stationary 的，计算 DAG 足够稳定，还要求事先在同型号 GPU 上做离线 profiling。部署阶段它甚至会主动避免把 kernel 极短的应用和 kernel 极长的应用放在一起，因为前者容易在每一轮 squad 里持续吃亏。像 autoregressive LLM serving 这类动态应用，如果要套 Bless，就得换一套进度模型，或者接受更重的 profiling 成本。

这套机制也有明确代价。每个 MPS 上下文大约要吃掉 230 MB 显存，kernel squad 切换大约 20 us，上下文切换还会引入 50 us 左右的空窗，而且 Bless 只管 SM，不管寄存器或 shared memory。更细一点看，在极端偏置负载下，它因为要等当前 squad 自然结束，会让那个低负载、高配额租户的延迟多涨约 9%；不过换来的结果是，忙碌租户的吞吐能比 GSlice 高 2.2x。

## 相关工作

- _Dhakal et al. (SoCC '20)_ - GSlice 为推理任务做自适应 spatial partition，而 Bless 进一步允许请求执行到一半时重配资源，把分区里闲着的 SM 收回来。
- _Han et al. (OSDI '22)_ - Reef 依赖微秒级 preemption 和受控并发去照顾高优先级推理任务；Bless 则面向无偏置的配额共享，不把收益建立在牺牲共置任务之上。
- _Strati et al. (EuroSys '24)_ - Orion 重点分析细粒度 GPU sharing 里的 interference，而 Bless 在此基础上增加了 kernel squad 调度和在线 spatial-temporal 配置搜索。
- _Lim et al. (ATC '21)_ - Zico 通过重叠训练 iteration 来提升共享效率并节省内存，Bless 则把调度粒度下探到 kernel，并直接按应用进度对齐配额目标。

## 我的笔记

<!-- 留空；由人工补充 -->
