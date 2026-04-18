---
title: "Skyler: Static Analysis for Predicting API-Driven Costs in Serverless Applications"
oneline: "用 serverless economic graph 和 SMT 定价模型，在部署前预测哪些 API 路径与输入会主导 serverless 账单。"
authors:
  - "Bernardo Ribeiro"
  - "Mafalda Ferreira"
  - "José Fragoso Santos"
  - "Rodrigo Bruno"
  - "Nuno Santos"
affiliations:
  - "INESC-ID / Instituto Superior Técnico, Universidade de Lisboa, Lisboa, Portugal"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790221"
code_url: "https://github.com/arg-inescid/Skyler.git"
tags:
  - serverless
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Skyler 把真正计费的云 API，而不是函数运行时间，本身当作 serverless 成本分析的中心。它从 JavaScript 和 IaC 构建 serverless economic graph，附着 provider 定价规则，再用 SMT 查询在部署前预测主导成本的路径、API 和输入。

## 问题背景

论文指出，今天的工具链和问题本身并不匹配。云厂商的 cost calculator 确实能把价格表相加，但前提是开发者已经知道每个云 API 的调用次数和 payload 大小。真实的 serverless 应用里，这些量又恰恰取决于分支、循环、异步触发、共享状态，以及各个服务自己那套计费规则。部署后的动态优化工具能帮助调 compute 效率，但它们需要真实执行，而且重点通常不在 API 侧账单，无法在上线前告诉开发者“是不是某条 API 路径本身就会把预算打穿”。

论文中的 `/createPost` 例子把这个问题讲得很清楚：一次请求可能只做一次用户查询，也可能进一步触发数据库写入、入队、toxicity analysis，以及后续的更新。由于 DynamoDB、SQS 和 Comprehend 的计费方式完全不同，这些控制流差异会直接变成账单差异。完整 moderation 路径最多可以比最小路径贵 `1368x`，而把输入从 `1 KB` 增长到 `200 KB`，总成本还能再放大超过 `50x`。论文想强调的是，这并不是玩具例子。在 API-heavy 的 serverless workflow 中，真正主导账单的常常不是 compute，而是这些被忽略的 economic sinks。

## 核心洞察

核心招式是把会推高账单的 billable API site 当成一等对象，也就是论文所说的 economic sinks。一旦把这些 sink 显式放进程序模型里，成本分析就变成了一个 whole-program symbolic reasoning 问题：静态跟踪 tainted input 如何跨函数、跨资源传播到 sink，把请求次数和对象大小保留成符号变量，再把定价语义写成约束，而不是提前猜死一个 workload。

这个洞察的价值在于把“理解程序结构”和“探索不同工作负载”拆开。Skyler 只需要做一次较重的静态分析，后面就能在同一个符号模型上持续回答不同问题：哪条 workflow 最贵、哪一个 API 主导单条 workflow、哪个输入字段最容易放大成本、换云之后价格会怎么变。换句话说，论文真正的主张不只是“能估成本”，而是“把成本变成部署前就可查询的程序属性”。

## 设计

Skyler 的设计分三段。第一段是构建 SEG：系统解析 IaC 模板和 JavaScript 代码，在 MDG 基础上加入 event node、API call node、loop node、resource node，以及 `CFG`、`DEP`、`TRIGGER`、`USES` 等边。这样它不只知道“某个函数里调用了哪个 SDK”，还知道 HTTP 请求如何触发函数、函数如何写 queue 或 bucket、这些资源又如何异步触发后续函数，以及共享状态怎样影响后续 API 的 payload 和调用次数。图构建同时结合 intra-function 的对象依赖分析和 inter-function 的 IaC 触发/共享资源拼接。论文也专门提到 cloud-specific 差异：AWS 往往能直接从 SDK 参数里恢复 resource 和 payload，而 Azure、Google Cloud 更常需要额外逻辑去解析分层的 client/resource 绑定模式。

第二段是把 SEG 变成 SMT-LIB 约束。Skyler 为请求次数、payload 大小、循环计数器和成本声明符号变量，沿控制流传播调用次数，沿数据流传播对象大小，加入 provider 上界约束，再套入 provider-specific pricing equation。它的规则集其实很紧凑：声明规则引入符号，控制流规则传播调用次数，数据流规则传播对象大小，guard 规则编码 provider 限制，pricing 规则把 usage 映射成美元。定价逻辑被封装在可插拔的 service plugin 中，因此同一套图和 solver 可以支持 AWS、Google Cloud 和 Azure。第三段则是在这个模型上运行四类查询：找主导成本的 workflow，找某条 workflow 中最贵的 API，分析输入字段的成本敏感度，以及比较多云部署成本。整个原型约 `5,800` 行 Python，带 `21` 个 service plugin，后端求解器是 Z3。

## 实验评估

实验远不只是跑一个 toy example。作者构建了 `16` 个 JavaScript benchmark，其中包括 `12` 个 microbenchmark 和 `4` 个端到端应用，覆盖 storage、queue、database、orchestration 和跨函数 event chain。为了验证精度，他们把这些 workload 部署到 AWS、Google Cloud 和 Azure 上，用固定请求画像运行 `128 MB` 函数，再把 provider 账单中的 API 相关收费拿出来，与 Skyler 的符号预测比较。最终平均 MAPE 为 AWS `0.5%`、Google Cloud `0.98%`、Azure `4.5%`；Azure 偏差较大，主要来自当前模型还没覆盖的 auxiliary operation 和 CosmosDB 内部计费细节。

真正让这个系统有用的，是它产出的查询结果。对 Booking 来说，Skyler 发现 `reviewBooking` 一条 workflow 就贡献了超过 `90%` 的 worst-case 总成本，而其中 `detectSentiment` 一个 API 就超过了 `85%` 的主导阈值。输入敏感度分析则指出 `reviewComment` 是最该被限制大小的字段。跨云比较也说明“便宜 provider”并不是固定的：小 payload 时 AWS 最便宜，在 `200 B` 处最多领先 `32%`；payload 增大后，Google Cloud 最多能便宜 `6.4%`。

我觉得论文和手工方法的对比也很有说服力。作者把人工估算拆成四步，结果显示，在开发者还没有近似重建完整 taint flow 之前，误差都维持在很高水平；对 Booking 来说，前三步都还高于 `500%`。local emulator 虽然比 calculator 更接近真实执行，但它依旧要求人工枚举路径、反复执行，才能回答输入敏感度和路径主导性这类问题。相比之下，Skyler 对最大 benchmark 的完整分析仍低于 `312` 秒，而模型建好后的单次查询通常不到一秒。就论文想证明的点而言，这足以支撑它的核心主张：Skyler 不只是一个符号化演示，而是一个真正可用的、面向部署前的成本调试界面。

## 创新性与影响

和 _Mahgoub et al. (OSDI '22)_、_Zhang et al. (NSDI '24)_ 相比，Skyler 把分析对象从“已经部署后的执行与 compute 调优”转向了“部署前的 API-side billing semantics”。和 _Ferreira et al. (PLDI '24)_、_Gupta et al. (S&P '25)_ 相比，它则把 cross-function dependency graph 风格的静态分析从安全、合规和权限问题转向了 cloud economics。这个组合很新鲜：它不是把静态分析拿来报漏洞，而是直接产出开发者能拿来做预算与架构决策的查询结果。

因此，这篇论文最可能影响两类人。一类是构建多服务 serverless backend 的工程团队，他们终于能在流量到来前检查架构里的成本陷阱；另一类是系统研究者，他们可以把“成本是程序属性”这件事看成一个明确的问题定义。论文还有一个安全侧的外溢价值：当系统能指出哪些路径和输入会放大账单时，它也在帮助开发者理解 denial-of-wallet 风险暴露在哪里。

## 局限性

局限也很明确。如果 loop 里的 API 调用次数无法静态求出，Skyler 仍然要开发者提供预期值。它也不处理那些依赖内部执行细节的复杂数据库 query 计费，而 Azure 结果说明辅助性计费操作也会漏出当前抽象。再往外看，原型目前只支持 JavaScript，依赖人工维护的 API profile 和 pricing plugin，评估对象也还是作者构造的 benchmark，而不是大规模生产应用。

## 相关工作

- _Zhang et al. (NSDI '24)_ — Jolteon 通过运行时 profiling 和配置调优去优化已部署的 serverless workflow；Skyler 则在部署前估算 API-driven cost。
- _Mahgoub et al. (OSDI '22)_ — Orion 优化运行时的 sizing、bundling 和 prewarming；Skyler 估算部署前的 API 费用。
- _Ferreira et al. (PLDI '24)_ — MDG 提供了 Skyler 扩展的依赖图基座，Skyler 在其上加入 trigger、resource 和 pricing-aware sink。
- _Gupta et al. (S&P '25)_ — Growlithe 关注合规与权限；Skyler 把类似的 whole-application reasoning 转向货币成本估算。

## 我的笔记

<!-- 留空；由人工补充 -->
