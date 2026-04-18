---
title: "CellReplay: Towards accurate record-and-replay for cellular networks"
oneline: "CellReplay 同时记录蜂窝链路在轻负载和重负载下的行为，并在回放时在两条轨迹间插值，把应用性能复现偏差显著压低到 Mahimahi 之下。"
authors:
  - "William Sentosa"
  - "Balakrishnan Chandrasekaran"
  - "P. Brighten Godfrey"
  - "Haitham Hassanieh"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "VU Amsterdam"
  - "Broadcom"
  - "EPFL"
conference: nsdi-2025
code_url: "https://github.com/williamsentosa95/cellreplay"
tags:
  - networking
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文认为，想把蜂窝网络做成高保真的 record-and-replay，不能只录一条 saturator 轨迹。CellReplay 同时记录 light packet train 和 heavy saturator 两种工作负载，单独追踪时变 base delay，并在回放时在两类轨迹之间插值。对 web browsing、file download 和 ABR streaming 来说，它都比 Mahimahi 明显更接近真实网络。

## 问题背景

在真实蜂窝网络上做应用评测既慢又难复现。吞吐和时延会随信号强度、干扰、移动性和运营商调度变化，所以想得到稳定结论，往往必须做大量重复实验。这也是为什么很多系统论文和应用开发者会依赖 record-and-replay：先在野外录一条轨迹，再在本地重放，希望在“同样的网络条件”下对比不同应用或协议。

论文指出，现代最常用的做法，也就是 Mahimahi 风格的回放，在蜂窝网络上会产生系统性偏差。Mahimahi 通过持续用 MTU-sized packet 把链路打满，记录 packet delivery opportunities，也就是 PDO，再在回放时加一个固定 propagation delay 来释放数据包。作者证明这里有两个根本问题。第一，蜂窝网络的 base RTT 不是固定值。即使在静止且信号良好的环境里，Mahimahi 仍会把中位 RTT 低估 16.88% 和 13.25%，因为 PDO 里的空档只能部分反映时延变化，而稀疏应用流量可能刚好绕开这些 blackout period。第二，可获得带宽会依赖工作负载本身。论文在 Verizon 上测到，100-packet train 的 delivery rate 是 10-packet train 的 2.6 倍，train completion time 相比 saturator 所暗示的固定带宽模型最多能偏离 35.8%。也就是说，用一条重负载轨迹去回放轻负载或 bursty workload，结果天然会偏快。

这种偏差并不只是数字上“有点不准”。论文报告 Mahimahi 在网页加载上平均会带来 17.1% 的 page load time 误差，在 250 KB 文件下载上误差甚至达到 49%。更糟的是，它可能直接改变实验结论，作者在后面的 ABR case study 里就给出了例子。问题本质在于，蜂窝网络同时暴露时变 delay 和 workload-conditioned bandwidth，而先前工具等于默认“一条重负载探针可以代表所有应用”。

## 核心洞察

论文最重要的判断是，要做 faithful 的 black-box replay，并不需要反推出运营商内部调度器，但必须把 Mahimahi 混在一起处理的两类现象拆开。Base delay 应该被当作单独的时间序列直接记录，因为即便在稀疏流量下它也会变化。Delivery opportunity 则不能只在一种工作负载下测量，因为网络会根据请求它的 workload 形态分配不同的服务。

因此，CellReplay 只记录两个边界工作负载。一个轻量 packet-train probe 用来捕获 RTT 和 train 前段的 delivery 行为，而且尽量不把链路推入 full heavy mode；一个 saturator 用来记录长流最终会见到的 heavy-workload PDO。回放时，每个 burst 先按 light trace 开始，随着 packet sequence 增长再切到 heavy trace，出现空闲 gap 后再回到 light 模式。作者的论点不是说蜂窝调度器本身是线性的，而是很多真实应用流都可以被这两个边界条件之间的插值近似得足够好。

## 设计

CellReplay 的记录阶段采集三类轨迹：base delay、light PDO 和 heavy PDO。一台手机运行 packet-train probing workload。每隔 `G` 毫秒，客户端先在 uplink 连续发送 `U` 个 MTU-sized packet；服务端一收到第一个包，就在 downlink 回发 `D` 个连续的数据包。这样，接收端看到的相对到达偏移就构成了 light PDO，而从第一个 uplink 包发出到第一个 downlink 包返回的时间，则给出了当前 RTT 样本，系统再把它折半成 one-way base delay。另一台手机运行 saturator，持续以高于 bottleneck 的速率请求带宽，并记录 heavy PDO。之所以一定要两台手机，是因为单设备 saturator 会把队列填满，破坏 light-workload 测量；作者利用商用蜂窝网络里的 per-user queue separation 来隔离这两类探针，并实证确认两台设备仍能分别观察到 light 和 heavy 行为。

回放逻辑沿用了 Mahimahi shell 的接口形式，但内部控制完全不同。CellReplay 有 inactive 和 active 两种状态。当一个新 burst 的第一个包在回放时间 `t` 到达时，系统会查找时间不晚于 `t` 的最新 base-delay 样本和 light-PDO 样本，并在需要时对 delay 做线性插值。然后它把当前 delay 加到 light PDO 上，再把 heavy PDO 的后缀拼接在 light schedule 之后，形成临时的 PDO 调度。每个数据包除了要吃掉这段 base delay，还会额外加一个 `comp(s)` 的 packet-size compensation，因为论文测到不同 packet size 之间的 RTT 差异远大于纯序列化时间所能解释的范围。延迟完成后，数据包进入一个 byte queue，按临时 PDO 调度出队。如果队列连续 `F` 毫秒为空，系统就回到 inactive 状态；这样下一次 burst 又会重新从 fresh light trace 开始，而不会错误地一直停留在 heavy mode。

剩下的难点是参数怎么选。论文先通过随机化 packet-train 实验来标定 `U` 和 `D`，选择那个在“light trace 加 heavy suffix”后，对其他 train size 总体插值误差最小的 train length。然后通过逐步缩短 inter-train gap 来找到 `Gmin`，也就是还能保持 light-workload 行为的最小安全间隔。接着再由 train 清空所需时间推导 fallback timer `F`，用随机 packet-size RTT 测试得到 `comp(s)`，最后用标准的 max-min bottleneck-buffer 方法估计回放队列大小 `B`。

## 实验评估

这篇论文的实验设计比较扎实，而且对自己提出的系统也保持了足够克制。作者用同一套 client/server 机器、地理上很近的服务器，以及 randomized trials，把 live network 和 replayed network 的应用表现做对比；再用 Earth Mover's Distance 除以 live mean，得到应用层的 distribution error。工作负载覆盖 HTTP/1.1 和 HTTP/2 的网页加载、1 KB 到 10 MB 的随机文件下载，以及三个 ABR 算法的 startup phase；网络环境则覆盖 T-Mobile 和 Verizon 5G，以及 good stationary、弱信号、拥挤场所、walking 和 driving。

在 microbenchmark 层面，CellReplay 回放出的 RTT 分布和 live network 基本重合，而 Mahimahi 会持续低估 RTT。到应用层，网页加载的平均误差从 17.1% 降到 6.7%。对小文件下载，CellReplay 把 T-Mobile 上的平均误差从 8.4%-20.7% 压到 0.5%-3.5%，把 Verizon 上的误差从 7.9%-49% 压到 0.2%-22.4%。对中等大小文件，1 MB 和 10 MB 下载的平均 distribution error 分别是 9.14% 和 6.54%，而 Mahimahi 对应是 23.35% 和 17.06%。这些结果基本支撑了论文的中心论点：只要同时建模 variable delay 和 workload-aware PDO transition，就能比单一 saturator trace 更接近真实蜂窝网络。

更有价值的是，作者还展示了系统在“难场景”里的表现边界。在 basement 和拥挤图书馆中，CellReplay 分别把误差从 15.22% 降到 5.74%，以及从 22.51% 降到 8.47%。在 mobility 下，它仍优于 Mahimahi：walking 从 14.48% 降到 4.13%，driving 从 13.15% 降到 6.97%。不过这里收益缩小了，因为 driving 会引入 handover 相关的 packet drop，而 CellReplay 并没有显式回放这种丢包。ABR 用例尤其说明问题：Mahimahi 平均把 startup bitrate 高估 17.73%，并错误地把 BOLA 排成远优于 BB；CellReplay 把这种偏差降到 5.89%，对 live-network 下的算法排序也更忠实。

## 创新性与影响

这篇论文的创新点，不是提出新的 congestion-control algorithm，也不是去构建一个白盒的 RAN emulator，而是做出了一套更合理的 black-box replay substrate。它明确承认蜂窝网络有两个关键特性：delay 会随时间变化，bandwidth allocation 会依赖请求它的 workload。Mahimahi 代表了实用 record-and-replay 的第一代成功方案，但 CellReplay 说明，面对现代蜂窝网络，单一 saturator trace 这个假设已经过粗。Pantheon 这一类 calibrated emulator 也和它不同：前者是用固定参数去逼近一条路径，后者则是直接回放测得的时变 delay 和按 workload 切换的 delivery opportunity。

因此，这篇论文对 cellular transport、mobile application，以及任何会根据网络观测值自适应行为的系统都很重要。作者把代码和 traces 一并开源，也让它更像一个能被后续论文直接复用的评测底座。更广义地说，这篇论文提醒大家，方便的 replay setup 可能带来的不是“随机噪声”，而是会系统性推高或压低某类方案表现的方向性偏差。

## 局限性

CellReplay 仍然对网络做了不少简化。它不会显式记录和回放随机 packet loss，除非丢包来自队列溢出或人工配置的 drop rate，所以在 handover 导致 IP-level packet drop 的 mobility 场景下能力有限。它的 calibration 参数也是在每次录制前固定下来的，如果环境在长时间录制过程中显著变化，trace 的代表性就会下降。

两台手机的设计本身也是工程折中，而不是完美抽象。移动过程中，两台设备可能短暂连到不同 base station，或者在不同时间发生 handover，论文也说明 driving 场景确实出现过这种情况。最后，记录端使用的是 UDP probe，所以无法捕获依赖协议类型的 middlebox discrimination，例如针对 TCP 的特殊处理。更大的 Verizon 文件下载上仍然残留明显插值误差，也说明“两个边界工作负载”是一个强近似，而不是运营商内部策略的完整模型。

## 相关工作

- _Netravali et al. (USENIX ATC '15)_ - Mahimahi 让 HTTP record-and-replay 变得实用，而 CellReplay 可以看作是针对蜂窝网络场景，对其单一 saturator 假设做出的修正。
- _Noble et al. (SIGCOMM '97)_ - 最早的 trace-based mobile emulation 奠定了 record-and-replay 的基本思想，但它面对的是远早于 4G/5G 的无线环境，没有今天这种明显的 workload dependence。
- _Mishra et al. (CCR '21)_ - NemFi 也是 record-and-replay emulator，但它围绕 WiFi frame aggregation 建模；CellReplay 处理的则是蜂窝路径的时变特性和按 workload 变化的带宽分配。
- _Yan et al. (USENIX ATC '18)_ - Pantheon 从 trace 中校准参数化 emulator，而 CellReplay 直接回放实测的 delay 和 delivery opportunity，并让 workload 决定何时切换服务状态。

## 我的笔记

<!-- 留空；由人工补充 -->
