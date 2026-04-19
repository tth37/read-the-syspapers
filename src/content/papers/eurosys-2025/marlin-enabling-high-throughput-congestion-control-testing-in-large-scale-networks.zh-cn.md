---
title: "Marlin: Enabling High-Throughput Congestion Control Testing in Large-Scale Networks"
oneline: "Marlin 把可编程交换机当吞吐放大器、把 FPGA NIC 当 CC 执行器，让可定制拥塞控制测试在 65,536 条流上跑到 1.2 Tbps。"
authors:
  - "Yanqing Chen"
  - "Li Wang"
  - "Jingzhi Wang"
  - "Songyue Liu"
  - "Keqiang He"
  - "Jian Wang"
  - "Xiaoliang Wang"
  - "Wanchun Dou"
  - "Guihai Chen"
  - "Chen Tian"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, China"
  - "School of Electronic Science and Engineering, Nanjing University, China"
  - "Shanghai Jiao Tong University, China"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3717486"
tags:
  - networking
  - datacenter
  - smartnic
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Marlin 把拥塞控制测试拆到两类设备上：FPGA NIC 负责每流 CC 逻辑和调度，可编程交换机负责把这些决策放大成真正的高吞吐流量。靠这套分工，一条 100 Gbps 控制链路就能在单个 Tofino pipeline 上驱动 1.2 Tbps 的 CC 流量，并支持 65,536 条并发流。

## 问题背景

云运营者真正需要的是一种上线前验证手段：既能比较不同 CC，也能调参数，还要在接近生产环境的网络里跑起来。仿真只能看趋势，抓不住实现错误、交换机或 NIC 的实际行为，以及部署时常见的参数误配。所以论文把问题收敛成三个硬要求：流量必须遵守 CC 行为，算法必须可定制，吞吐必须到数据中心规模。

现有方案通常只能满足其中两项。软件和 FPGA 测试器很灵活，但吞吐不够；交换机测试器和商业设备吞吐高，却不擅长跑用户自定义的 CC。作者的判断是，单一设备不可能同时兼得可编程性、足够高的包处理频率和 Tbps 级聚合吞吐，因此测试器必须做成异构协作系统。

## 核心洞察

Marlin 的核心洞察是把决策和放大分离。FPGA NIC 保存每流状态、执行 CC 算法、处理定时器，并决定下一包该由谁发；可编程交换机不运行 CC，只负责把这些小决策转成大量 `DATA` 流量。这个拆分成立，是因为控制包远小于数据包。按 1024B MTU 计算，100 Gbps 控制链路上的 `SCHE` 包约为 148.8 Mpps，而单个 100 Gbps 数据端口只有约 11.97 Mpps，于是一条控制链路就能喂满 12 个测试端口。剩下的问题，是如何把这条链路做成一个不失真、不乱序的反馈闭环。

## 设计

Marlin 定义了五类包。`SCHE` 是 FPGA 发出的 64 字节调度指令，告诉交换机下一次该为哪条流生成哪个包；`TEMP` 包在交换机内部按线速循环，充当模板；模板包在 egress 端取到元数据后被改写成真正的 `DATA` 包；回来的 `ACK` 再被压缩成 64 字节的 `INFO` 包送回 FPGA。换句话说，交换机只做模板展开和反馈压缩，不做 CC 算法本身。

交换机侧主要承担三件事：处理入站 `DATA` 并产生 `ACK`，把回程反馈改写成 `INFO`，以及在每个 egress 端口维护元数据队列，驱动 `TEMP` 向 `DATA` 的转换。队列必须放在 egress，这样模板包到某个端口时，只会取该端口自己的元数据，不会误取别的流的信息。

FPGA 这一边更像可编程传输引擎。`INFO` 包先进入按端口划分的 RX FIFO，随后 CC 模块从 BRAM 中取出该流状态，运行用 Vivado HLS 写成的算法逻辑，再生成调度、重传、定时器和日志动作。接口设计很克制：固定 intrinsic state，再加 64B 的自定义 CC 状态。论文用这一接口实现了 Reno、DCTCP 和 DCQCN。

系统之所以能跑到线速，靠的是两套控制。第一套是事件回流：只要一条流还允许发送，它的调度事件就会重新进入对应端口的 scheduling FIFO，作为 rescheduling event 循环使用，而不是每次都重跑完整 CC。这样能保证公平，也避免 FIFO 被同一条活跃流重复填满。第二套是按端口的频率控制：RX timer 限制 `INFO` 进入 CC 模块的速率，避免 BRAM 读改写冲突；TX timer 限制 `SCHE` 的发送速率，避免交换机端队列溢出。按 1518B MTU 计算，安全上限是每端口 8.127 Mpps。

因此，一个 Tofino pipeline 可以把 12 个 100 Gbps 端口留给测试流量，其余端口承担控制和 loopback 路径。这样单个 pipeline 加单个 100 Gbps FPGA 端口就能做到 1.2 Tbps。

## 实验评估

实验先证明系统是对的，再证明它够大。正确性部分里，作者让单条 DCTCP 流经历人为注入的丢包和 ECN 标记，再把 Marlin 记录下来的 `cwnd` 和 `alpha` 变化与 ns-3 对比，关键状态转移是对得上的。调度层面也符合预期：单端口多流会公平分掉 100 Gbps，多端口各跑一条流时，每个端口都能独立跑到 100 Gbps。

真正出现拥塞时，系统仍然表现得像目标算法本身。多端口流量汇聚到一个 100 Gbps 瓶颈后，DCTCP 和 DCQCN 都会逐步均分带宽，其他流结束后，剩余流又能把空出的带宽吃回去。保真度实验更关键。作者把 Marlin 上实现的 DCQCN 和 Mellanox ConnectX-5 在 2-cast-1、3-cast-1 的 RDMA Write 场景下做对照，使用同样的 WebSearch 流量模型，结果 FCT CDF 很接近，说明 Marlin 不只是快，而是真的保留了 CC 行为。

规模结果是整篇论文最醒目的数字：Marlin 在每个端口上都接近线速，总吞吐约 1.2 Tbps，并稳定支持 65,536 条并发流。在这个规模下，DCQCN 仍然比 DCTCP 更适合短流，这也说明测试器没有把算法间真正重要的差异洗掉。

## 创新性与影响

Marlin 的贡献不是发明新的 CC 规则，而是提出一种新的测试器分工：可编程端点负责每流控制，交换机负责吞吐放大。也因此，它第一次把三件过去难以兼得的事情放到一起：流量真的遵守 CC、算法可以替换、吞吐达到 Tbps 级。对运营者而言，这是一种上线前比较算法和参数的白盒工具；对研究者而言，这是一种能把 CC 验证推到更大规模的实验平台。最可能被后续工作复用的，是这种「交换机做放大器」的架构思路。

## 局限性

Marlin 不是对所有 CC 都同样友好。它最适合每包 sender-side 逻辑比较轻、能塞进 FPGA 时序预算里的算法。论文提到，像 Cubic 这种即便优化后，单包处理仍要约 100 个时钟周期，单流线速就很难维持。实验覆盖的实现算法也只有 Reno、DCTCP 和 DCQCN，最强的保真度证据主要还是 DCQCN。

另外，它故意忽略 payload 语义和大量高层协议逻辑，所以非常适合隔离地研究 CC，却不适合排查真实应用栈之间的交互问题。部署成本也不低：需要可编程交换机、FPGA NIC，以及足够大的片上存储来容纳每流状态。论文里 65,536 条流已经用了 72 Mb 的 BRAM，继续扩展仍然依赖具体硬件资源。

## 相关工作

- _Chen et al. (NSDI '23)_ - Norma 同样利用可编程交换机做高吞吐网络负载测试，但它不生成带有拥塞控制行为的流量，也不提供可替换的 CC 逻辑。
- _Zhou et al. (CoNEXT '19)_ - HyperTester 证明了可编程交换机可以做高性能流量生成，而 Marlin 往前走了一步，把 FPGA 执行的反馈闭环接进来，让流量真正跟随 CC 动态变化。
- _Arashloo et al. (NSDI '20)_ - Tonic 关注的是在 FPGA NIC 上做可编程传输协议，本质上是端点卸载；Marlin 则把 FPGA 的可编程性和交换机的高吞吐拼起来，目标是 Tbps 级测试器。
- _Boo et al. (ISCA '23)_ - F4T 展示了 FPGA 上的全栈 TCP 加速，而 Marlin 把 FPGA 主要用于每流控制，把吞吐扩展交给交换机完成。

## 我的笔记

<!-- 留空；由人工补充 -->
