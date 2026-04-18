---
title: "State-Compute Replication: Parallelizing High-Speed Stateful Packet Processing"
oneline: "SCR 把数据包轮转分发到多核，并在每个包上附带有界历史，让每个核本地重建流状态，从而把单条有状态流扩展到多核处理。"
authors:
  - "Qiongwen Xu"
  - "Sebastiano Miano"
  - "Xiangyu Gao"
  - "Tao Wang"
  - "Adithya Murugadass"
  - "Songyuan Zhang"
  - "Anirudh Sivaraman"
  - "Gianni Antichi"
  - "Srinivas Narayana"
affiliations:
  - "Rutgers University, USA"
  - "Politecnico di Milano, Italy"
  - "New York University, USA"
  - "Queen Mary University of London, UK"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
code_url: "https://github.com/smartnic/bpf-profile"
tags:
  - networking
  - smartnic
  - hardware
  - ebpf
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

SCR 通过轮转分发数据包并在每个包上附带一段有界历史，把单条有状态流扩展到多个核心处理。每个核心只需重放缺失的历史就能重建本地状态，因此既避开了锁争用，也避开了 RSS 分片“一条 flow 只能吃一个核”的上限。

## 问题背景

这篇论文面向 CPU 受限的高速软件包处理场景，例如负载均衡器、DDoS 缓解器、连接跟踪器，以及对 packets-per-second 很敏感的遥测服务。单核吞吐提升已经接近停滞，但 NIC 线速仍在持续上升，所以多核扩展已是刚需。

难点在于状态。共享状态并行依赖锁或原子操作，遇到热点流时会出现 cache bouncing 和同步崩塌；RSS 式分片虽然避免了显式共享，却把每条 elephant flow 永远限制在一个核心上。RSS++ 可以迁移分片来减轻失衡，但仍然不能把一条已经压垮单核的流拆给多个核心。论文要解决的是：既支持一般有状态更新，又不依赖流量分布，还能随着核心数增加而单调变好的方法。

## 核心洞察

论文最关键的观察是：正确性需要的是所有核心都重建同样的有序状态迁移，而不是把每个包都重新作为独立软件事件分发给每个核心。之所以有价值，是因为在高速包处理框架里，dispatch 往往比程序本身的计算更贵。

所以 SCR 复制的是状态和计算，而不是 dispatch。sequencer 把每第 k 个包交给某个核心，同时附带前面 k-1 个相关包的必要元数据；该核心先本地重放这些历史，把私有状态追平，再处理当前包。只要 dispatch 仍是主导成本，这种重复一点点计算的代价，就比锁争用或“一条 flow 绑死一个核”更低。

## 设计

设计从一个确定性的 packet-processing program 出发，把它视为有限状态机。每个核心维护一份私有状态副本。系统新增的 packet-history sequencer 能看到所有包，按 round-robin 方式把包喷洒到不同核心，并维护一个有界环形历史缓冲，只保存推进状态所必需的字段。这个历史只与核心数和元数据宽度有关，与活跃 flow 数量无关。

发给某个核心的每个包都带三样东西：原始包、一小段最近历史，以及指示最老历史项位置的 index 或 pointer。论文把历史放在修改后报文最前面，这样硬件能在固定位置写入，软件仍可把原始包视作一段连续区域来解析。在“交换机做 sequencer”的部署里，还会额外加一个 dummy Ethernet header，让主机 NIC 能正确接收改写后的报文。

SCR-aware 程序先按顺序重放 piggyback 的历史，把私有状态快进到当前，再处理真正分给该核心的包。因为所有核心最终都会看到同样的有序历史，所以这些私有副本能保持一致，而不需要显式跨核同步。

作者实现了两种 sequencer。在 Tofino 上，它基于寄存器保存环形索引并把历史读入包元数据；被索引指向的那一项会被当前包的新字段覆盖。在 NetFPGA-PLUS 上，它是一个 Verilog 模块，维护 `N x b` 历史数组和指针，把整段历史前缀到每个包上，然后更新一行并推进指针。对罕见的 sequencer 到 CPU 之间丢包，系统用序号和每核日志中的 `history`、`LOST`、`NOT_INIT` 状态来恢复缺失历史，而不是复制完整流状态。对非确定性程序，sequencer 可以提供时间戳；若程序依赖随机数，则不同核心应共享固定随机种子。

## 实验评估

实验平台是两台背靠背连接的 100 Gbit/s 服务器，使用 Intel Ice Lake CPU 和 ConnectX-5 NIC。被测机运行五个 XDP/eBPF 程序：DDoS mitigator、heavy-hitter monitor、TCP connection tracker、token-bucket policer 和 port-knocking firewall。流量来自 university datacenter trace、CAIDA backbone trace，以及用于双向 TCP connection tracking 的 synthetic hyperscaler datacenter trace。

在这五个程序上，SCR 是唯一一种在真实偏斜负载下仍能随着核心数单调扩展的方案。论文报告，在测试范围内，SCR 吞吐近似线性增长；而基于锁的共享状态在少量核心之后就会崩塌，RSS 和 RSS++ 则会在单条热点流超过单核能力后很快碰到天花板。关键不是“平均更快”，而是 SCR 真正去掉了分片方案保留下来的单条 elephant flow 瓶颈。

微架构计数器解释了原因。与共享状态相比，SCR 的 L2 hit ratio 更高、计算延迟更低，因为它不再承受锁争用和共享缓存行抖动。与 RSS 和 RSS++ 相比，SCR 在不同核心上维持了更高且更均匀的 retired IPC，因为工作不会困在少数热点流核心上。随着程序自身计算开销相对 dispatch 增大，SCR 的优势会收窄，这与论文的简单模型一致。

部署代价方面，启用丢包恢复会带来额外日志和同步开销，但 SCR 仍领先于各类基线。NetFPGA sequencer 在 1024-bit 数据通路上可满足 340 MHz 时序要求；当历史行宽为 112 bit 时，可以支持最多 128 个核心，而且 FPGA 面积占用很低。Tofino 版本受 stateful ALU 数量限制更强，但仍能保存 44 个 32-bit 历史字段。

## 创新性与影响

这篇论文的创新点首先是一条新的扩展原则：通过复制状态、重放有界历史，让单条有状态流也能跨多个核心扩展，而不需要锁，也不依赖按 flow 切分。此前大多数系统只能在“共享状态争用”和“shared-nothing 分片”之间二选一，SCR 打开了第三个设计点。

这对那些瓶颈在 packets-per-second 而不是 bytes-per-second 的软件数据通路尤其重要。如果未来 NIC 或可编程交换机愿意提供哪怕不多的 sequencing 支持，运营者就可能继续把 middlebox 逻辑留在软件里，同时跟上更高线速和更恶劣的流量偏斜。

## 局限性

SCR 依赖一些很强、但论文也明确承认的前提。程序必须是确定性的，或者通过 sequencer 提供时间戳、固定随机种子等方式被“变成”确定性。它还需要一个外部 sequencer，而今天的商品 NIC 并不直接提供这种能力，所以现实部署仍依赖可编程 NIC、可编程交换机或未来的固定功能支持。

另一个真实限制是 piggyback 历史带来的字节开销。额外元数据会增加 DDIO 和 cache 压力，占用更多 PCIe 带宽，并可能让瓶颈从 CPU 转移到 NIC；论文在一个配置中展示了这种情况会在大约 11 个核心后出现。最后，SCR 最适合 dispatch 主导成本的程序。如果程序本身计算越来越重，那么为了追历史而重复做的工作就会变得不划算，扩展收益也会逐渐消失。

## 相关工作

- _Barbette et al. (CoNEXT '19)_ — `RSS++` 通过在核心间迁移 flow shard 来改进负载均衡，但它仍然无法把一条过载的有状态流拆给多个核心。
- _Pereira et al. (NSDI '24)_ — software network function 的自动并行化仍然是 flow-oriented，而 SCR 复制计算，是为了并行化单条 flow。
- _Katsikas et al. (NSDI '18)_ — `Metron` 关注以接近底层硬件速度执行 NFV service chain，但其扩展模型仍建立在跨 flow 分配工作上，而不是在每个核心上重放有界历史。
- _Sadok et al. (HotNets '18)_ — 在 software middlebox 中喷洒数据包的思路强调均匀分发，而 SCR 额外补上了状态重建机制，使“每包都可能更新状态”的程序也能正确执行。

## 我的笔记

<!-- 留空；由人工补充 -->
