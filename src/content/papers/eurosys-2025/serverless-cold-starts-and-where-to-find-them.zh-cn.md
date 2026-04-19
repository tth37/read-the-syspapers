---
title: "Serverless Cold Starts and Where to Find Them"
oneline: "这篇五区域生产跟踪表明，serverless 冷启动并不是单一延迟，而是 trigger 模式、资源池、runtime 与区域瓶颈错配后的结果。"
authors:
  - "Artjom Joosen"
  - "Ahmed Hassan"
  - "Martin Asenov"
  - "Rajkarn Singh"
  - "Luke Darlow"
  - "Jianfeng Wang"
  - "Qiwen Deng"
  - "Adam Barker"
affiliations:
  - "Central Software Institute, Huawei"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3696073"
project_url: "https://github.com/sir-lab/data-release"
tags:
  - serverless
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这不是一篇提出新 runtime 或新 scheduler 的论文，而是一份 provider 视角的冷启动体检报告。作者基于 Huawei YuanRong 在五个 region、31 天里的真实轨迹说明：冷启动没有统一主因，pod allocation、code deployment、dependency deployment 和 scheduling 哪个最慢，会随着 region、trigger、runtime 与资源规格而变化；再把「pod utility ratio」算进去，很多冷启动的代价看起来也和直觉不一样。

## 问题背景

大家都知道 serverless 有冷启动，但公开证据其实很薄。provider 往往只放出汇总统计，外部黑盒测量又只能看到总时延，看不到到底慢在 pod allocation、调度、依赖下载，还是 keep-alive 策略本身。这样一来，研究者虽然知道冷启动值得优化，却不知道应该优先打哪一层。

这在公有云里尤其麻烦，因为平台不是一个均匀的大池子。不同 region 的请求密度、runtime 组合、峰值形状、资源配置都不一样。同样是一分钟 keep-alive，对某些函数是合理缓存，对另一些函数则几乎等于白白养一个马上会被删掉的 pod。论文因此换了一个更贴近运营的问题来问：真实流量下，究竟哪些函数最容易制造冷启动，冷启动里哪一段最慢，以及这些启动成本到底有没有被后续请求摊薄。

## 核心洞察

论文最重要的判断是：冷启动不是一种统一的延迟税，而是多类错配叠在一起的结果。低频 timer 函数之所以反复冷启动，常常只是因为触发周期刚好落在一分钟 keep-alive 之外；高请求函数之所以也会冷启动，则往往是因为流量抖动逼着系统扩容，进而把 scheduling 或资源池分配压成瓶颈。两者表面上都叫冷启动，成因却完全不同。

进一步说，长冷启动也不一定比短冷启动更糟。如果一个启动很慢的 pod 后面长期留在系统里、连续处理了很多请求，那它的代价其实可能被摊薄得更好。于是作者不再把 cold start time 当成唯一指标，而是把它拆成 pod allocation、code deployment、dependency deployment、scheduling 四段，再引入「pod utility ratio」来衡量启动后的有效利用时间是否值回票价。

## 设计

这篇论文的「设计」本质上是测量设计。作者使用 YuanRong 平台 31 天的三路遥测数据：request 级记录、pod 级 cold-start 记录，以及 function 元数据。整份 trace 覆盖五个 region、20 个 cluster，总计 850 亿次请求、超过 1200 万个 pod，以及 1190 万次冷启动。对每次冷启动，系统都会记录总时长，以及 pod allocation、code deployment、dependency deployment、scheduling 四个组成部分。

分析先从 region 级别展开，再在 Region 2 上细拆 trigger type、runtime 和 CPU-memory 配置。这样做的价值在于，它把宏观现象和微观路径连起来了：一边看多 region 的峰值错位、节假日效应和流量周期，一边看启动路径内部到底是哪一段拖后腿。作者还给所有 region 的 cold-start time 拟合了 LogNormal 分布，给 cold-start inter-arrival time 拟合了 Weibull 分布，方便后续系统论文做更像真的模拟。

另外两个选择也很关键。第一，论文把 multi-region 差异当作主角而不是噪声，因为不同 region 的 peak hour、每函数请求强度、主导瓶颈本来就不一样。第二，它定义了「pod utility ratio」：用 pod 的有效生命周期除以 cold-start time，其中有效生命周期会先扣掉默认的一分钟 keep-alive。这个指标直接回答了一个更实际的问题：这个慢启动的 pod，后来到底值不值得。

## 实验评估

最扎实的结论是异质性。五个 region 的 median cold-start time 从大约 0.1 秒到 2 秒不等，而且每个 region 都有明显长尾。Region 1 的 cold start 最长能到 7 秒，Region 2 最长到 3 秒。更关键的是，主导组件并不相同：Region 1 主要被 dependency deployment 和 scheduling 拖慢，Region 2 则主要慢在 pod allocation。所有 region 里，cold-start time 都与冷启动次数正相关；节假日后的第一个工作日还会出现明显的「补课式」反弹，冷启动数量和时长一起上升。

Region 2 的拆分把这些统计变成了可执行建议。timer 函数占了将近 60% 的函数数、30% 的冷启动数，却只占 5% 的 running pods，这说明很多 timer 函数几乎每次触发都要冷启动，但启动完后又很快失去价值。Python3 贡献了将近 50% 的冷启动。小规格 CPU-memory 配置贡献了 60% 以上的冷启动次数，但一旦换成大规格资源池，启动就会更慢：不同 region 里，大池子的 median cold-start time 大约是小池子的 1 倍到 5 倍，主要差在 pod 搜索、代码部署和依赖部署。

runtime 和 trigger 的影响也不是一回事。在 Region 2 里，大多数 runtime 的 median 都低于 1 秒，只是带着长尾；真正的离群点是 Custom 和 HTTP，中位数都超过 10 秒。对 Custom 来说，主因几乎就是 pod allocation，因为平台不会为它保留现成资源池。OBS trigger 的冷启动也很慢，但论文没有把锅简单甩给 OBS，因为它和 Custom runtime 高度缠在一起。最后，「pod utility ratio」改写了代价判断：20% 的 pod 该比值低于 1，而中位数大约是 4:1，说明有些看起来不算长的冷启动，实际上非常不划算。

就测量论文而言，这份评估是有说服力的。它不只是报端到端延迟，而是拿到了组件级时间，并且横跨多 region 和长时间窗口。它的弱点不在描述能力，而在因果能力：它很擅长指出慢在哪一段，却未必总能把那一段再唯一归因到某个系统设计选择上。

## 创新性与影响

这篇论文的创新点不在于发明新机制，而在于把冷启动问题重新拆开。过去很多工作讨论 cold start 时，默认它是一个统一现象；这篇论文则从 provider 内部视角证明，region、trigger、runtime、资源大小都会改变主导瓶颈，而且冷启动成本还应该结合「pod utility ratio」来看，而不是只盯着一次启动花了多少秒。

这种重构很有影响力，因为它直接改变优化方向。论文给出的启发不是某个单点技巧，而是一组更细粒度的策略：按 region 做 load balancing，按 trigger 调 keep-alive，按资源配置预测 resource pool，按 workflow 调用链去做预热。哪怕读者根本不用 YuanRong，这套分析框架也足以提醒人们，冷启动优化首先要找准主导组件和主导 workload。

## 局限性

归根结底，这还是一篇来自单一 provider、单一平台的观察性研究。数据只有 31 天，覆盖的是五个 region，而不是 Huawei 的全部部署。更细的 trigger、runtime、资源配置分析主要集中在 Region 2，没有在所有 region 上完整复刻，所以文中的占比不应被当成所有公有云的通用常数。

另外，一些解释天然带着混杂因素。论文自己就指出，OBS 的慢冷启动和 Custom runtime 高度相关，因此不能把 trigger type 当成干净的因果变量。更普遍地说，provider telemetry 很擅长把慢点定位到启动路径中的某一段，却不总能进一步证明那一段的唯一根因。更合理的读法，是把它视为一篇质量很高的测量论文：它显著缩小了优化搜索空间，但没有替代后续机制论文。

## 相关工作

- _Wang et al. (USENIX ATC '18)_ - _Peeking Behind the Curtains_ 从用户侧黑盒测量 serverless 冷启动；这篇论文补上了 provider 内部的组件级拆解。
- _Shahrad et al. (USENIX ATC '20)_ - _Serverless in the Wild_ 更偏 provider 工作负载总览，而这篇论文把焦点收紧到多 region 冷启动成因。
- _Oakes et al. (USENIX ATC '18)_ - _SOCK_ 直接优化 serverless provisioning；这篇论文则说明生产环境里 provisioning 到底慢在哪些环节。
- _Joosen et al. (SoCC '23)_ - _How Does It Function?_ 讨论长期 serverless 负载趋势；这篇论文进一步下钻到 cold start，并引入更细的事件级遥测。

## 我的笔记

<!-- 留空；由人工补充 -->
