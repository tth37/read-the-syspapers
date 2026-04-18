---
title: "TiNA: Tiered Network Buffer Architecture for Fast Networking in Chiplet-based CPUs"
oneline: "TiNA 保留 SNC 的本地低延迟收包路径，并在本地 LLC 的 DCA ways 填满时把突发流量溢出到远端 chiplet 缓冲区，避免长突发下的延迟陡升。"
authors:
  - "Siddharth Agarwal"
  - "Tianchen Wang"
  - "Jinghan Huang"
  - "Saksham Agarwal"
  - "Nam Sung Kim"
affiliations:
  - "University of Illinois, Urbana-Champaign, Urbana, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762224"
code_url: "https://github.com/ece-fast-lab/ASPLOS-2026-TINA"
tags:
  - networking
  - hardware
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

TiNA 关注的是 chiplet CPU 上一个很具体的失效模式：`SNC` 能把收包和处理都限制在本地 chiplet，因此短突发时延迟很低；但一旦突发长度超出本地 `DCA` 容量，延迟就会急剧恶化。论文的做法是默认把包放在本地 chiplet 缓冲区里，只有当本地 `LLC` 的 `DCA ways` 快装不下时，才把多出来的流量溢出到远端 chiplet 的缓冲区，同时用增强版 NIC 和 `DPDK` 栈维持包处理顺序。

## 问题背景

论文研究的是 Intel Sapphire Rapids 这类四 chiplet 服务器 CPU 上的微秒级网络处理。在默认的 non-`SNC` 模式下，核心可以使用整颗 socket 的 `LLC slices` 和 `DRAM controllers`，但很多内存访问都要跨一次甚至两次封装内互连，因此会多出几十纳秒延迟，也会带来更大的时延波动。对批处理负载来说这未必致命，但对 dataplane 来说，包处理往往就是一连串短小的内存访问，这些额外代价会直接体现在端到端 tail latency 上。

`SNC` 把这组权衡反过来了。它把每个 chiplet 暴露成一个 sub-NUMA node，让核心、`LLC`、`DRAM` 控制器和 `PCIe` 通道尽量保持本地化。对短突发而言，这非常有效：论文报告相较 non-`SNC`，`SNC` 最多可把 p50 和 p99 的包处理延迟分别降低 `45%` 和 `50%`。问题在于，`SNC` 同时也把包处理核心能看到的 `LLC` 容量和 `DRAM` 带宽缩小到大约整颗 socket 的四分之一。结合 `DDIO`/`DCA` 后，进入 NIC 的数据会先 DMA 写入特殊的 `LLC ways`；一旦突发期间活跃 `mbuf` 的总量超过本地 chiplet 的 `DCA` 容量，系统就会出现 `DMA leak` 和 `DMA bloat`，此时 `SNC` 反而会比 non-`SNC` 更差。

因此，核心问题并不是“`SNC` 和 non-`SNC` 谁更好”。真正的问题是：如何保住 `SNC` 在常见短突发下的本地低延迟路径，同时避免队列暂时堆高时因为本地 cache 预算耗尽而出现延迟断崖。

## 核心洞察

这篇论文最值得记住的观点是：在 chiplet CPU 上，自适应的对象不该只有 CPU 绑定位置，包本身的落点也应该动态调整。在 `SNC` 下，凡是 DMA 写入某个 chiplet 所属内存区域的包，就只会被缓存到该 chiplet 的 `LLC slices` 里。于是，网络栈就可以把本地 chiplet 和远端 chiplet 上的收包缓冲区视为两层 cache-backed buffer。

TiNA 的主张是，应该先尽量把流量放进本地 `DCA ways`，因为这能把处理延迟压到最低；只有当活跃 `mbuf` 规模再继续增长、马上会导致本地溢出时，才把额外的流量导向远端 chiplet 的 `DCA ways`。换句话说，TiNA 并不是在系统启动时一次性选择“全本地”或“全局摊开”，而是把瞬时的活跃 `mbuf` 大小转化成每个到达包的放置决策，让只有真正需要额外容量的那部分包去承担跨 chiplet 的代价。

## 设计

TiNA 分成两部分：位于 `DPDK` 中的 `TiNA-stack`，以及接收路径上的 `TiNA-NIC`。`TiNA-stack` 为每个处理核心分配 `N` 个 descriptor buffer，其中 `N` 是 chiplet 数量。一个 descriptor buffer 指向本地 chiplet 上分配的 `mbufs`，构成 `Local-tier`；其余 `N-1` 个 descriptor buffer 指向远端 chiplet 上分配的 `mbufs`，共同构成 `Remote-tier`。由于 `SNC` 会让每个内存区域只在对应 chiplet 中缓存，写入这些缓冲区的包就会稳定地落到本地或远端的 `DCA ways` 中。

放置策略是一个基于活跃缓冲区大小估计值的简单状态机。TiNA 维护 `A_local` 和 `A_remote`，分别表示当前两个 tier 中仍然活跃的字节数，再将它们与各自的 `DCA` 容量 `D_local`、`D_remote` 以及新到达包批次大小 `P` 做比较。系统初始处于 `local` 状态；如果 `A_local + P` 会让本地 `DCA ways` 溢出，就切到 `remote`；如果本地容量重新腾出来，或者继续放到 remote 也会溢出，就可以切回 `local`。为了让 NIC 不必等待软件精确重建队列状态，栈会周期性地把包消费速率 `C` 回传给 NIC；在论文的实现里，这个更新周期是 `100 us`。

真正棘手的是顺序保证。既然同一条包流可能被拆到两个 tier 中，TiNA 仍然必须按接收顺序把包交付给应用。做法是优先复用传输层已有的 sequence number；若底层协议没有，则由 `TiNA-NIC` 自己附加。`TiNA-stack` 只窥视各个 descriptor buffer 头部包的序号，记录这些序号后持续从头部序号最小的那个 buffer 中取包，直到另一个 buffer 应该接管为止。论文还把 remote 放置进一步分散到多个硬件队列上，使连续的一批包而不是单个包一起被 steer 过去，从而降低顺序检查开销，也减少对接收侧 batching 的破坏。

原型实现相当克制。`TiNA-NIC` 只用了大约 `500` 行 Verilog，运行在一块 Xilinx `U280` FPGA 上，以 bump-in-the-wire 的形式插在 ConnectX-6 前面，额外消耗约 `1k` 个 `LUTs` 和 `2k` 个寄存器。`TiNA-stack` 的修改则局限在 `DPDK` 库内部，不要求应用改写 API。

## 实验评估

实验首先证明这个问题不是纸上谈兵。在 SPR 服务器上，对于能装进单个 chiplet `LLC` 的 `2-15 MB` working set，`SNC` 可把内存访问延迟降低约 `45%`；但对于 `15-60 MB` 的 working set，由于更早溢出到 `DRAM`，`SNC` 最差会比 non-`SNC` 慢 `100%`。在网络微基准中，`SNC` 在约 `100 us` 的短突发下优于 non-`SNC`，在接近 `400 us` 处打平，之后随着本地 `DCA ways` 溢出而开始落后。论文还显示，在后续回放的端到端 trace 中，活跃 `mbuf` 总量超过本地 `2 MB` `DCA` 预算是很常见的，出现比例约为 `20-50%`。

在这个背景下，TiNA 的收益与机制是对得上的。对 `L2TouchFwd` 而言，TiNA 在 `250-400 us` 的突发范围内相较 `SNC` 可把 p99 再降低约 `8-10%`；在 `400-700 us` 范围内，则相较 non-`SNC` 再降低约 `5-10%`。而在极短或极长突发这些本来就没有太多优化空间的区间，它与更优基线的差距也大致控制在 `2%` 以内。随着 offered load 提升，TiNA 把延迟膨胀和丢包的出现位置推迟到接近 non-`SNC` 的水平，但在进入那个拐点之前，又能优先利用本地 `DCA ways`，因此常常比 non-`SNC` 更早阶段就取得更低延迟。

端到端结果最有说服力。跨 `L2TouchFwd`、`KVS`、`NAT`、`RSA` 四类应用与三条来自 hyperscaler 的 trace，TiNA 平均把 mean latency 和 p99 latency 相对 `SNC` 分别降低 `25%` 和 `18%`，相对 non-`SNC` 分别降低 `28%` 和 `22%`。不同应用的收益形态也符合直觉：`NAT` 的单包工作量很小，活跃缓冲区规模也小，所以它本来就在 `SNC` 下接近最优，TiNA 主要是相对 non-`SNC` 有帮助；`KVS` 的 tail 收益最大，p99 最多可下降约 `55%`，因为它同时受益于更大的有效 cache 容量、更低的本地访问延迟，以及对应用非 I/O 状态上 `DMA bloat` 的缓解；`RSA` 会制造更大的活跃 `mbuf` 规模，因此收益较小，这反而说明论文的解释是成立的：一旦所有设计都深陷溢出区间，再聪明的放置策略也很难创造太多额外空间。

我认为这些实验基本支撑了中心论点。基线比较是公平的，因为 `SNC`、non-`SNC` 和 TiNA 都运行在同一平台上；同时，作者既做了微基准，也做了完整应用，使得设计在哪些区间受益、在哪些区间趋于饱和都讲得比较清楚。

## 创新性与影响

相较 _Farshin et al. (EuroSys '19)_，TiNA 不是把包数据尽量摆到单个最佳 `LLC slice`，而是在 chiplet 粒度上引入动态的两层放置策略。相较 _Alian et al. (MICRO '22)_，它也不是在单一处理器层级内部做 inbound data orchestration，而是把 `SNC` 的本地性和 non-`SNC` 的总容量变成运行时可切换的选择。相较 _Smolyar et al. (ASPLOS '20)_，它并不通过改 `PCIe` 拓扑来消除 non-uniform `DMA`，而是在 `SNC` 下改变包最终写入哪一个 chiplet 支撑的缓冲区。

因此，这篇论文更像一篇真正提出新机制的系统论文，而不是单纯的测量研究。它为今后研究 NIC steering、cache 拓扑与软件 packet buffer 在 chiplet CPU 上如何协同，给出了一个很具体的接口与设计点。所有在新一代服务器 CPU 上做低延迟 dataplane 的工作，基本都会和它形成对话。

## 局限性

TiNA 依赖一些较强的平台前提：需要 `SNC`、需要 `DCA`/`DDIO`，还需要 NIC 有足够多的硬件队列，能够为每个处理核心分出 `N` 个队列。论文只在 Sapphire Rapids 级别的平台和 `100 Gbps` 环境下评估了它，因此它对其他 chiplet CPU 是否同样有效，目前更多还是合理推测，而不是直接证据。

此外，这个设计依赖的是活跃缓冲区大小的估计值，而不是 NIC 侧的精确观测，更新间隔 `I` 也需要调参。如果处理速率的变化比论文中的工作负载更剧烈，这个估计器就可能在短时间内把包放错 tier。顺序保证机制设计得很仔细，但它也确实带来了轮询多个 descriptor buffer 的额外开销；论文明确展示过，在突发极短或极长、几乎没有自适应空间的情况下，TiNA 可能会比最佳基线略差，不过幅度大约只有 `2%`。

最后，TiNA 不是应对极端过载的万能药。像 `RSA` 这样会把活跃 `mbuf` 推得很大的应用，会让所有方案都遭遇显著而不可避免的泄漏，因此 TiNA 的收益会收缩。论文也讨论了在 non-`SNC` 模式下使用 TiNA 的可能性，但结论是 split-`DMA` transaction 的代价太高，不值得采用。

## 相关工作

- _Farshin et al. (EuroSys '19)_ — CacheDirector 把包头尽量映射到最近的 `LLC slice`，而 TiNA 则在本地容量耗尽时，把溢出流量动态导向远端 chiplet 的 `DCA ways`。
- _Farshin et al. (USENIX ATC '20)_ — Reexamining Direct Cache Access 分析了高性能网络中的 `DMA leak` 问题，而 TiNA 把这些病理现象转化成 chiplet CPU 上的运行时放置策略。
- _Alian et al. (MICRO '22)_ — IDIO 关注的是处理器内部的 inbound network data orchestration；TiNA 关注的则是 `SNC` 下本地与远端接收缓冲区之间的 chiplet-aware tiering。
- _Smolyar et al. (ASPLOS '20)_ — IOctopus 通过改变 `PCIe` 连接方式来对抗 non-uniform `DMA`，TiNA 则保持商品化拓扑不变，只改变包被缓存到哪里。

## 我的笔记

<!-- 留空；由人工补充 -->
