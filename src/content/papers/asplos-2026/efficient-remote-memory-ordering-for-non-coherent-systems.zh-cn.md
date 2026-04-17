---
title: "Efficient Remote Memory Ordering for Non-Coherent Interconnects"
oneline: "把远程访存排序从请求端挪到 PCIe 与 Root Complex，用 acquire/release 语义和 RLSQ 消除 MMIO 发送与有序 RDMA 读取的源端停顿。"
authors:
  - "Wei Siew Liew"
  - "Md Ashfaqur Rahaman"
  - "Adarsh Patil"
  - "Ryan Stutsman"
  - "Vijay Nagarajan"
affiliations:
  - "University of Utah, Salt Lake City, Utah, USA"
  - "Arm, Cambridge, UK"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790156"
code_url: "https://github.com/icsa-caps/efficient-remote-memory-ordering.git"
tags:
  - hardware
  - networking
  - rdma
  - memory
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

这篇论文认为，非一致性互连之所以慢，瓶颈不在 PCIe 带宽，而在于“排序”被放错了地方。作者把 acquire/release 语义一路带进 PCIe，并在 Root Complex 里用硬件执行排序，从而让 CPU 到 NIC 的 MMIO 发送不再依赖 `sfence`，也让有序 RDMA 读取的性能逼近无序读取。

## 问题背景

论文研究的是非一致性 CPU-设备通信里的细粒度顺序约束。现实软件里这种约束非常常见：CPU 往 NIC 发包时必须保持写入顺序；RDMA NIC 做 key-value 查询时，往往也必须先读锁或版本，再读对象本体。问题在于，PCIe 只给了软件一半想要的保证。posted write 天然保 `W->W`，但 read 不保 `R->R`；而 CPU 侧的 MMIO 顺序通常又只能靠 store fence 强行在源端串行化。

这个错位在 DMA 和 MMIO 两边都很贵。对 DMA 来说，有序远程读会退化成 stop-and-wait：NIC 先发一个读，请求沿互连和内存系统走完整个往返，等完成后才能发下一个依赖读。论文在 ConnectX-6 Dx 上量到，每增加一个有依赖关系的 DMA 读，大约要多付出 `300 ns`；单个 queue pair 上，64 B 有序 RDMA READ 的吞吐因此只有约 `5.0 Mop/s`，也就是 `2.37 Gb/s`。对 MMIO 来说，互连本来能很好地流水化 write，但 CPU 为了保证每个 packet-sized write 的程序次序，必须在写合并缓冲之间插 `sfence`。结果是吞吐被直接打穿：即便消息大小已经到 `512 B`，强制排序仍会让测得的 MMIO 吞吐下降 `89.5%`。

更糟的是，软件因此被迫放弃最直接的协议。发送路径不用“CPU 直接 MMIO 写包”，而改成 doorbell 加 DMA fetch；单边 RDMA key-value store 也不得不引入额外验证轮次，或者在每条 cache line 上嵌版本元数据，因为它不能相信互连会保住一个简单的“先检查，再读取”顺序。论文的立场很明确：这些复杂度大多不是高速 I/O 的宿命，而是在替缺失的体系结构级排序支持买单。

## 核心洞察

最值得记住的命题是：远程排序应该是端到端的显式语义，而不该靠源端停顿间接实现。只要软件能把一个请求标成 acquire 或 release，源端就不必为了制造可见性边而自己停住。它可以继续积极地流水化请求，把真正需要维护的依赖关系交给靠近目的地的硬件去执行。

这一步的价值在于，它把不可避免的串行化挪到了低延迟的位置。今天的设计里，源端每次保序都要承担一次完整的互连加内存往返，在论文模型里大约是 `500 ns`。而在作者提出的设计里，排序点变成 Root Complex，所以瓶颈退化为主机内存侧的本地顺序开销，大约 `100 ns`；再进一步，还能靠投机执行把这部分残余停顿继续摊薄。换句话说，这篇论文不是简单给 PCIe 多加几个 fence bit，而是把“必须串行的那一下”搬到了更容易回收并行度的地方。

## 设计

整个设计分成三层：PCIe 语义、主机 ISA 支持，以及 Root Complex 里的微体系结构。

在 PCIe 层，论文把 acquire/release 风格的远程排序引入到事务里。read 新增 acquire bit；write 则复用现有 relaxed-ordering 编码，把 release write 和普通无序 write 区分开来。这样表达能力比简单的“强序/弱序”更细。比如典型的生产者-消费者模式“先读 flag，再读对象”，就可以表示成一个 acquire read 加上一串 relaxed read，只有真正重要的依赖被保留下来。

在 CPU 接口层，作者主张把远程 MMIO 操作提升为一等 ISA 原语。他们给出了 `MMIO-Store`、`MMIO-Release`、`MMIO-Load`、`MMIO-Acquire` 四种变体，也讨论了一个更现实的过渡方案：对 RISC-V 风格的 fence 重新解释，不再要求核心把前序 MMIO 全部 drain 完，而是把排序元数据注入到发出的事务流里。对 MMIO write 来说，每个线程的操作都会携带序列号，而 Root Complex 里的 reorder buffer 会在把 write 转发给设备前重建程序顺序。这样就能保住 `W->W` 语义，同时去掉今天让直接 MMIO 不可接受的源端停顿。

设计里最关键的部件是 Root Complex 上的新 `RLSQ`。在朴素版本里，relaxed DMA 请求可以并发发出；一个 acquire 会阻塞同线程的后续请求，直到自己完成；一个 release 则会等到同线程更早的请求都结束后再发出。为了避免不同 queue pair 或不同线程上下文之间出现假依赖，PCIe 包还会带 thread ID，于是排序是按线程执行，而不是全局一刀切。

优化版 `RLSQ` 则借用了 CPU 的经典思路：乱序执行，顺序提交。对于 `Acquire->Read` 这样的序列，它可以把两个主机内存访问投机并行发出，把后面的 read 结果先缓存在队列里，等 acquire 真正解析完成后再回复设备。正确性不是靠新造一套 coherence 协议，而是靠把 `RLSQ` 当成一个新的 coherent agent：它会监听 invalidation；如果主机写入打到了某个被投机读取过的地址，就只 squash 冲突的那一个读取并重试。`Write->Release` 也能用类似办法把高延迟的 coherence 动作提前重叠。论文还讨论了 peer-to-peer 场景：如果去往不同目标设备的流量共用一条队列，就必须配合 virtual output queue，否则会出现明显的 HOL blocking。

## 实验评估

实验把真实 NIC 测量和 gem5 模拟结合起来，且两者讲的是同一个故事。在 ConnectX-6 Dx 上，一个完全通过 MMIO 提交的 RDMA WRITE，中位延迟是 `2,941 ns`；加上一次 DMA read 后变成 `3,234 ns`；若变成两个有序 DMA，则升到 `3,613 ns`。这正是论文声称“每个依赖会多出约 `300 ns` stop-and-wait 代价”的经验基础。MMIO 实验同样直观：无序 write-combining store 能做到 `122 Gb/s`，但一旦用 `sfence` 保序，小包场景几乎直接塌掉，连 `512 B` 消息也仍会损失 `89.5%` 吞吐。

模拟结果则展示了新硬件到底买来了什么。对有序 DMA 读来说，投机版 `RC-opt` 在各种对象大小下几乎都能追平无序读取，而把排序放在源端 NIC 的方案则远远落后。在 key-value-store benchmark 里，仅仅把排序点从 NIC 移到 Root Complex，就能把单 QP 的 get 吞吐提升 `29.1x`；再加上投机 `RC-opt`，`64 B` 对象上相对 NIC 排序能提升 `50.9x`。在更多并发和更大 batch 下，只有 `RC-opt` 这种正确的有序设计还能接近 `100 Gb/s` 链路上限。

真实硬件上的“仿真式验证”也很有说服力。因为作者证明了：在只读、无冲突场景下，他们提出的有序设计应当与今天的无序硬件拥有同样的最佳性能，所以可以把现有 ConnectX-6 Dx 的无序吞吐视为目标上界。在这个设定里，只有在有序读硬件支持下才真正安全的 `Single Read` key-value 协议，在 `64 B` 对象上比 FaRM 快 `1.6x`，而且它的 on-wire 布局还比 FaRM 逐 cache-line 嵌版本号的方式更简单。最后，硬件开销也不夸张：CACTI 估算新增的 `RLSQ` 加 reorder buffer 只占参考 I/O hub 面积不到 `0.9%`、静态功耗不到 `0.6%`。当然，最大的保留项也在这里：论文的核心体系结构收益仍主要来自模拟，而不是来自一个真正实现了有序 Root Complex 的硬件原型。

## 创新性与影响

和 _Liew et al. (HotOS '25)_ 相比，这篇论文的新意不只是“如果没有 fence，直接 MMIO 其实很强”这个观察，而是把它扩展成一套完整接口：从 PCIe 语义，到主机 ISA，再到 Root Complex 队列和上层应用协议，全链路都被统一起来。和 _Schuh et al. (ASPLOS '24)_ 相比，它的核心观点是：在非一致性 fabric 上显式表达排序，也许就能拿回大量 coherent CPU-NIC 接口想争取的好处，而不必顺带背上 coherence 协议的复杂度。和 _Yu et al. (ISCA '25)_ 相比，它把关注点放在非一致性主机-设备 I/O，并给读写两侧都补上了明确的 acquire/release 契约。

因此，这篇论文会同时吸引互连架构师、NIC 设计者、考虑改进 MMIO 抽象的 ISA 设计者，以及那些今天还在为无序 RDMA 读取付软件税的系统研究者。它更像一篇新机制加新架构 framing 的论文，而不是生产部署报告。

## 局限性

这套方案要求 PCIe 规范、主机 ISA、Root Complex 微体系结构和设备端行为一起改动，所以部署路径显然不算渐进。论文里最亮眼的收益，尤其是投机有序读部分，也主要来自模拟与基于现有无序硬件的代理验证，而不是真正流片或 FPGA 化的完整原型。

应用覆盖面同样是有选择性的。论文对 CPU-NIC 发送路径和读密集型 RDMA key-value get 讲得非常扎实，但它并不是一篇广泛覆盖整套网络栈或通用加速器通信的软件研究。某些边界情况仍然需要回退到源端排序：如果同一个进程必须跨不同目标设备建立 `R->R` 顺序，论文明确要求由源端 NIC 串行化发出。多目标拓扑下也必须配合 virtual output queue，否则会出现明显的 HOL blocking。也就是说，这个思路很强，但它最干净、最漂亮的收益主要出现在论文重点针对的生产者-消费者模式里。

## 相关工作

- _Schuh et al. (ASPLOS '24)_ — CC-NIC 通过 coherence 给 NIC 更快的主机接口；这篇论文则主张，在非一致性 PCIe 上显式表达排序，也能更简单地拿回其中很大一部分收益。
- _Liew et al. (HotOS '25)_ — 展示了只要去掉 fence 成本，CPU 到 NIC 的 MMIO 路径就很有吸引力；这篇论文把那个观察推广成完整的远程排序接口与执行机制。
- _Yu et al. (ISCA '25)_ — CORD 为异构 release consistency 提供目录式排序；这篇论文则聚焦非一致性主机-设备互连，并围绕 RDMA 风格通信定义 acquire/release 排序。
- _Jasny et al. (TODS '25)_ — 总结了当下无序 RDMA 读取如何迫使分布式数据结构采用复杂同步协议；这篇论文提供的硬件排序正好直接简化这些协议。

## 我的笔记

<!-- empty; left for the human reader -->
