---
title: "Enabling Efficient GPU Communication over Multiple NICs with FuseLink"
oneline: "FuseLink 通过把 GPU 流量经由 NVLink 转发到 relay GPU，并在运行时把发送调度到 direct 与 indirect NIC，汇聚原本空闲的 NIC 带宽。"
authors:
  - "Zhenghang Ren"
  - "Yuxuan Li"
  - "Zilong Wang"
  - "Xinyang Huang"
  - "Wenxue Li"
  - "Kaiqiang Xu"
  - "Xudong Liao"
  - "Yijun Sun"
  - "Bowen Liu"
  - "Han Tian"
  - "Junxue Zhang"
  - "Mingfei Wang"
  - "Zhizhen Zhong"
  - "Guyue Liu"
  - "Ying Zhang"
  - "Kai Chen"
affiliations:
  - "iSINGLab, Hong Kong University of Science and Technology"
  - "University of Science and Technology of China"
  - "MetaX Integrated Circuits"
  - "Massachusetts Institute of Technology"
  - "Peking University"
  - "Meta"
conference: osdi-2025
tags:
  - gpu
  - networking
  - rdma
  - ml-systems
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

FuseLink 让一块 GPU 能通过多张 NIC 做跨机通信，方法是把 NVLink 相连的 peer GPU 当作 relay。它把 NCCL 缓冲区重映射到 relay GPU 上，再按 worker 优先级调度被借来的 NIC，因此额外带宽不会长期抢占 NIC 原属 GPU 的资源。论文在 8 GPU、8 张 400 Gbps NIC 的服务器上做到 212 GB/s 的跨机 GPU 带宽。

## 问题背景

GPU 服务器通常是“每块 GPU 一张好 NIC，外加若干条更差的间接路径”。NCCL 一类通信栈因此倾向于维持静态的 GPU-NIC 绑定。可一旦流量失衡，这种策略就会浪费带宽：分离式 LLM serving 的请求长度和到达时间变化很大，expert-parallel MoE 的 token routing 会造成不均衡的 all-to-all，DLRM 的 embedding 流量也会在不同 worker 之间摆动。论文测得，分离式 serving 的平均 NIC 利用率只有 13%-53%，MoE 只有 29%-65%。

把流量直接均匀分到所有 NIC 上并不安全。发送端 GPU 仅靠 PCIe 无法高效驱动所有 NIC，借用 peer GPU 的 NIC 又可能抢走对方的带宽或显存。因此，FuseLink 的目标不是泛泛地“多用几张 NIC”，而是在不改应用代码、也不伤害 direct-NIC 所有者的前提下，把空闲 NIC 变成可用带宽。

## 核心洞察

论文的核心主张是，应把机内 GPU fabric 看成机间通信路径的一部分。只要忙碌的 GPU 能先经由 NVLink 把数据送到一块拥有空闲 direct NIC 的 peer GPU，再由那张 NIC 发出，节点就能聚合那些原本被坏 PCIe 路径困住的带宽。

要让这件事真正可用，关键不在于重新设计传输协议，而在于把“路径重定向”和“性能隔离”配对起来。虚拟内存重映射让 NCCL 现有缓冲区可以物理驻留在 relay GPU 上，而带优先级的调度则保证 direct NIC 的所有者能迅速收回它。

## 设计

FuseLink 以 NCCL 下层网络层的形式实现。它截获 proxy thread 的 connect、register、send 和 receive 调用，在启动时探查拓扑，并为每个 GPU-NIC 组合选择 direct path 或 router GPU。

它最关键的数据路径机制是“通过重映射做 relay”。FuseLink 不走 CPU copy 或 host-memory staging，而是把网络缓冲区的虚拟地址重映射到 relay GPU 的显存上。应用填充缓冲区时，写入就会直接经由 NVLink 落到 relay 显存，省掉一次额外拷贝和一次 RDMA 前同步。接收端也可以先把数据落到拥有最佳 NIC 路径的 GPU 上，再把最终目标地址重映射给真正的消费者。

控制路径则是 credit 驱动的。接收端把空闲 NIC 编进 credit；发送端结合远端空闲信息和本地 NIC 状态，选择 direct NIC、空闲 indirect NIC，或者回退到 direct NIC。每块 GPU 在自己的 direct NIC 上始终拥有最高优先级；投递到 indirect NIC 的 outstanding request 数也被限制；relay 显存有上限；在更高优先级的机内 GPU 通信阶段，relay 流量会主动退让。

## 实验评估

实验平台是配备 8 块 Hopper GPU、NVSwitch 加八路 NVLink、以及 8 张 ConnectX-7 400 Gbps NIC 的服务器。基线是启用了 PXN 的 NCCL。相对该基线，FuseLink 在允许最多使用 6 张 NIC 时，把两块跨机 GPU 之间的点对点带宽从 49.27 GB/s 提升到 212.35 GB/s。消融也能支撑这一结论：仅做高效 relay 时是 78.39 GB/s，加入 contention mitigation 后升到 178.59 GB/s，完整调度策略达到 212.35 GB/s。

控制面开销对目标场景而言不大。批量查询一次 NIC 负载只需 0.9-1.6 us；路径切换时的 remap 大约是 95-193 us。论文认为，这些代价会被 512 KB chunk 的流水传输所摊薄。

端到端结果也贴合论文想解决的工作负载。对分离式 OPT-30B serving，FuseLink 将 TTFT 提升了 1.04x-2.73x；在单机并行 8 个 serving instance 时，中位 TTFT 从 684.54 ms 降到 308.48 ms。对 expert-parallel Mixtral 8x22B 训练，吞吐提升约 1.3x；对 DLRM 训练，最高可加速到 1.2x。证据最强的仍然是存在流量倾斜的点对点通信，这与论文的主张是一致的。

## 创新性与影响

相对于 NCCL 的 PXN，FuseLink 不是更聪明的固定路径选择器。PXN 改善的是某一条路径，而 FuseLink 把整台服务器的 NIC 当作可动态借用的资源池，在发送端和接收端两侧都能按空闲情况聚合带宽。相对于 _Lu et al. (NSDI '18)_ 这类多路径协议，它复用的不是数据中心网络中的多条 fabric path，而是单台 GPU 服务器内部的多个 NIC 附着点。相对于 _Rajasekaran et al. (NSDI '24)_ 这类作业级调度器，它的决策发生在通信运行时的 chunk 粒度。

因此，FuseLink 更像一种可复用的系统机制，而不是某个工作负载的小技巧。论文说明，在已经具备高速机内 GPU fabric 和多 NIC 配置的集群里，运行时拓扑控制本身就能转化成 LLM serving、MoE 训练和推荐系统训练中的实际收益。

## 局限性

FuseLink 最适合大消息、强失衡的点对点流量。论文明确说，像 ring all-reduce 这样流量高度均衡的 collective 并不是它的天然适用场景，除非框架同时改变 worker placement，在单机内部制造新的流量倾斜。

它的调度器也是近似的。NIC 空闲状态来自最近 completion，而不是精确瞬时信号；路由切换后可能出现一次受限的次优发送；relay 显存管理也只是 best effort。整套设计还依赖标准的 GPU peer addressing 以及 RDMA 对重映射缓冲区的访问能力。

## 相关工作

- _Hwang et al. (NSDI '23)_ — ARK 改进的是 GPU-driven communication execution，而 FuseLink 关注的是在多张 NIC 之间做动态选择和 relay。
- _Lu et al. (NSDI '18)_ — MP-RDMA 利用的是数据中心网络中的多条路径；FuseLink 聚合的是单台 GPU 服务器内部的多个 NIC 端点。
- _Hidayetoglu et al. (ICS '24)_ — CommBench 刻画了 multi-GPU、multi-NIC 拓扑的性能特征；FuseLink 则给出利用这类拓扑不对称性的运行时机制。
- _Patel et al. (ISCA '24)_ — Splitwise 展示了分离式 serving 中那类跨阶段、带倾斜的流量模式，而 FuseLink 解决的是其下层的多 NIC GPU 通信问题。

## 我的笔记

<!-- 留空；由人工补充 -->
