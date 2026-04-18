---
title: "Quilt: Resource-aware Merging of Serverless Workflows"
oneline: "Quilt 先分析工作流调用图与资源上限，再只合并能装进同一容器的 serverless 子图，把远程函数调用改写成本地调用。"
authors:
  - "Yuxuan Zhang"
  - "Sebastian Angel"
affiliations:
  - "University of Pennsylvania"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764830"
code_url: "https://github.com/eniac/quilt"
tags:
  - serverless
  - scheduling
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Quilt 是一个面向 serverless workflow 的后台优化器：它不会把整条工作流一股脑合并，而是只合并那些在 CPU、内存约束下仍能装进一个容器、且值得内联的子图。它先通过 tracing 和资源画像推断调用图，再用受约束的图聚类算法决定怎么合并，最后在 LLVM IR 层把函数间 RPC 改写成进程内调用。对 DeathStarBench 工作流，Quilt 将中位完成时间降低 45.63%-70.95%，吞吐提升 2.05x-12.87x。

## 问题背景

这篇论文针对的是 serverless 的一个核心矛盾：开发者把应用拆成许多函数，是为了获得模块化、独立部署和语言自由；但工作流内部的每一次函数调用，本质上仍然是一次经过 API gateway、controller，甚至可能触发 cold start 的网络 RPC。对于短函数来说，这些编排成本经常比真正业务逻辑还重。即使没有 cold start，warm invocation 也往往要几毫秒，而不少 serverless 函数本身只运行几十毫秒。

已有工作已经证明，把函数放近一点或者直接 fuse 到一起能减少这类开销。但论文指出，“全部合并”并不是正确答案。第一，合并后的工作流可能超过平台给单个容器设定的 CPU 和内存限制，导致资源碎片化、throttling，甚至 OOM。第二，很多先前系统默认所有函数都用同一种解释型语言，依赖源码级改写；而现实中的 serverless 工作流越来越多地使用 Rust、C++、Swift、Go 这类编译型语言。Quilt 的问题因此是：能不能在不要求开发者重写代码的前提下，同时保留 serverless 的调度灵活性和接近单体应用的执行性能？

## 核心洞察

Quilt 的核心判断是，workflow fusion 应该被视为一个带资源约束的优化问题，而不是一条统一的程序变换规则。真正该合并的对象不是“整条 workflow”，而是“那些调用足够频繁、值得内联，而且聚合后的 CPU/内存需求仍能放进一个容器的子图”。只要平台能推断调用频率、平均 CPU 和峰值内存，它就可以把最昂贵的远程边内化，同时把高 fan-out、资源消耗大的部分保留为远程调用。

这个思路之所以可行，是因为 serverless 函数之间本来就通过一个很窄的接口通信：HTTP 上承载的字符串负载。Quilt 正是利用了这一点。决策阶段，它把 workflow 建模成带权 rooted DAG，并在节点上标注资源画像；合并阶段，它只需要在不同语言之间桥接字符串类型，而不必理解任意复杂的应用数据结构，因此 LLVM IR 层的跨语言合并就变得现实。

## 设计

Quilt 作为一个 opt-in 的后台服务运行。开发者仍然像平时一样上传函数；当 Quilt 积累到足够画像后，它会把某个工作流入口透明地替换成一个 merged binary。它保留跨 tenant、跨 workflow 的隔离，但不保留同一 merged workflow 内各函数之间的隔离；论文明确把这些函数视为更接近“链接进同一进程的库代码”。

在画像层，Quilt 在 API gateway 前放置 nginx ingress，用 OpenTelemetry 透明记录 caller-callee 关系，再借助 cAdvisor 和 InfluxDB 收集每个函数的平均 CPU 和峰值内存。由此得到的调用图是一个 rooted DAG，边权来自调用频率，并被归一化为“每次 workflow 执行大约会触发多少次该边”。优化问题允许子图重叠，因为一个被多处调用的函数有时值得在多个 merge group 中复制。每个候选 merge group 都必须保持为一个连通的 rooted DAG，且其估计 CPU 与内存使用不得超过平台限制；优化目标则是最小化跨子图边权，也就是剩余远程调用的次数。

对小图，Quilt 枚举 root set 并求解 ILP，得到最优划分。对大图，它使用 Downstream Impact Heuristic，不只看一个节点本地的边权，还看它下游子树携带了多少 CPU 和内存压力。这个启发式是规划器里最关键的系统点：它优先把那些资源密集的下游部分单独切出来，避免它们把整个全局打包方案拖向坏解。

一旦划分确定，Quilt 就把函数编译到 LLVM IR，重命名冲突符号，链接 caller/callee 模块，并把 `sync_inv`/`async_inv` 改写成本地调用。同语言合并相对直接；跨语言合并则用一层小型 shim，把各语言的字符串类型通过 `char *` 互转，因为 serverless 的 ABI 本质上就是 string-in/string-out。随后 Quilt 再跑一轮优化，去重库，延迟 libcurl 初始化，让已合并路径在不需要剩余远程调用时不必支付 HTTP 库加载成本，并按 BFS 顺序逐步把整个子图合成一个二进制。

## 实验评估

实验在一个六机集群上完成，并固定使用 Fission 和 Rust，以减少平台变量。工作负载来自 DeathStarBench 的三个应用：Social Network、Hotel Reservation、Movie Review。主要对比对象有两个：一个是每个函数各自运行在单独容器中的 baseline；另一个是 container-merge baseline，它把整个 workflow 放进同一个容器、通过内部 API gateway 保留进程级函数边界，但不做真正的进程内融合。

在延迟实验中，Quilt 在给定资源上限下对工作流进行合并，并与拥有相同总容器预算的 baseline 对比。结果是：在 11 条工作流中的 9 条上，中位延迟下降 45.63%-70.95%，tail latency 下降 15.64%-85.47%。另外两条来自 Hotel Reservation 的路径提升有限，因为它们本来就在函数内部花掉数秒，函数调用开销并不是主瓶颈。这和论文主张一致：Quilt 最适合由大量短函数组成的 workflow。

在吞吐上，Quilt 同时优于两个基线，因为它既删掉了 RPC 路径上的无效工作，也更灵活地共享了 CPU 与内存。以 `compose-post` 为例，同步调用场景下，Quilt 相比 baseline 将延迟降低 65.74%，吞吐提高 11.24x；异步场景下，延迟降低 51.0%，吞吐提高 12.87x。container-merge 也能略微降延迟，但因为 Fission 可能把多个完整 workflow 实例塞进同一容器，它仍然容易在高负载下触发内存问题。Quilt 通过更小的 merged binary 和更少的进程级重复开销避免了这一点。

论文还专门证明了“资源感知拆分”不是点缀，而是必要条件。在一个被修改过、专门用来施压 CPU 上限的 `nearby-cinema` workflow 上，如果把所有函数都合成一个二进制，虽然延迟更低，但吞吐反而比 baseline 差 11.64%，原因是 merged 容器被 CPU throttling 卡住。按 Quilt 的优化器把它拆成两个 merged binary 后，吞吐则比 baseline 高 50.75%。在规划器质量上，Downstream Impact Heuristic 在 25 节点图上的 optimality gap 只有 0.0394，在 200 节点随机图上耗时不到 0.27 秒；真正主导总合并时间的是编译和链接，大约需要 1.5 分钟。论文还展示了 conditional local/remote invocation，可以在 fan-out 画像失真时避免资源超限和崩溃。

## 创新性与影响

Quilt 的新意不只是“让函数调用更便宜”，而是把三个通常分散讨论的点整合到了一起：在不修改现有 serverless 平台的前提下透明部署、在 LLVM IR 层做跨语言融合、以及显式考虑 CPU/内存约束的资源感知 merge planner。它真正贡献的是一种判断标准：哪些远程边值得被内化，必须由平台约束和工作流结构共同决定。

因此，这篇论文对 serverless 研究者和平台实现者都很有价值。对研究者来说，它表明 workflow 结构应该继续暴露给运行时，而不是被 API 边界完全遮蔽；对平台方来说，它给出了一条不牺牲现有 scheduler、却能回收大量单体性能的现实路径。它也把“函数融合”这个话题从 Python 级源码拼接扩展到了编译型、多语言工作流。

## 局限性

论文对限制说得比较坦率。Quilt 只优化函数之间的直接调用；如果函数通过 SQS 一类外部系统交互，这些边就不在它的作用范围内。合并后，同一 workflow 内的函数级隔离被削弱，因此处理敏感数据的函数应该 opt out，或者额外配合隔离机制。失败粒度也变粗了：一旦某个函数在 merged process 内崩溃，整个 merged workflow 实例都可能一起失败。

此外，部署和评估层面也有保留。跨语言实现目前只在五种语言上验证过，论文并没有深入讨论更复杂 runtime 或 GC 之间的长期交互。合并时间并不低，编译和链接大约要 1.5 分钟。最后，绝大多数证据仍来自 benchmark workflow 和随机图实验，而不是生产级、多租户 serverless 集群，所以关于 workload drift、公平性和 rollback policy 的问题，论文只给出了初步答案。

## 相关工作

- _Jia and Witchel (ASPLOS '21)_ - Nightcore 把相关函数放到同一 worker 中，并用本地通信替代部分远程调用；但它既不透明地复用现有平台，也没有解决 Quilt 关注的跨语言合并问题。
- _Mahgoub et al. (ATC '21)_ - SONIC 优化的是同一 VM 内链式 serverless 函数之间的数据传递；Quilt 则把代码直接 fuse 到一个进程里，并把 CPU、内存约束纳入 merge 决策。
- _Kotni et al. (ATC '21)_ - Faastlane 通过带额外隔离机制的同语言函数融合来加速 FaaS workflow；Quilt 的重点则是透明的 LLVM 级跨语言融合。
- _Mahgoub et al. (POMACS '22)_ - WiseFuse 通过 workload characterization 和 DAG transformation 优化 serverless workflow；Quilt 在此基础上进一步提出了更丰富的资源感知聚类模型和具体的跨语言编译流水线。

## 我的笔记

<!-- empty; left for the human reader -->
