---
title: "Fork in the Road: Reflections and Optimizations for Cold Start Latency in Production Serverless Systems"
oneline: "AFaaS 用面向 FaaS 的运行时接口、资源池化与分层可 fork seeds，替换漫长的 OCI 冷启动路径，把生产环境冷启动压到毫秒级。"
authors:
  - "Xiaohu Chai"
  - "Tianyu Zhou"
  - "Keyang Hu"
  - "Jianfeng Tan"
  - "Tiwei Bie"
  - "Anqi Shen"
  - "Dawei Shen"
  - "Qi Xing"
  - "Shun Song"
  - "Tongkai Yang"
  - "Le Gao"
  - "Feng Yu"
  - "Zhengyu He"
  - "Dong Du"
  - "Yubin Xia"
  - "Kang Chen"
  - "Yu Chen"
affiliations:
  - "Tsinghua University"
  - "Ant Group"
  - "Shanghai Jiao Tong University"
  - "Quan Cheng Laboratory"
conference: osdi-2025
code_url: "https://github.com/antgroup/AFaaS"
tags:
  - serverless
  - virtualization
  - datacenter
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

AFaaS 的核心论点是，生产级 serverless 冷启动的瓶颈已经不只是 sandbox 创建本身。它用面向 serverless 的 FRI 取代 OCI 的长控制路径，池化和共享高争用内核资源，再从分层 user-code seeds 中 fork 新实例。部署在 Ant Group 后，它相对基于 Catalyzer 的基线把端到端延迟降低了 1.80x-8.14x，并且在 24x 并发下把冷启动延迟稳定在 6.97 ms 到 14.55 ms。

## 问题背景

论文首先指出一个很不舒服的生产事实：即便平台已经使用 secure containers 和 fork-based startup，冷启动依然足够常见，足以继续主导用户体验。Ant Group 报告平台上有超过 50,000 个独立函数、每天大约 1 亿次调用，但调用分布高度倾斜。由于为低频函数长期保留热实例会浪费太多内存，平台只保留 1 分钟缓存，因此超过 50% 的函数冷启动概率大于 0.75，超过 35% 的函数冷启动概率为 1。对那些真正执行时间往往只有 50-100 ms 的函数来说，一次秒级启动仍然是头号延迟问题。

作者认为，先前工作通常只优化冷启动链路中的某一段，然后就默认问题解决了。Catalyzer 这类 fork-based 系统把 sandbox 创建压到极快；checkpoint/restore 和 caching 方案减少部分初始化工作；lightweight runtime 则删掉了一部分容器开销。但在真实生产路径里，这些局部胜利并不会自动变成低的用户可见延迟。论文给出的 Node.js 示例中，仅控制路径就需要 18-25 ms，而 user-code initialization 需要 275.53 ms，其中 238.73 ms 花在依赖加载上。并发一高，情况还会恶化：尾延迟显著扩散，吞吐还会随着时间推移下降，因为宿主机内核在 namespace、mount 和 seccomp 相关路径上出现争用。

这也是问题定义里最有价值的部分。论文并不是在说“fork 还不够快”，而是在说生产环境中的冷启动本质上是一条流水线；一旦某一段被优化，新的瓶颈就会转移出来。它归纳出的三个核心缺口分别是：`containerd` 与低层 runtime 之间的控制路径开销、并发启动时的资源争用，以及当 sandbox 启动已很便宜后会反过来主导整体延迟的 user-code initialization。

## 核心洞察

论文的中心判断是，剩余的大部分冷启动成本都来自对可复用状态的重复构造。如果面向高频 serverless 路径的操作不再强行走通用 OCI 栈，而是被专门化，那么这些操作就可以从 binary load 和多层 RPC 退化成直接函数调用。如果那些在并发下最容易争用的资源能被预先准备、池化，或者安全地与 seed 共享，那么启动路径就不必在最热的时刻和内核竞争。如果 user-code 状态能按不同粒度分层组织，平台就不必在“完整热函数”和“完全冷启动”之间二选一，而是可以从最近的已准备祖先节点 fork。

这套思路之所以成立，是因为 AFaaS 建立在 secure container 的 CoW 共享和 guest 内独立执行之上。很多决定启动速度的状态，例如 runtime 初始化结果、预编译好的 seccomp rules，以及预加载好的 user code，都可以被继承，而不必把实例变成另一个用户可变执行状态的热缓存。换句话说，系统把冷启动当成了跨整个软件栈的状态摆放问题，而不是单一的 VM fork 原语问题。

## 设计

AFaaS 保留了两层 runtime 架构：高层仍然是 `containerd`，低层仍然是基于 Catalyzer 的 secure container runtime，但它用 FRI，也就是 Function Runtime Interface，替换了 OCI 风格的交互。FRI 通过 `containerd-faas-package` plugin 暴露 `create()`、`fork()` 和 `activate()` 三个接口。关键在于，只有 root seed 需要走一次昂贵的 `create()` 路径去加载低层 runtime binary；之后 `fork()` 和 `activate()` 都可以由高层 runtime 直接调用，从而绕开 Catalyzer 中每次冷启动都要重新 binary load 的 18-25 ms shim 路径。

为了解决争用问题，AFaaS 把资源分成适合池化与适合共享两类。它预先分配 veth pair，并把 cgroup 放进池里循环复用，这样实例创建就不必在高负载下反复创建和销毁这些内核对象。它允许 seed 与实例共享 network 和 IPC namespaces，在 seed preparation 阶段预编译 seccomp rules，并把网络栈拆成可共享状态和实例专属绑定两部分。可共享的部分，例如协议处理器和其他相对固定的结构，可以直接从 seed 继承；实例特有的地址与设备绑定则在 fork 后单独配置。

对 user-code initialization，AFaaS 采用树状 seed 组织。level-0 root seed 只包含 guest OS 状态，level-1 seeds 增加 Node.js 或 Python 等语言 runtime，level-2 seeds 再加入函数特定代码、依赖库和框架初始化状态。请求到来时，runtime 会沿着这棵树寻找最近的可用祖先并从其 fork。这样既形成了从 user-code-specific seed 到 language seed 的 best-effort 光谱，又能依靠 CoW 在相关 seeds 之间共享内存。实现层面，论文还加入了 container early destroy 和 EPT prefill，以降低短生命周期函数的销毁开销与页表缺失成本。

## 实验评估

评估运行在一台 24 核 Xeon、512 GB 内存的机器上，并把 AFaaS 与 Kata、gVisor，以及三个中间配置 `CataOnly`、`CataOPT1`、`CataOPT2` 做比较。这个分层基线设计很有价值，因为它能清楚地说明收益来自三类缺口的联合作用，而不是来自一个难以拆解的黑箱系统。

顺序执行下的主要结果基本支撑了论文主张。对于初始化时间短、执行时间也短的函数，AFaaS 相比 `CataOnly` 将平均端到端延迟降低了 3.76x-6.68x，P99 延迟降低了 6.31x-11.74x。对于 user-code initialization 占主导的函数，收益更大，平均为 4.09x-31.48x，P99 为 6.19x-34.51x，因为 seed hierarchy 可以直接跳过框架和依赖加载。对长执行函数，收益则自然缩小到大约 1.05x-1.14x，因为这时启动已经不再是主要部分。

并发结果更关键，因为论文的第二个缺口讨论的是稳定性，而不只是中位数速度。在 JS benchmark 上，AFaaS 在 1x 到 24x 并发下把端到端延迟维持在 16.34-39.56 ms，而 `CataOnly` 落在 51.32-117.92 ms。单看冷启动部分，AFaaS 维持在 6.97-14.55 ms，`CataOnly` 则是 38.39-74.05 ms。持续 24x 并发时，`CataOnly` 的吞吐会随着 namespace 和 kernel lock 路径跌出 fast path 而持续下降，AFaaS 则稳定得多。论文还显示，tree-structured seeds 相比 `CataOnly` 里按函数单独维护的 seeds 可节省 28.11%-84.91% 的内存；对 8 个 Node.js 生产函数做的一天统计中，AFaaS 的端到端加速比为 1.80x-8.14x，启动时间保持在 5.45 ms 到 9.41 ms。整体上，这组评估确实支持中心论点，只是大部分真实世界证据仍来自 Ant Group 自己的系统栈和工作负载。

## 创新性与影响

相对于 _Du et al. (ASPLOS '20)_ 的 Catalyzer，AFaaS 把“sub-millisecond fork”视为真正生产问题的起点而不是终点，并展示了如果不继续处理 OCI 控制路径、内核争用和 user-code initialization，理论上的 fork 收益会被大量吞掉。相对于 _Li et al. (ATC '22)_ 的 RunD，这篇论文的重点不在于再发明一个更轻的 secure container runtime，而在于围绕 FaaS 语义专门化接口和资源生命周期。相对于 _Yu et al. (ASPLOS '24)_ 以及更广泛的 caching/checkpoint 路线，AFaaS 则通过分层、best-effort 的 forkable seeds，避免依赖长期保温实例或 restore 开销较重的快照路径。

因此，这篇论文的重要性更多来自工程整合能力，而不是某个孤立新原语。它告诉 serverless 平台实现者：当 fork-based startup 已经足够快之后，真正还会继续消耗几十到几百毫秒的层次究竟在哪里。对于运行 secure-container-based FaaS 平台的工程团队，这种“剩余瓶颈地图”本身就很有引用价值。

## 局限性

AFaaS 的收益有一部分来自主动放弃通用性。FRI 是明确面向 serverless 专门设计的，并且和 `containerd` 以及 AFaaS 的低层 runtime 紧耦合，因此它不是对任意 OCI-compliant stack 的直接改良。安全性论证也主要沿用了 prior secure-container work 的 threat model，而不是形式化证明 pooled 或 shared resources 在所有部署里都绝对安全；论文解释了为什么在自己的设定里共享 network namespace、IPC namespace 和若干内核对象是可接受的，但这仍然是一种特定部署前提下的判断。

user-code seeding 的收益同样是有条件的。最大收益出现在那些足够常用、值得维护 seeds，但又没有热到可以一直依赖 hot instances 的函数上。过多的 user-specific seeds 会增加内存压力，甚至触发 swap，这一点论文明确提醒过。在超高并发下，单个 seed 本身也可能成为串行瓶颈，因为同一时刻只能从它克隆一个实例；共置部署的其他工作负载也可能重新引入 cgroup lock 抖动。最后，评估最强的部分还是 Ant Group 的生产函数和偏 Node.js 的案例，论文并没有说明这些收益在其他 serverless 栈、或者以长时间应用执行为主的工作负载上还能保留多少。

## 相关工作

- _Du et al. (ASPLOS '20)_ - Catalyzer 证明了 secure-container startup 可以通过 fork 降到亚毫秒，而 AFaaS 进一步说明这还不足以解决生产环境端到端冷启动。
- _Li et al. (ATC '22)_ - RunD 面向高密度、高并发 secure containers，而 AFaaS 关注的是建立在 secure-container substrate 之上的 serverless 专用控制路径和 seed 复用机制。
- _Wei et al. (OSDI '23)_ - MITOSIS 用 remote fork 和 RDMA 去除跨节点的 provisioned concurrency 依赖，而 AFaaS 不依赖专用硬件，重点解决单节点生产瓶颈。
- _Yu et al. (ASPLOS '24)_ - RainbowCake 通过分层缓存和共享来缓解 serverless 冷启动，而 AFaaS 则依赖 hierarchical seeds 与 best-effort multi-level fork，而不是保留热缓存实例。

## 我的笔记

<!-- 留空；由人工补充 -->
