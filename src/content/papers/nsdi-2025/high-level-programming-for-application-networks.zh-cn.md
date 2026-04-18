---
title: "High-level Programming for Application Networks"
oneline: "AppNet 用高层 match-action 规则描述 service mesh 功能，再编译成语义等价的 RPC library/proxy 部署，把 RPC 开销最多降低 82%。"
authors:
  - "Xiangfeng Zhu"
  - "Yuyao Wang"
  - "Banruo Liu"
  - "Yongtong Wu"
  - "Nikola Bojanic"
  - "Jingrong Chen"
  - "Gilbert Louis Bernstein"
  - "Arvind Krishnamurthy"
  - "Sam Kumar"
  - "Ratul Mahajan"
  - "Danyang Zhuo"
affiliations:
  - "University of Washington"
  - "Duke University"
  - "UCLA"
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - pl-systems
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AppNet 把 service mesh 视为一个高层程序，而不是一串平台相关的 filter。开发者用针对 RPC 字段与共享状态的 match-action 规则描述 application network function，编译器再决定每个函数该放在哪、跑在哪种运行时上，同时用符号化等价性检查保证对任意 RPC 流都不改变语义。论文在随机链路和两个微服务应用上都展示了显著的开销与端到端时延下降。

## 问题背景

论文要解决的是 service mesh 的一个根本矛盾。按理说，application network 只服务于一组已知微服务和已知策略，应该既能针对应用定制，也不该太贵。但现实里，开发者仍要用平台相关、非常底层的方式去写 application network function，或者把 RPC 语义硬塞进通用 HTTP 模块里。这让很多本来很自然的应用特定逻辑，例如按 RPC 字段做访问控制、路由或限流，变得难写又难维护；当微服务代码来自第三方、无法修改时，问题更严重。

性能上同样如此。现有 service mesh 把函数执行顺序、放置位置和运行平台都交给人手工指定：是在进程内的 RPC library、client/server sidecar，还是 remote proxy。可这些决策会和共享状态、副本数量、上游函数是否会 drop 请求等因素相互影响，局部最优直觉经常出错。论文引用的现有结果表明，application network 会把 RPC latency 和 CPU usage 抬高 2-7x。于是，真正的问题并不是“service mesh 太慢”这么简单，而是今天的抽象直接暴露了执行细节，却没有把“我想实现什么语义”与“系统该如何高效落地”分离开来。

## 核心洞察

这篇论文的核心主张是，application network 也应该像更低层网络那样被“编译”。程序员负责描述语义，编译器负责选择高效实现。要做到这一点，语言必须显式暴露 RPC 字段访问、共享状态以及日志这类辅助输出；同时，编译器必须对整个 RPC 流上的有状态行为做推理，而不是只看单个请求。

第二个关键洞察是，语义等价性不需要精确重建每个函数内部的所有处理逻辑。AppNet 把每个 element 抽象成一组 symbolic transfer function，只记录它会影响哪些字段、状态变量、drop/reorder 事件和辅助输出通道。随后，编译器对 element chain 做 symbolic execution，判断某个重排、迁移后的实现，在 strong 或 weak observation consistency 下，是否仍与原始规范等价。正是这个抽象，让 AppNet 能大胆优化而不至于偷偷改掉行为。

## 设计

AppNet 用一条 element chain 来描述两个微服务之间的一条通信边。用户可以把 element 放进四个规范槽位里：`client`、`server`、`any`，以及给压缩/解压这类成对操作准备的 `pair`。每个 element 都有 `state`、`init`、`req`、`resp` 四个部分。处理逻辑写成 generalized match-action rule，匹配对象既可以是 RPC metadata、payload 字段，也可以是 built-in function 的结果和 key-value state。共享状态是一等公民，用户可以直接声明 strong consistency、weak consistency，或指定 `sum` 之类的聚合方式。因为编译器还会读取 RPC schema，所以开发者既不需要手写序列化代码，也不必手工维持字段名与 Protobuf 定义的一致性。

优化器会先给每个状态变量打上依赖标签，例如 client replica、server replica 或 global，然后在 placement、platform 和 ordering 的组合空间里搜索。它使用 multi-start simulated annealing，并用一个启发式 cost model 偏好低开销平台、能够把整条链压缩到单一平台从而绕过其他平台的方案、与状态依赖对齐的放置方式、需要同步共享状态的 element 共置，以及把可能 drop RPC 的 element 尽量提前。对短链，编译器也可以直接 brute-force 搜索。

真正让这个优化安全可用的，是论文的等价性检查。AppNet 先把每个 element 抽象成 transfer function，再对整条链做 symbolic execution，得到输出 RPC、状态更新和辅助通道输出的端到端 transfer function。若这些函数完全一致，两条链就在 strong consistency 下等价；若只允许辅助输出不同、而微服务可见行为必须一致，则对应 weak observation consistency。运行时控制器与 Kubernetes 和 Istio 集成，负责下发 gRPC interceptor、Envoy C++ 或 Envoy Wasm 模块；强一致共享状态通过 Redis 访问，弱一致状态则后台同步；配置更新采用带版本号的两阶段切换，保证单个 RPC 只会看到旧配置或新配置，不会看到混合态。

## 实验评估

论文从三个层面评估 AppNet。第一是表达能力。作者实现了 14 个 application network function，包括 12 个常见功能，如 rate limiting、cache、logging、admission control，以及更复杂的 ServiceRouter 和 Prequal 风格路由/负载均衡。12 个常见功能只需 7-28 行 AppNet 代码，ServiceRouter 需要 62 行，Prequal 需要 88 行。与手写 filter 相比，生成代码的 abstraction tax 也不高，latency 和 CPU 的中位数额外开销只有 1-4%。

第二是 RPC processing chain 的微基准。对 30 条随机生成的 5-element chain，AppNet 在 `NoOpt` 和 `LocalOpt` 两个基线之上都取得明显优势。相对 `NoOpt`，在 strong consistency 下，AppNet 把 service time、tail latency 和 CPU usage 的中位数分别降低 47%、44% 和 42%；切换到 weak consistency 后，中位数降幅提升到 74-83%。论文摘要里的 headline 结果，即 latency 最多降低 82%、CPU 最多降低 75%，就来自这组实验中的最好案例。优化器本身也足够实用，论文报告 5-element chain 的求解时间约为 1.4 秒。

第三是应用级收益。对 Hotel Reservation，AppNet 在 strong consistency 下把端到端 service time、tail latency 和 CPU 中位数分别降了 35%、29% 和 26%；在 weak consistency 下则进一步达到 49%、41% 和 42%。附录里的 Online Boutique 虽然收益稍小，但趋势一致。这说明论文并不是只在 Echo 这类微基准上压榨系统，而是真正抓住了微服务应用里 service-mesh tax 这一一阶问题。

## 创新性与影响

AppNet 的创新之处在于把三类通常分散出现的思想合在了一起：面向 application network logic 的可编程语言、能跨多个执行基座搜索实现的编译器，以及能处理 stateful chain、drop/reorder 与辅助输出的语义检查。相对 `ServiceRouter` 这类生产系统，它不是某一种特定策略的工程化实现，而是一个更通用的框架。相对 `P4`、`NetKat` 这类更偏 packet 层的高层语言，它把抽象边界抬到了 RPC 语义和 service-mesh 共享状态这一层。

它的影响也有两层。实践上，AppNet 表明 service mesh 不必在“表达力”和“低开销”之间二选一。概念上，它把 application networking 重新定义成一个 compilation problem，这意味着未来可以继续接入 kernel/hardware offload 之类的新后端，也能把配置更新的一致性做成编译器和控制器共同管理的能力。

## 局限性

这套系统仍明显是研究原型，且有真实部署约束。当前 AppNet 只支持三类执行目标：gRPC interceptor、EnvoyNative 和 EnvoyWasm。论文也明确说，kernel 或 eBPF 执行仍是未来工作。它还假设目标平台能够看到明文的 RPC header 和 payload；如果必须保留端到端 mTLS 且不允许中间节点解密，AppNet 实际上就只能退回到 gRPC interceptor。

有些成本也只是被转移，而非彻底消失。强一致共享状态每次访问都要经过 Redis，因此最终性能很依赖编译器是否能把 element 放到与状态依赖对齐的位置，或在语义允许时安全地放宽一致性。成本模型本身也是启发式的，而不是从真实部署遥测中自动学习出来的。最后，论文大量实验使用的是随机生成的 chain，以及 Go/gRPC 版本的应用移植；这足以说明方向有很强潜力，但还不足以证明 AppNet 已覆盖最复杂的生产 service-mesh 策略。

## 相关工作

- _Saokar et al. (OSDI '23)_ - `ServiceRouter` 针对特定生产 service mesh 设计做深度工程化，而 `AppNet` 想用统一语言和编译器覆盖更广的一类 application network function。
- _Wydrowski et al. (NSDI '24)_ - `Prequal` 是一个复杂的 latency-aware 负载均衡器；在 `AppNet` 里，它只是可以被编码进去的一种策略，而不是系统的固定目标。
- _Panda et al. (OSDI '16)_ - `NetBricks` 通过安全组合 middlebox function 来提速，但它处理的是 packet-level NF，不是带放置与状态一致性推理的 RPC-level service-mesh logic。
- _Bremler-Barr et al. (SIGCOMM '16)_ - `OpenBox` 关注 packet-level NF 逻辑去冗余，而 `AppNet` 处理的是跨多种运行时的 stateful RPC-processing chain 语义等价问题。

## 我的笔记

<!-- 留空；由人工补充 -->
