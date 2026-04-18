---
title: "Skyler: Static Analysis for Predicting API-Driven Costs in Serverless Applications"
oneline: "用 serverless economic graph 和 SMT 定价公式，在部署前静态预测哪些 API 路径与输入会主导 serverless 账单。"
authors:
  - "Bernardo Ribeiro"
  - "Mafalda Ferreira"
  - "José Fragoso Santos"
  - "Rodrigo Bruno"
  - "Nuno Santos"
affiliations:
  - "INESC-ID / Instituto Superior Técnico, Universidade de Lisboa, Lisboa, Portugal"
conference: asplos-2026
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

云厂商的 cost calculator 只有在开发者已经知道每个服务的调用次数和 payload 大小时才有意义。但真实的 serverless workflow 会受到分支、循环、异步触发、共享状态和 payload-dependent billing 的共同影响。论文中的 `/createPost` 例子说明得很直接：一次请求可能只做一次读，也可能扩展成入队、moderation 和多次数据库更新；由于 DynamoDB、SQS 和 Comprehend 的计费方式不同，完整 moderation 路径最多可以比最小路径贵 `1368x`，而把输入从 `1 KB` 增长到 `200 KB`，总成本还能再放大超过 `50x`。

## 核心洞察

核心招式是把会推高账单的 API 位置当成一等对象，也就是论文所说的 economic sinks。Skyler 先静态跟踪 tainted input 如何跨函数、跨资源传播到这些 sink，再把请求次数和对象大小保留成符号变量，把具体“如果这样输入会花多少钱”之类的问题推迟给 solver。这样，同一个静态模型就能回答路径级、输入级和跨云的成本问题，而不需要先把程序部署出去。

## 设计

Skyler 的设计分三段。第一段是构建 SEG：系统解析 IaC 模板和 JavaScript 代码，在 MDG 基础上加入 event node、API call node、loop node、resource node，以及 `CFG`、`DEP`、`TRIGGER`、`USES` 等边。这样它不只知道“某个函数里调用了哪个 SDK”，还知道 HTTP 请求如何触发函数、函数如何写 queue 或 bucket、资源又如何异步触发后续函数，以及对象在这些步骤之间怎样传播和变形。图构建同时结合 intra-function 的对象依赖分析和 inter-function 的 IaC 触发/共享资源拼接。论文也指出 cloud-specific 差异：AWS 往往能直接从 SDK 参数里恢复 resource 和 payload，而 Azure、Google Cloud 更常需要额外逻辑去解析分层的 client/resource 绑定模式。

第二段是把 SEG 变成 SMT-LIB 约束。Skyler 为请求次数、payload 大小、循环计数器和成本声明符号变量，沿控制流传播调用次数，沿数据流传播对象大小，加入 provider 上界约束，再套入 provider-specific pricing equation。定价逻辑被封装在可插拔的 service plugin 中，因此同一套图和 solver 可以支持 AWS、Google Cloud 和 Azure。第三段则是在这个模型上运行四类查询：找主导成本的 workflow，找某条 workflow 中最贵的 API，分析输入字段的成本敏感度，以及比较多云部署成本。整个原型约 `5,800` 行 Python，带 `21` 个 service plugin，后端求解器是 Z3。

## 实验评估

实验并不只是一个玩具示例。作者构建了 `16` 个 JavaScript benchmark，其中包括 `12` 个 microbenchmark 和 `4` 个端到端应用，覆盖 storage、queue、database、orchestration 和跨函数 event chain。为了验证精度，他们把这些 workload 部署到 AWS、Google Cloud 和 Azure 上，用固定请求画像运行 `128 MB` 函数，再把 provider 账单中的 API 相关收费拿出来，与 Skyler 的符号预测比较。最终平均 MAPE 为 AWS `0.5%`、Google Cloud `0.98%`、Azure `4.5%`；Azure 偏差较大，主要来自尚未建模的 auxiliary operation 和 CosmosDB 内部细节。

查询结果更能体现系统的价值。对 Booking 来说，Skyler 发现 `reviewBooking` 一条 workflow 就贡献了超过 `90%` 的 worst-case 总成本，而其中 `detectSentiment` 一个 API 就超过了 `85%` 的主导阈值。输入敏感度分析则指出 `reviewComment` 是最该被限制大小的字段。跨云比较也说明“便宜 provider”并不是固定的：小 payload 时 AWS 最便宜，在 `200 B` 处最多领先 `32%`；payload 增大后，Google Cloud 最多能便宜 `6.4%`。论文还表明，相比人工使用 calculator 或 local emulator，Skyler 更适合系统化分析，因为手工方法在没有重建完整 taint flow 之前误差会非常高，而 Skyler 对最大 benchmark 的完整分析仍低于 `312` 秒，模型建好后的单次查询通常不到一秒。

## 创新性与影响

和 _Mahgoub et al. (OSDI '22)_、_Zhang et al. (NSDI '24)_ 相比，Skyler 的位置是互补的：Orion 和 Jolteon 优化的是运行时执行和 compute 效率，而 Skyler 关心的是部署前的 API 侧账单。和 _Ferreira et al. (PLDI '24)_、_Gupta et al. (S&P '25)_ 相比，它则把 dependency-graph 风格的静态分析从安全、合规与权限问题转向了 pricing semantics 和 denial-of-wallet 风险。这个组合很新鲜：它不是把静态分析拿来报漏洞，而是直接产出开发者能拿来做成本决策的查询结果。

## 局限性

局限也很明确。如果 loop 里的 API 调用次数无法静态求出，Skyler 仍然要开发者提供预期值。它也不处理那些依赖内部执行细节的复杂数据库 query 计费，而 Azure 结果说明辅助性计费操作也会漏出当前抽象。再往外看，原型目前只支持 JavaScript，依赖人工维护的 API profile 和 pricing plugin，评估对象也还是作者构造的 benchmark，而不是大规模生产应用。

## 相关工作

- _Mahgoub et al. (OSDI '22)_ — Orion 优化运行时的 sizing、bundling 和 prewarming；Skyler 估算部署前的 API 费用。
- _Zhang et al. (NSDI '24)_ — Jolteon 提升 workflow 执行效率；Skyler 静态推断 billable API usage。
- _Ferreira et al. (PLDI '24)_ — MDG 提供了 Skyler 扩展的依赖图基座，Skyler 在其上加入 trigger、resource 和 pricing-aware sink。
- _Gupta et al. (S&P '25)_ — Growlithe 关注合规与权限；Skyler 把类似的跨函数分析转向货币成本估算。

## 我的笔记

<!-- 留空；由人工补充 -->
