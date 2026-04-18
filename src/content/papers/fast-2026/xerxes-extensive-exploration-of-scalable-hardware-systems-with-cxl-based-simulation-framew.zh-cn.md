---
title: "Xerxes: Extensive Exploration of Scalable Hardware Systems with CXL-Based Simulation Framework"
oneline: "Xerxes 用图式路由、设备侧一致性和细粒度 PCIe 总线建模，在硬件缺位时就能评估 CXL 3.1 拓扑、DMC 与全双工传输的取舍。"
authors:
  - "Yuda An"
  - "Shushu Yi"
  - "Bo Mao"
  - "Qiao Li"
  - "Mingzhe Zhang"
  - "Diyu Zhou"
  - "Ke Zhou"
  - "Nong Xiao"
  - "Guangyu Sun"
  - "Yingwei Luo"
  - "Jie Zhang"
affiliations:
  - "Computer Hardware and System Evolution Laboratory"
  - "Peking University"
  - "Xiamen University"
  - "Mohamed bin Zayed University of Artificial Intelligence"
  - "Institute of Information Engineering, Chinese Academy of Sciences"
  - "Huazhong University of Science and Technology"
  - "Sun Yat-sen University"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/ChaseLab-PKU/Xerxes"
tags:
  - hardware
  - memory
  - disaggregation
  - networking
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Xerxes 是一个面向未来 CXL 特性的模拟框架，目标不是复刻一个已知设备的延迟曲线，而是把 port-based routing、device-managed coherence 和 PCIe 全双工传输这些尚未广泛落地的机制真正模拟出来。它的关键做法是把 fabric 建成图结构、把各类端点都建模成主动参与者，从而让拓扑、协议和链路层效应通过一阶机制自然涌现。

## 问题背景

这篇论文抓住的是 CXL 研究里一个非常现实的断层。CXL 3.x 想支持的是机架级的计算与内存池化、设备之间的直接通信，以及由设备自己发起和维护的一致性流程；但研究者今天能接触到的硬件大多还停留在早期代际，规模有限、模式偏 host-centric，很难揭示未来大规模 fabric 的真实行为。

现有方法各有硬伤。基于 NUMA 的仿真只能粗略逼近远端内存时延，却继承了 socket 数量上限，也无法体现 CXL 与传统 UPI/NUMA 在协议上的差异。MESS、CXLMemSim 这类 behavioral simulator 虽然更轻量，但它们依赖预先测得的 latency-bandwidth 曲线，因此只能重放一个已知设备的效果，无法预测一个从未做出来的新拓扑或新一致性机制。传统体系结构模拟器则在问题划分上就不适配：计算导向的模拟器默认中心化内存层次，网络导向的模拟器擅长拓扑却不理解内存语义与一致性流量。结果是，像“树形 CXL fabric 是否会在 root 处崩溃”“设备侧 snoop filter 应该怎样淘汰条目”“PCIe 全双工到底在什么条件下有收益”这类由 CXL 3.1 引出的核心设计问题，仍然缺乏定量答案。

## 核心洞察

论文的核心命题是：要做可预测的 CXL 模拟，必须把“互连”与“设备行为”拆成两个彼此独立但紧密配合的抽象。前者要把连通性和路由当成图问题，后者要把 host、accelerator 和 memory device 都视为主动 peer，而不是被动外设。只有这样，port-based routing 和 device-managed coherence 才不再是塞进 host-centric 模型里的补丁，而会成为由路由、端点状态与协议交互共同决定的自然结果。

这也是这篇论文真正有价值的地方。它不是笼统地说“更多细节更好”，而是在强调性能差异恰恰产生在多个边界的交互处。PBR 会改变哪些路径拥塞；DMC 会改变由谁发起一致性流量、失效延迟出现在哪一侧；PCIe 全双工会改变混合读写对链路方向性的利用方式。单纯注入平均延迟的模型看不到这些联动，而显式建模 bus、switch、coherence command 和 endpoint 行为的框架则可以。

## 设计

Xerxes 由 interconnect layer 和 device layer 两层组成。interconnect layer 在初始化时把系统拓扑构造成一张图，并向所有组件提供路由信息。默认路由采用 shortest path，而 switch 还能直接查询拓扑图并生成自己的 forwarding table。这样一来，chain、tree、ring、spine-leaf、fully-connected 等非树形结构都变成配置项，而不是写死在模拟器里的层级结构。

device layer 则把所有参与者统一建模成主动 agent。一个 requester 内部包含 request queue、地址翻译与交织单元，以及 cache coherence management 单元，因此既可以发合成流量，也可以回放 trace、维护私有 cache 状态，并响应 back-invalidation snoop。互连侧的 bus 模型会分别跟踪两个方向上的传输并独立分配带宽，从而显式体现 PCIe 全双工；switch 模型实现的是 PBR 风格的端口转发，而不是 PCIe 式的层级转发。

在 device-managed coherence 上，Xerxes 还给出了一个具体的设备侧 snoop filter，实现方式类似 DCOH。这个 snoop filter 会记录 cacheline 的 owner 与 sharer，在冲突时发出 `BISnp`，在条目不足时执行 victim selection，并在需要时等待 `BIRsp` 完成失效流程。因为这部分逻辑被模块化了，研究者就能系统性地比较 victim-selection policy 或 `InvBlk` 长度，而不是只能接受一个固定的 coherence controller。论文还展示了与 gem5、DRAMsim3、SimpleSSD 的集成方式：Xerxes 负责 CXL fabric 独有的路由、交换与一致性行为，其他模拟器继续负责更细致的 endpoint 模型。

## 实验评估

这篇论文的验证部分比常见模拟器论文更扎实，因为它并没有把基线故意设弱。作者用一台双路 Xeon Gold 6416H 服务器加 Montage CXL 2.0 memory expander 做实机校准，同时也把同一套硬件测得的 latency-bandwidth 数据喂给 MESS 和 CXLMemSim。即便在这种对 behavioral simulator 很有利的条件下，Xerxes 仍能把 loaded-latency 曲线的平均误差压到 `4.3%`，把 PBR 路径时延的平均预测误差控制在 `10.4%`，把 DMC 脏写所引入的额外 back-invalidation 往返延迟误差控制在 `1.4%`。在 SPEC CPU2017 的端到端实验中，Xerxes 在 `gcc` 上对 CXL 带来的执行时间开销预测与实机相差仅 `0.7%`，而 NUMA emulation、gem5-garnet 和 behavioral tool 的偏差更大。

真正体现 Xerxes 价值的是 design-space exploration。拓扑实验显示，chain 和 tree 会被关键 bridge 路径卡死，带宽上限基本受一个端口约束；ring 大致能到 `2x` 端口带宽；spine-leaf 能做到大约 `N/2` 倍；fully-connected 则能达到 `N` 倍，因为请求方之间存在直接路径。在真实 trace 上，ring 相对 chain 的吞吐最高可提升 `1.72x`，而 spine-leaf 与 fully-connected 最高可达 `3.63x`。在 DMC 策略上，`LIFO` snoop-filter victim policy 相比 `FIFO` 可把带宽提升 `5%`、平均延迟降低 `15%`、失效次数减少 `16%`，原因在于到达 snoop filter 的请求大多是针对冷数据的 miss，而不是热点重访。协议层面上，`InvBlk` 长度为 `2` 最划算：一次失效多清几行是有收益的，但继续增大长度会被额外的本地 cache 访问与 BISnp 流量竞争抵消。最后，全双工分析说明了为什么物理层细节不能省略：当 header overhead 为零时，`1:1` 的读写混合几乎能把带宽翻倍；当 header 长度增长到与 payload 相当时，这个收益会消失。论文选择的 workload 也确实打在它宣称的瓶颈上，因此实验基本支撑了核心论点。

## 创新性与影响

这篇论文的新意，不是抽象地“做了一个 CXL memory simulator”，而是给未来 CXL fabric 提供了一个从拓扑、交换、一致性到链路传输都显式建模的预测性框架。相对于 behavioral CXL simulator，Xerxes 模拟的是性能变化的原因，而不只是最后的延迟结果。相对于 NUMA emulation 和当前硬件测量，它研究的是尚未落地的 CXL 3.1 特性。相对于传统 host-centric 体系结构模拟器，它把一致性看成分布式、由 peer 直接驱动的过程。

因此，这项工作同时会影响多个方向。做 CXL 架构的人可以在芯片和系统还不存在时比较不同拓扑与一致性设计。做内存解耦、加速器池化或者新型 endpoint 的系统研究者，也可以把自己的 device model 接进来做端到端探索。就贡献类型而言，这既是一篇机制论文，也是一篇基础设施论文：前者体现在“两层式 graph-plus-peer 建模”，后者体现在它把未来 fabric 问题从猜测变成了可实验对象。

## 局限性

它最大的局限在于，最有意思的 CXL 3.1 特性目前还没有真实硬件可对照。Xerxes 的校准来自一个真实的 CXL 2.0 memory expander 平台，但对 PBR 和 DMC 的正确性验证主要依赖理论时延模型，而不是硅后测量。这在现阶段是合理的，但也意味着关于未来 fabric 准确性的最强证据，仍然是“与作者自己的组件模型一致”，而不是外部 ground truth。

此外，Xerxes 的细粒度是有选择的。它在本文关心的问题上建模得很细，例如 switch、bus、requester 行为和 snoop-filter 状态；但在 endpoint 微结构层面，它仍大量依赖集成的 backend simulator 或 trace replay。若干策略实验也带有刻意简化的 workload 设定，例如 hot/cold 倾斜访问模式、或用于全双工分析的合成读写混合流量。论文也没有进一步研究 adaptive routing、故障处理，或在真实大规模软件栈上的复杂性。这些缺口不会推翻当前结论，但会把它的适用范围限定在“面向特定架构问题的高保真探索框架”，而不是一个无所不包的机架级 CXL 全系统模型。

## 相关工作

- _Esmaili-Dokht et al. (MICRO '24)_ - MESS 用校准后的 latency-bandwidth 行为做应用画像，而 Xerxes 显式建模 switch、bus 与 coherence transaction，用来预测未出现过的 fabric 设计。
- _Sun et al. (MICRO '23)_ - _Demystifying CXL Memory_ 关注真实 CXL-ready 系统的测量与拆解；Xerxes 借助真实硬件做验证，但目标是继续外推到当前设备尚不支持的拓扑和一致性模式。
- _Gouk et al. (USENIX ATC '22)_ - _DirectCXL_ 研究的是现有 CXL 硬件上的内存解耦，而 Xerxes 探索的是带有 PBR 与 DMC 的未来系统设计空间。
- _Tang et al. (EuroSys '24)_ - 面向 ASIC 的 CXL memory 优化研究聚焦单一硬件设计点，而 Xerxes 提供的是比较更广泛拓扑与协议方案所需的模拟基座。

## 我的笔记

<!-- 留空；由人工补充 -->
