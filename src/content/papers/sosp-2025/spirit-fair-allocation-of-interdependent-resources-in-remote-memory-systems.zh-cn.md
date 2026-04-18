---
title: "Spirit: Fair Allocation of Interdependent Resources in Remote Memory Systems"
oneline: "Spirit 把 DRAM cache 与 remote-memory 带宽联合定价，让应用在运行时互换两者，在保持公平的同时比 DRF 最多快 21.6%。"
authors:
  - "Seung-seob Lee"
  - "Jachym Putta"
  - "Ziming Mao"
  - "Anurag Khandelwal"
affiliations:
  - "Yale University"
  - "UC Berkeley"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764805"
code_url: "https://github.com/yale-nova/spirit"
tags:
  - memory
  - disaggregation
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Spirit 认为，透明 remote memory 系统里的公平目标不该是平均切分 DRAM cache 和 remote-memory 带宽，而该是让应用获得公平的数据访问吞吐。它的 Symbiosis 分配器给每个应用相同预算，再根据竞争情况联合定价两类资源，并用运行时估计出的性能曲面让应用在 cache 与带宽之间做交换，同时保持强公平性。

## 问题背景

基于 swap 的 remote memory 很有吸引力，因为它让未修改应用也能突破本地 DRAM 容量: 热数据留在本地 DRAM cache，冷数据 miss 后经网络从远端取回。但在多租户部署里，性能并不只取决于“给了多少内存”，而是同时取决于两类资源: 本地 cache 容量，以及 miss 发生时可用的 remote-memory 带宽。更麻烦的是，这两类资源并不独立。对 cache-sensitive 的 key-value store 来说，只要多拿一点 DRAM，网络流量就可能明显下降；对 streaming workload 来说，即使 cache 增加，它仍可能主要受带宽限制。

这直接击穿了 DRF 一类传统多资源公平机制的前提。DRF 假设每种资源的需求是固定的、彼此独立的，而且应用能事先说明这些需求。Spirit 证明 remote memory 场景通常不满足这些条件: 很多不同的 `<cache, bandwidth>` 组合都可能带来相近吞吐，最优组合依赖 workload，而且会随时间变化。如果系统仍然要求应用申报需求，最理性的行为就是把两类资源都尽量多要，最终退化为静态切分。论文的动机实验就展示了这一点: Stream 在 `<100%, 75%>` 和 `<40%, 100%>` 这样的分配下都能维持相近吞吐，而 Memcached 与 SocialNetwork 则明显更依赖 cache，DLRM 几乎不受两类资源影响。

## 核心洞察

论文最重要的观点是: 公平应当围绕应用实际得到的性能来定义，而不是围绕资源份额来定义。如果每个应用都拿到相同预算，再把预算花在最能提升自己吞吐的 cache-bandwidth 组合上，那么价格就会成为两类可替代资源之间的交换比。cache-sensitive 的租户自然会买更多 cache，bandwidth-sensitive 的租户会买更多带宽，而混合型 workload 会随着竞争状态调整取舍。

这个重述之所以关键，是因为它把问题从“让用户提前报需求”变成了“让市场出清”。Spirit 不要求用户提交自己的效用曲线，而是自己在运行时估计每个应用的局部性能函数 `f_i(c, b)`。正因为如此，系统才能在不信任用户申报的前提下，同时维持 sharing incentive、envy-freeness 和 resource Pareto-efficiency。

## 设计

Spirit 分成三层: Symbiosis 分配器、用于估计 `f_i(c, b)` 的运行时模型，以及运行在传统 swap-based remote-memory 栈旁边的数据面。

Symbiosis 是一个受 CEEI 与 Walrasian pricing 启发的拍卖式分配器。系统把 cache 容量 `C`、带宽 `B`、总信用额和资源价格都归一化；每个应用获得 `1/N` 的预算，并满足 `p_c + p_b = 1`。给定当前价格向量后，每个应用都求解一个受预算约束的 `argmax f_i(c, b)`。如果所有竞价加总后 cache 超卖，Spirit 就提高 cache 价格；如果带宽超卖，就提高带宽价格。由于在归一化预算下，每个应用始终买得起静态公平份额，所以最终分配保留 sharing incentive；而相同价格和相同预算保证 envy-freeness，市场出清则给出 resource Pareto-efficiency。

理想化求解会很贵，因为 `f_i` 可能是非线性、非凸、甚至不可微的。于是实现采用 PTAS。Spirit 用 `epsilon = 1/200` 把 cache 和带宽离散化，相当于在一个 `200 x 200` 的网格上搜索，再把实际搜索范围缩到当前分配附近的 plus or minus `5 epsilon`，因为估计器在这一局部区域最准确。

估计器是除拍卖机制外最有技术含量的部分。Spirit 不去构造完整的 reuse-distance miss-ratio curve，而是从采样到的内存访问里拟合一个幂律 page-popularity 函数 `g(x)`。它用 Intel PEBS 对 LLC miss 采样，采样频率是每 25 次访问取 1 个样本，然后基于这些样本构建页面热度直方图，并做两阶段 gradient descent 拟合: 第一阶段拟合采样到的访问分布，第二阶段再用当前 cache 大小下观测到的 miss ratio 进行校准。接着，Spirit 用目标 cache 大小下推导出的 miss ratio，加上当前 swap 带宽使用量，构造 slowdown 模型，把附近的 `<cache, bandwidth>` 目标点转换成相对吞吐估计。论文报告该估计过程平均最快可在 140 ms 内收敛。

数据面保持应用透明。每个应用运行在独立 Docker container 中。Spirit 通过 `perf` 统计 LLC misses per second，读取 swap 设备带宽作为 remote-memory 访问代理，用 container memory limit 控制 cache，用 cgroups 的 `io.max` 节流带宽。系统每 30 秒更新一次资源分配，每 5 个 epoch 刷新一次估计器。

## 实验评估

实验用 Intel Xeon 6252N 服务器模拟 AWS `m5a.8xlarge` 级别环境: 32 个 vCPU、128 GB 内存、7.5 Gbps 网络带宽，并故意把本地 DRAM 限制在 10-20 GB，让其余工作集落到 remote memory。主实验把 24 个应用实例分布到 4 台服务器上: 每台机器运行 3 个 Stream、1 个 Meta KVS Memcached、1 个 DLRM、1 个 SocialNetwork。Spirit 分别与 user-demand DRF、harvest-and-redistribute baseline、direct trading baseline 和离线 Ideal allocator 对比。

关键结果基本支撑了论文主张。相对 user-demand DRF，Spirit 让 Stream 吞吐提升 21.6%，让 cache-sensitive 的 Meta KVS 和 SocialNetwork 吞吐提升 5.9%-6.1%。它还把 Meta KVS 的 p99 延迟降低 16.8%，把 SocialNetwork 的 p99 延迟降低 6.1%；DLRM 因为本身是 compute-bound，结果几乎不变。Spirit 的表现已经非常接近离线 Ideal，而 Harvest 会因为短时性能信号噪声做出错误回收决策，Trade 虽然能比 Harvest 更聪明地交换资源，却会牺牲公平性，出现“帮了一类 workload、伤了另一类 workload”的情况。

灵敏度实验同样有说服力。当本地 DRAM cache 从 10 GB 翻倍到 20 GB 时，Spirit 在 Stream 上的收益从 21.6% 降到 7.6%，说明这种市场机制最擅长的场景是“资源足够稀缺以至于值得交换，但又没有稀缺到每个人都只能死守资源”。系统开销方面，在 24 个应用的设置下，Symbiosis 一次分配可在 1 秒内完成，平均消耗不到单个 CPU core 的 3.3%；即使扩展到 1,000 个应用，平均分配时间也仍在 20 秒以内。不过控制环并不算快: 当 workload 从 bandwidth-sensitive 变成 cache-sensitive 再切回来时，Spirit 最多需要约 5 分钟检测到 `f_i` 变化，再用约 5 分钟收敛到新的稳定分配。

## 创新性与影响

Spirit 的新意在于，它给透明 remote memory 增加了一个正式的公平层，而不是再发明一条更快的 paging path。相对 Infiniswap、AIFM、Canvas 这类系统，它的贡献是把 cache 与 remote-memory 带宽视为互依赖资源，并直接以实际吞吐为优化目标的 allocator。相对先前 market-based cache-sharing 工作，它真正新增的是对资源可替代性的显式建模，以及一个无需修改应用、可在生产风格 remote-memory 栈里运行的在线估计器。

因此，这篇论文的意义并不限于基于 RDMA 的 Ethernet swap。作者明确把 Symbiosis 定位为一种面向 cache-bandwidth 互依赖系统的通用机制，未来可延伸到 CXL 风格 disaggregated memory 以及其他共享 in-memory cache。更一般的启发是: 有些资源不该被看作彼此独立的静态配额，而应该被看作可以互换的资源包。

## 局限性

Spirit 的假设也就是它的边界。估计器假设 `f_i(c, b)` 对两类资源都是单调的，这与 LRU、LFU 一类策略兼容，但不覆盖任意非单调替换行为。它的估计也是刻意局部化的，所以实现只在当前工作点附近搜索，而不会恢复一个全局都精确的性能曲面。

这个原型还只面向单个共享 cache 和单条带宽池。weighted priorities、与 CPU 或 storage 分配器的分层协同、以及分布式多 cache 部署，都被留给了未来工作。更现实的约束是，Spirit 只有在“确实有东西可换”时才有明显收益: 如果所有应用都主要争抢同一种资源，或者资源要么极度充裕、要么极度匮乏，那么相对静态切分的提升会明显缩小。最后，它的控制环也不足以处理秒级突发 workload 变化。

## 相关工作

- _Gu et al. (NSDI '17)_ — Infiniswap 让基于 RDMA 的 remote memory 变得实用，但没有解决多个租户应如何公平共享由此形成的 cache 与带宽瓶颈。
- _Wang et al. (NSDI '23)_ — Canvas 为多应用 remote memory 提供隔离和自适应 swapping，而 Spirit 进一步补上了一个针对互依赖 cache 与带宽的正式公平分配层。
- _Majid and Lee (ASPLOS '14)_ — REF 把 market-style elasticity fairness 引入共享硬件资源，但它的固定效用模型无法表达 Spirit 这里 workload-specific 的 cache-bandwidth 可替代性。
- _Wang and Martinez (HPCA '15)_ — XChange 也使用市场机制做多资源分配，但它面向的是不同的硬件缓存场景，既没有 Spirit 这种 remote memory 设定，也没有 sharing incentive 保证。

## 我的笔记

<!-- 留空；由人工补充 -->
