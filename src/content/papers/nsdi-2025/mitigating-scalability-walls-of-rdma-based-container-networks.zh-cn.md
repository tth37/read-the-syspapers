---
title: "Mitigating Scalability Walls of RDMA-based Container Networks"
oneline: "ScalaCN 用组合因果测试推断 RNIC 的隐藏瓶颈，并在 RDMA 容器网络触及规模墙前重组 offloaded flow tables，提前避开性能崩塌。"
authors:
  - "Wei Liu"
  - "Kun Qian"
  - "Zhenhua Li"
  - "Feng Qian"
  - "Tianyin Xu"
  - "Yunhao Liu"
  - "Yu Guan"
  - "Shuhong Zhu"
  - "Hongfei Xu"
  - "Lanlan Xi"
  - "Chao Qin"
  - "Ennan Zhai"
affiliations:
  - "Tsinghua University"
  - "Alibaba Cloud"
  - "University of Southern California"
  - "UIUC"
conference: nsdi-2025
category: datacenter-networking-and-transport
pdf_url: "https://www.usenix.org/system/files/nsdi25-liu-wei.pdf"
project_url: "https://scala-cn.github.io"
tags:
  - rdma
  - networking
  - datacenter
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ScalaCN 是一个面向 RDMA-offloaded container network 的灰盒系统：它从 RNIC 的通用 datapath 抽象中推断可能的瓶颈，预测性能何时会撞上规模墙，并在真正崩塌前重写 offloaded flow table 的组织方式。按照论文的生产负载结果，它解决了 82% 的已推断成因，把带宽提升到 1.4x，并将 packet-forwarding latency 降低了 31%。

## 问题背景

这篇论文研究的是一个此前很多容器网络论文都没有真正覆盖的部署区间：一个生产级 RDMA-offloaded container network，约有 8K 台主机、约 40K 个 RNIC、平均约 50 万活跃容器、峰值约 100 万容器。在这个规模下，RDMA 容器网络在中等负载时确实能带来明显收益，但性能并不会随着规模线性延伸。论文报告说，当活跃容器数从 40 万增长到 80 万时，端到端带宽最多会下降 87%，packet-forwarding latency 最多会上升 34 倍。

难点在于，这些故障并不表现为一个单一且容易定位的 bug。作者基于一年的持续监控，统计到 13,396 次与 RNIC 相关的性能问题，主要表现为八类症状：OVS 中重复 re-offload flow、driver 停滞或崩溃、flow state 维护缓慢、间歇性回退到软件转发、某些 flow 在新 mask 被加入后持续变慢、VF unbind 时 PCIe 故障，以及 VXLAN context 过多时 RNIC 失去响应。这些症状横跨 virtual switch、kernel driver 和硬件三层。

最直觉的反应当然是“找到 RNIC 的根因然后修掉它”，但论文的出发点恰恰是：云厂商通常看不到这些设备的内部。Commodity RNIC 的内部实现大多闭源，vendor 也不容易复现实打实的百万容器生产负载，而运营方又不能直接把生产 workload 提供给 vendor。因此真正的问题不只是“大规模 RDMA 容器网络会撞上规模墙”，而是“这个规模墙藏在一个运营方无法直接观察的设备里”。

## 核心洞察

论文最重要的判断是：即使没有完整 white-box 可见性，也仍然可以做出足够有用的诊断和缓解。对一个闭源 RNIC 来说，运营方至少知道它在这种环境里必须暴露哪些共性抽象：承载 RDMA verb 的 queue pair、负责 offloaded packet processing 的 embedded match-action switch、把 flow entry 分组的 matching mask，以及 VXLAN/forwarding 之类 action list。ScalaCN 先基于这些抽象构建候选 architecture model，再利用拓扑与 reachability 约束删去不可能的组合，最后逐维扰动 workload，就能推断哪些组件最可能位于关键 packet-processing path 上。

沿着这个过程，论文在被研究的 RNIC 上得到一个相当稳定的结论：性能断崖与 flow table 的组织方式高度相关，尤其与 queued in-flight packet 需要查询多少个 matching mask 强相关。也就是说，瓶颈并不只是抽象意义上的“flow 太多了”，而是新的 flow pattern 迫使 RNIC 在 packet-switching path 里依次检查更多 mask group，这种额外 query depth 再和 queue contention 叠加，最终一起拉低吞吐、抬高时延。一旦看清这一点，缓解手段就不再是等待硬件重构，而是直接重写 offloading schedule。

## 设计

ScalaCN 分为离线推理和运行时控制两个阶段。离线阶段执行 combinatorial causal testing。它首先把 RNIC datapath 抽象为 queue pair、eSwitch flow table、matching mask 和 action。若直接枚举，组件组合空间会爆炸；因此 ScalaCN 使用 topological restriction 做剪枝：凡是会造成 packet loop 或不可达目的地的候选组合都视为无效，只保留那些仍能正确送达数据包的组合。论文指出，这一步把搜索规模从原本的组合爆炸降低到了与 subnet 和 container 结构相关的二次多项式量级。

对每个有效 architecture model，ScalaCN 会注入真实和合成 workload，寻找与生产环境中相似的症状，然后做 local sensitivity analysis 和 permutation removal。前者逐一改变某个配置维度，例如 matching mask 的数量，观察问题是否缓解或恶化；后者则剔除那些并不会显著影响结果的维度，使关键路径更加具体。借助这个流程，系统可以推断：例如 matching-mask 数量增长是 S6 式持续慢 flow 的高概率成因，而 flow deletion 延迟或 counter 更新滞后则更可能解释 S1、S4、S5。

运行时预测并不依赖纯粹黑盒的 feature engineering，而是直接使用上面推断出的性能模型。ScalaCN 跟踪本地和远端 host 上，queued in-flight packet 平均需要执行多少次 matching-mask query；带宽用一个关于这两个 query 数的 radial basis function 拟合，时延则用线性模型拟合。论文报告的预测精度足以支撑主动控制：带宽 98.9%，时延 98.5%。

当预测到性能下降会超过经验阈值 5% 时，ScalaCN 会重组 offloaded flow table。核心机制是把 mask 划分为一个位于最前面的 exact-match hyper mask，以及其后的多级 cascading mask。新出现的 packet pattern 先进入 cascading mask，但足够热的具体 flow 会被激活到 hyper mask 中，这样之后的数据包只需支付一次快速 exact-match query。Cascading mask 再依据 locality score 重新排序，这个分数由 mask 的具体程度和近 60 秒匹配到的 packet 数共同决定；aged entry 用 LRU 淘汰，未来可能出现的 flow 还可以通过 Gaussian mixture model 进行预热。整个过程改变的是 offloaded rule 的查询结构，而不是网络语义。

## 实验评估

实验同时覆盖一个 50-host 的中等规模 RCN 和真实生产负载，涉及六种 RNIC：NVIDIA ConnectX-4/5/6/7、BlueField-3，以及 Intel E810。微基准首先说明机制为何有效。在默认 offloading 策略下，随着 flow 数增长，各类 RNIC 的带宽都会明显下滑；当 offloaded flow 达到 15K 时，ScalaCN 平均把 aggregated bandwidth 提升 40.4%，把 average packet-forwarding latency 降低 30.5%。论文还展示了像 CX-6 在约 8K flow 附近那样的阈值点，之后性能会更快恶化，这与前面“mask/query depth 导致非线性断崖”的解释是对上的。

预测结果同样关键，因为 ScalaCN 的目标是在崩塌前动作，而不是事后解释。Packet-queue utilization 的预测偏差最大只有 +2.82%，在此基础上得到的带宽和时延预测精度分别达到 98.9% 与 98.5%。相比之下，使用通用 flow feature 的基线 ML 方法偏差非常大。对这篇论文来说，这一点很重要，因为它的论点不是“相关性足够就行”，而是“解释性足够强，才能驱动可控的在线优化”。

运行代价是存在的，但被控制在可接受范围内。随着规模增大，startup delay 会增加，但大部分延迟仍然来自用户态 OVS；ScalaCN 在 startup-delay breakdown 里只占约 18%，driver 占约 12%。CPU 开销大体与 offloaded flow 数线性增长，最终收敛到单个 CPU core 的约 5%。在生产负载上，平均带宽提升 17%，平均时延降低 15%，而某些 RNIC 家族上的收益更高。论文也诚实地给出狭窄失利区间：通信很少、计算很重的任务可能出现不到 5% 的性能下降，而且只发生在其集群中不到 0.03% 的 RNIC 上。

## 创新性与影响

这篇论文的新意并不只是单独提出一个更快的 container datapath，而是建立了一条从症状、到 RNIC architecture 推断、到运行时预测、再到具体缓解策略的完整生产闭环。先前工作分别研究过 container overlay、RDMA 容器网络，或者 black-box RNIC 行为，但 ScalaCN 把这些理解真正变成了一个既能解释、又能规避大规模故障的运维方法。

它的工程影响也比较可信，因为这套闭环并没有停留在论文自证层面。Vendor 已经确认了论文报告的问题及其高概率成因，作者还说明其中几类问题已经通过 driver 或 firmware 更新得到修复，剩余问题也仍在协同处理中。因此 ScalaCN 更像是一种“今天先把现网跑稳，同时为明天的 RNIC 设计提供证据”的运营技术，而不是纯实验室里的优化器。

## 局限性

ScalaCN 推断的是“最可能的成因”，而不是形式化意义上的内部根因证明。作者明确承认，他们是从共性抽象出发逼近 architecture model 和 performance model，因为真实 RNIC 的实现是闭源的。因此，这种方法的可靠性依赖于抽象本身和后续验证闭环是否足够强。就这篇论文而言效果很好，但它仍然是 greybox 论证，而不是 source-level 解释。

它能优化的目标也有边界。ScalaCN 最擅长处理的是可配置 packet-processing structure 带来的损失，尤其是 flow-table query 和 mask 组织方式。如果真正的瓶颈来自 on-chip SRAM contention 或其他硬容量上限，论文也承认这最终还是需要硬件重构。工程上，ScalaCN 还需要持续监控、对 OVS offload 行为做改造，以及足够强的流量局部性，才能让 hyper-mask 方案始终划算。

## 相关工作

- _Kim et al. (NSDI '19)_ - `FreeFlow` 研究的是面向容器的软件虚拟 RDMA 网络，而 ScalaCN 关注的是已经在生产大规模部署的硬件 offloaded RDMA container network 何时、为何会失稳。
- _Kong et al. (NSDI '23)_ - `Understanding RDMA Microarchitecture Resources for Performance Isolation` 在受控环境下刻画 black-box RNIC 的资源行为，而 ScalaCN 推断 packet-processing critical path，并把这种解释直接用于在线缓解。
- _Yu et al. (SIGCOMM '23)_ - `Lumina` 通过 black-box 测量揭示 hardware-offloaded network stack 的微行为；ScalaCN 则额外引入 RNIC 特定抽象，并把解释结果转化成预测器和 flow-table 重组策略。
- _Wang et al. (NSDI '23)_ - `SRNIC` 提出新的可扩展 RNIC 架构，而 ScalaCN 的目标是在不重构硬件的前提下改善今天 commodity RNIC 的实际部署表现。

## 我的笔记

<!-- empty; left for the human reader -->
