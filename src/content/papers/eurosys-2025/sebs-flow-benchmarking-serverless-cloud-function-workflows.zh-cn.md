---
title: "SeBS-Flow: Benchmarking Serverless Cloud Function Workflows"
oneline: "SeBS-Flow 用一套可移植工作流定义同时落到 AWS、GCP 和 Azure，把 serverless workflow 的差异拆成编排、数据传输与冷启动三部分。"
authors:
  - "Larissa Schmid"
  - "Marcin Copik"
  - "Alexandru Calotoiu"
  - "Laurin Brandner"
  - "Anne Koziolek"
  - "Torsten Hoefler"
affiliations:
  - "Karlsruhe Institute of Technology, Germany"
  - "ETH Zurich, Switzerland"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3717465"
code_url: "https://github.com/spcl/serverless-benchmarks"
project_url: "https://github.com/spcl/sebs-flow-artifact"
tags:
  - serverless
  - datacenter
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SeBS-Flow 讨论的不是单个函数 benchmark，而是完整的 serverless workflow。它把 workflow net 加上数据传输标注，形成一套可移植定义，再自动转写成 AWS Step Functions、Google Cloud Workflows 和 Azure Durable Functions 的实现。基于 6 个应用 benchmark 和 4 个 microbenchmark，论文证明同一条工作流在不同云上的瓶颈完全可能不一样：AWS 往往端到端最快，Azure 常常计算关键路径最短但编排开销极大，Google Cloud 则比 Azure 稳一些，却经常在关键路径上更慢。

## 问题背景

单函数的 serverless 平台已经有不少 benchmark，但真正的应用越来越依赖 workflow：串行阶段、fan-out/fan-in、循环、条件分支，都会让问题从「函数跑多快」变成「编排系统怎么放大或掩盖函数成本」。偏偏主流云厂商在这一层差异很大。AWS 和 Google 用状态机式语言，Azure 用代码化 orchestrator；并行度限制不同，计费粒度不同，表达同一逻辑所需的样板代码量也不同。

这使得现有比较很难服人。作者回顾了 72 篇 serverless workflow 论文，发现大家使用的应用、覆盖的负载类别、比较的平台集合都不一致，几乎不存在可复用的基线。已有 SeBS 这类 benchmark suite 主要面向单个 FaaS 函数，而不是 workflow orchestration。于是，一篇论文里看到的差异，到底来自云平台本身、workflow 写法，还是作者手工重写出来的平台特定实现，经常说不清楚。

## 核心洞察

论文最重要的判断是：想做公平的 workflow benchmark，不能把平台语法差异原样带进实验，但也不能把真正影响性能的语义一起抹平。SeBS-Flow 的做法，是把 workflow 建模成两层：一层是函数阶段和 coordinator 组成的控制流；另一层是阶段之间数据怎么走，包括 object storage、NoSQL、invocation payload、provider-transparent return，以及 reference passing。

这个拆分很关键。控制流和数据依赖由统一定义承担，具体函数仍然是普通云函数，按照标注自己去读写对象或数据库。这样生成出来的 AWS、GCP、Azure 版本在结构上可比，同时又保留了真正决定成本和延迟的编排与数据移动行为。换句话说，SeBS-Flow 不是想掩盖平台差异，而是把差异暴露在可重复的实验框架里。

## 设计

它的模型建立在 workflow net with data 之上，并额外加了两样东西。第一，transition 被分成 serverless function 和 coordinator。Coordinator 不执行用户逻辑，而是显式表示平台在阶段边界做的调度与同步。第二，每个读写数据的动作都带 resource annotation，说明数据是走 object storage、NoSQL、request payload、provider 决定的返回通道，还是只传一个 reference。

建立在这个模型之上的 workflow 定义语言只有 6 类 phase：`task`、`map`、`loop`、`repeat`、`switch`、`parallel`。论文刻意把语言保持得很小，理由是主流工作流已经大多能被这几种构件覆盖，而构件越少，跨平台自动转写就越稳。

真正体现工程取舍的是各平台后端。AWS 没有原生的顺序数组循环，所以 SeBS-Flow 用顺序配置的 `map` 去模拟 `loop`。Google Cloud Workflows 没有真正的 task primitive，于是每个任务都要变成对函数触发 URL 的 HTTP POST，再加额外状态解析返回值；它的并行 map 甚至要求把单个函数体包成子工作流。Azure 则相反：SeBS-Flow 上传抽象定义，再由用户 orchestrator 在运行时解析定义并调起 Durable Functions activity。三种实现显然不完全一样，但都由同一份 workflow 规格机械生成。

基准套件本身则构建在 SeBS 之上。SeBS-Flow 补上了 object storage 管理、跨云 NoSQL 抽象，以及基于 Redis 的时间戳收集。工作负载包括 6 个应用 benchmark：Video Analysis、Trip Booking、MapReduce、ExCamera、一个简单的 ML training pipeline，以及 1000Genomes；另有 4 个 microbenchmark，分别针对 function chain、object storage I/O、parallel sleep 和 selfish detour 噪声测量。

## 实验评估

这篇论文的评估顺序是合理的：先看模型够不够表达，再看自动转写会不会额外加负担，最后才比较不同云。对文献中的 workflow 来说，在 58 个描述足够详细的案例里，有 53 个能被完整建模并转写；另有 2 个超出了 SeBS-Flow 的目标范围，另外 3 个是当前转写器还没覆盖，而不是模型本身表达不了。Azure 侧 orchestrator 的解释成本也几乎可以忽略：在最大的 1000Genomes workflow 上，它平均只花 13.6 ms，而该 workflow 的中位执行时间是 3757.55 s。

跨云比较时，作者尽量把条件压到一致：三家云都用同一份高层 workflow 定义，函数内存取能成功执行的最低共同配置，大多数 workload 都以 30 个并发 workflow burst 提交，并重复 180 次。结果最能说明问题的是，真正主导端到端表现的往往不是函数算得快不快，而是 orchestration。Azure 经常拥有最短的 critical path，但 orchestration overhead 会急剧膨胀。ExCamera 上，论文给出的平均 overhead 是 495.5 s，而 critical path 只有 13.5 s，超过 36x。后面的 microbenchmark 进一步把原因拆开：storage I/O 和 parallel scheduling 是两个主要来源。比如并行下载实验里，Azure 对 128 MB 下载会额外带来接近 149 s 的 overhead，而 AWS 大致维持在 1 s 左右。

冷启动是另一条主线。Table 5 显示，应用 benchmark 中 AWS 的 cold-start 比例在 73.58%-100%，Google Cloud 在 38.24%-99.26%，Azure 只有 0.6%-7.72%。当作者单独看 warm execution 时，AWS 的 critical path 最多可缩短 4.5x，Google Cloud 最多缩短 2.0x，几乎抹掉了 Azure 在计算路径上的优势。论文还顺手给科学工作流泼了盆冷水：1000Genomes 在 AWS 上要 259.8 s，在 Google Cloud 上要 457.7 s，而在 Ault 这台 HPC 机器上只要 7.7 s。

## 创新性与影响

SeBS-Flow 的创新点不在于提出新的 serverless runtime，也不在于替换某家的 workflow engine。它真正贡献的是一套可复现的 workflow benchmark 方法：统一的控制流/数据流模型、自动转写到各家云的 workflow service，以及覆盖 web、data、ML、media、scientific workflow 的工作负载集合。

这让它同时对研究界和工程界有用。对研究者来说，它提供了一条比「每篇论文自己拼一个 demo」更扎实的公共基线。对实践者来说，它给出的结论也有决策价值：Azure 靠低冷启动拿到较短的计算关键路径，但编排成本可能很重；AWS 往往端到端最快，却未必便宜；Google Cloud 常常更稳，却也更容易在关键路径上吃亏。后续无论是 benchmark、workflow portability，还是 workflow engine 论文，都很可能把它当参照物。

## 局限性

尽管设计认真，它终究还是 benchmark paper。工作负载只有 6 个真实应用，平台也只覆盖 3 个托管工作流服务，并且每家主要只测了一个 region。作者自己也承认，日期和区域变化都可能影响结果。

所谓可移植，也不是字节级等价。AWS 的 `loop` 是用 `map` 模拟的，Google Cloud 的 task 要包装成 HTTP 调用和子工作流，Azure 则依赖一个解释式 orchestrator。它们是原则一致的转写，不是逐条状态完全相同的实现，所以论文更准确的说法是 near-identical，而不是 identical。

模型本身也有边界。它不面向那些依赖函数间直接通信、或依赖系统动态状态做负载均衡式编排的 workflow；当前转写器也还没有覆盖文献里出现过的所有构件。换言之，SeBS-Flow 瞄准的是主流云工作流服务，而不是所有可能的 orchestration 设计。

## 相关工作

- _Copik et al. (Middleware '21)_ - SeBS 关注的是单个 FaaS 函数 benchmark，而 SeBS-Flow 把同一套基础设施扩展到了 workflow orchestration、共享数据服务，以及跨云工作流比较。
- _García López et al. (UCC Companion '18)_ - 这篇工作主要用 microbenchmark 比较 FaaS orchestration system；SeBS-Flow 则补上了可移植 workflow 定义和更完整的应用级 benchmark 集。
- _Wen and Liu (ICWS '21)_ - 他们对 serverless workflow service 做了测量研究，但主要是两类应用和若干 microbenchmark；SeBS-Flow 进一步提供了可公开复用的 benchmark suite 和自动转写层。
- _Kulkarni et al. (CCGrid '24)_ - XFBench 也研究 cross-cloud FaaS workflow benchmark，但 SeBS-Flow 更强调 provider-native workflow service、本地云数据通路，以及跨平台价格和扩展性分析。

## 我的笔记

<!-- 留空；由人工补充 -->
