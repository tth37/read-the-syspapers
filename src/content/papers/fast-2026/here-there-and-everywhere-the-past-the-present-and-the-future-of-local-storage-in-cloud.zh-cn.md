---
title: "Here, There and Everywhere: The Past, the Present and the Future of Local Storage in Cloud"
oneline: "梳理 Alibaba Cloud 本地盘从 SPDK 轮询到 ASIC/SoC 卸载的三代演进，并提出结合 EBS 的混合方案，在保住近本地性能的同时补回可用性与弹性。"
authors:
  - "Leping Yang"
  - "Yanbo Zhou"
  - "Gong Zeng"
  - "Li Zhang"
  - "Saisai Zhang"
  - "Ruilin Wu"
  - "Chaoyang Sun"
  - "Shiyi Luo"
  - "Wenrui Li"
  - "Keqiang Niu"
  - "Xiaolu Zhang"
  - "Junping Wu"
  - "Jiaji Zhu"
  - "Jiesheng Wu"
  - "Mariusz Barczak"
  - "Wayne Gao"
  - "Ruiming Lu"
  - "Erci Xu"
  - "Guangtao Xue"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Group"
  - "Solidigm"
conference: fast-2026
category: cloud-and-distributed-storage
tags:
  - storage
  - virtualization
  - hardware
  - caching
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文既是工业界经验回顾，也是面向未来的设计研究。它解释了 Alibaba Cloud 的本地存储栈为什么会从 kernel/Virtio 路径演进到 `ESPRESSO`、再到 `DOPPIO`、再到 `RISTRETTO`，并进一步主张下一步不该是“更纯粹的本地盘”，而应是混合形态：把低延迟、突发型 I/O 留在本地高性能层，把持久性、弹性和更广泛可部署性交给 Elastic Block Storage。微基准里，`RISTRETTO` 在单个虚拟盘上做到 `949K` 的 4KB 随机读 IOPS 和 `6.7 GB/s` 读带宽，已经接近物理 Gen4 SSD；`LATTE` 原型在 `75%` 命中率下则做到 `8.9 GB/s` 的读带宽。

## 问题背景

云上本地盘之所以长期受欢迎，是因为它直接挂在计算节点上，避开了网络 hop，因而能以明显低于远端块存储的价格，交付接近物理设备的性能。但让它快的同一个架构选择，也让它在产品层面一直很别扭。本地盘难以弹性扩缩容，不天然具备副本保护，而且只有在某些需求足够密集的地域才值得部署大量直挂 SSD。换句话说，它始终处在“性能好”与“云特性差”之间的拉扯里。

论文认为，SSD 的持续演进不断打碎旧前提。Alibaba 早期面向 HDD 的 kernel stack 在慢设备时代还能接受，但 NVMe SSD 把 VM exit、system call 和 interrupt 的代价成倍放大。`ESPRESSO` 用 `SPDK` 把栈搬到用户态、用 polling 减少上下文切换，确实修掉了大量软件开销；但它需要长期占用 host CPU core，而且完成路径上仍要为 `eventfd` 和 hypervisor 过渡买单。随后 `DOPPIO` 又把虚拟化与 I/O 处理推到 ASIC-based DPU 上，消除了 host CPU 依赖，可新问题也随之出现：固定逻辑的 ASIC 很难追上新一代 `1.5M` IOPS SSD，也不擅长快速支持 `LVM`、`ZNS` 这类新云特性。

更深一层的问题是，哪怕 `RISTRETTO` 已经把本地盘做得几乎像物理盘，纯本地存储仍然天然缺少高可用、细粒度容量弹性和广泛可达性。高性能远端块存储如 Alibaba `EBSX` 能解决这些问题，但论文给出的量级是：一个 `1M` IOPS、`4 TB` 的 `EBSX` 虚拟盘，价格大约会是同等能力 `RISTRETTO` 本地盘的 `20x`。因此真正的问题不是“本地盘能不能继续变快”，而是如何在不放弃 locality 延迟优势的前提下，摆脱 locality 带来的产品限制。

## 核心洞察

论文最核心的主张是：本地存储不是一个固定不变的设计点。随着设备越来越快，主导瓶颈会从软件上下文切换，转移到 host CPU 预留成本，再转移到固定功能 offload hardware 的僵化，最后变成纯本地盘在产品层面的先天短板。一个可持续的架构因此必须把最敏感的 fast path 放进专用硬件，同时把策略、特性演进和云语义保留在可编程软件里。

这个判断一方面解释了 `RISTRETTO` 为什么要做 ASIC 与 SoC 的分工：把 NVMe 仿真、DMA 路由和 interrupt injection 交给 ASIC，把 block abstraction 和 feature logic 交给 ARM SoC；另一方面也解释了 `LATTE` 的方向：当可用性和弹性才是主要矛盾时，正确答案不是把本地盘继续做得更复杂，而是把它降级成高性能前端 tier，再让远端 `EBS` 提供持久、弹性的后端。论文最值得长期记住的，不是某一个 controller 细节，而是这条抽象边界。

## 设计

`ESPRESSO` 是第一代 SSD 时代的重构。它基于 `SPDK` 把存储栈搬到用户态，用 polling 代替 interrupts，并把每个虚拟盘线程绑定到专用 host core，同时采用 share-nothing 数据结构。这一改动显著降低了旧 kernel stack 在 NVMe 上暴露出来的上下文切换成本，也支撑它扩展到数万台服务器。但部署代价同样明显：启用 `ESPRESSO` 的节点无法再提供 bare-metal service，预留出来的 CPU 在 `99th` percentile 上实际利用率只有约 `60%`，而且完成路径仍然会经过 `eventfd` 和 hypervisor。

`DOPPIO` 进一步把这条路径卸载到商用 ASIC-based DPU。每个 DPU 管理两块 NVMe SSD，把 namespace 暴露成 `SR-IOV` virtual function，通过 DMA 抓取 guest 的 NVMe command，把数据暂存在 DPU DRAM 中，再用硬件 `MSI` interrupt 通知 guest 完成。这样一来，host CPU 不再承担 I/O 处理职责，`ESPRESSO` 剩余的完成路径软件开销也大幅下降。但 DPU 很快反过来成了系统新瓶颈：当一块 DPU 需要服务两块 Gen4 SSD 时，`DOPPIO` 的单盘能力大约封顶在 `1.3M` IOPS，而固化逻辑又很难跟上新云功能。

`RISTRETTO` 是论文里最完整、也是最重要的架构。它是一张 PCIe 扩展板，板上同时有 ASIC、`4` 个 ARM Cortex-A72 core，以及 `64 GB` DRAM。ASIC 负责仿真 NVMe controller、抓取 guest command、在 SSD 与 host memory 之间路由 DMA、向 guest 注入硬件 interrupt，并维护 ASIC 与 SoC 间的 virtual queue；SoC 运行基于 `SPDK` 的 runtime，轮询这些队列、做 queue mapping，并插入一个可编程的 block abstraction layer，用来承载 `LVM`、`RAID`、caching，甚至面向 `ZNS` SSD 的 host-side `FTL`。此外，它还让多个 virtual queue 对齐 guest 的 NVMe queue pair，从而保留并行性，而不是把所有 I/O 都压回单一路径。

论文最后把 `EBSX` 与 `LATTE` 视作下一阶段方向。`EBSX` 是 Alibaba 的高性能远端块存储，延迟大约 `30 us`、吞吐 `6 GB/s`、IOPS 达 `1M`，但因为使用更高端硬件与更强的数据保护机制，价格也显著更高。`LATTE` 则以 `RISTRETTO` 作为前端 cache、标准 `EBS` 作为后端，建立在 `CSAL` 之上。写路径里，一个 `ML` dispatcher 会根据最近 `5` 个 I/O 的 cache/backend latency、I/O size 与 queue depth，用线性 `SVM` 判断该写入前端还是后端；读路径则采用 `S3-FIFO` 风格的 admission policy，避免 one-hit block 污染本地层。系统维护 `L2P` 映射，保证 cache 与 backend flush 之间的写顺序，在延迟方差超过 `10%` 时触发模型重训，而单次推理开销据论文报告最高只有 `200 ns`。

## 实验评估

实验整体上是支撑论文论点的，因为测法基本对齐了主张。三代本地存储栈都在同一类 SSD 上测试，因此关键差异主要来自栈本身，而不是设备代差。在单个虚拟盘上的 4KB 随机读里，`RISTRETTO` 做到 `949K` IOPS，明显高于 `ESPRESSO` 的 `572K` 和 `DOPPIO` 的 `661K`；扩展到 `8` 个虚拟盘后，它能到 `7.385M` IOPS 与 `53.4 GB/s` 顺序读带宽。论文关于“接近物理盘”的说法也比较可信：Table 1 给出的 `RISTRETTO` 本地虚拟盘大约有 `900K/180K` 的读写 IOPS 与 `6.7/4.0 GB/s` 的读写吞吐，而底层物理 SSD 是 `1,000K/180K` 与 `6.9/4.1 GB/s`。

这些微基准也很好地解释了早期方案为什么会输。`ESPRESSO` 的读写延迟最高，因为 interrupt 与 hypervisor 路径在高 IOPS 下仍清晰可见。`DOPPIO` 去掉了大部分这类软件成本，但在 Gen4 SSD 上读带宽仍只有大约 `4.1 GB/s`，瓶颈已经变成 DPU 的 PCIe 通道能力。`RISTRETTO` 则同时修正了这两个问题：它用硬件 interrupt 处理 guest-facing completion path，同时在 SoC 侧保留足够的软件可编程性，避免 `DOPPIO` 那种“性能够了但功能演进跟不上”的死胡同。

`LATTE` 的评估更像原型验证，而不是成熟产品验证，但结果仍然很有启发性。在 `75%` cache hit rate 下，它做到 `8.9 GB/s` 读带宽和 `7.8 GB/s` 写带宽，超过 `RISTRETTO` 与 `EBSX`，原因是它同时用上了本地层和后端层的带宽。三条生产 trace 的读命中率分别达到 `90.23%`、`88.79%` 和 `82.80%`，trace replay 也显示其延迟明显低于标准 `EBS` 与 `EBSX`。在 MySQL Sysbench 中，`RISTRETTO` 在只读与混合负载上都优于 `DOPPIO` 和 `ESPRESSO`；而 `LATTE` 在纯写负载上甚至超过 `RISTRETTO`，说明本地缓冲和后端吞吐的组合确实有效。主要保留意见在于成熟度：`LATTE` 仍是 PoC，它最好看的微基准数据依赖较理想的命中率与 auto-scaling 行为，尚未经过实地大规模部署验证。

## 创新性与影响

相对 _Kwon et al. (OSDI '20)_ 和 _Chen et al. (HPCA '23)_ 这类硬件辅助存储虚拟化工作，这篇论文不只是又做了一块新的 offload device。它真正的新意在于给出了一条纵向演进论证：每一代云本地存储都解决了一个瓶颈，却又暴露出下一个瓶颈，而合理终点不是纯软件，也不是纯硬件，而是 ASIC/SoC 分工再加上 local-cloud hybrid。相对 _Zhou et al. (EuroSys '24)_，`LATTE` 把本地加远端的加速思路，从“写缓存层”扩展成带有路径调度与 admission control 的混合块存储。相对 _Zhang et al. (FAST '24)_，它又从相反方向补完了 Alibaba 存储体系的故事：前者讲远端 cloud block store，本文讲真正贴在计算节点上的 local disk，以及如何再桥接回 `EBS`。

因此，这篇论文对系统实践者的价值可能大于对算法研究者的价值。做 VM storage virtualization、storage DPU、或者 local/remote hybrid tier 的人，很可能会引用它，因为它把多年线上经验压缩成了相当清晰的架构边界。它既有新的机制，也有经验报告的成分，更有一种产品级设计判断：本地存储应该负责到哪一步为止。

## 局限性

论文最扎实的部分是 `RISTRETTO`，最弱的部分则是最后关于 `LATTE` 的愿景。`RISTRETTO` 已有数千节点部署经验，而 `LATTE` 明确还只是 proof of concept，因此关于 QoS、成本下降与运维可行性的未来判断，证据强度都弱于本地盘部分。论文也承认，如果多个租户共享同一块本地盘并同时发生突发 I/O，要稳定维持可预测 QoS 并不容易。

即便在混合设计里，持久性也不是无条件成立的。论文说所有数据最终都会进入 `EBS`，但在 write-back 模式下，本地盘崩溃时仍可能丢掉尚未 flush 的数据；若想得到更强保证，就需要依赖 `O_DIRECT` 或 `O_SYNC`，而这会改变性能区间。成本问题同样没有完全解决：`LATTE Auto` 虽把归一化月价降到大约 `2.1-4.0x` `RISTRETTO`，但它仍显著高于纯本地盘。

此外，这篇论文也带着 experience report 常见的边界。它很好地解释了每一类瓶颈为何重要，但部分系统级结论显然深受 Alibaba 具体环境影响，例如地域可达性假设、产品打包方式，以及 `EBSX` 的经济模型，不一定能直接外推到所有云厂商。微基准设计是认真的，但 hybrid failover、模型重训与 cache sharing 的端到端运维复杂度，只被部分量化了。

## 相关工作

- _Kwon et al. (OSDI '20)_ — `FVM` 用 FPGA 辅助虚拟设备仿真实现存储虚拟化，而本文研究的是面向云本地盘产品约束的 ASIC 与 ASIC/SoC 卸载路线。
- _Zhou et al. (EuroSys '24)_ — `CSAL` 是 `LATTE` 的直接软件基础，但 `LATTE` 在其之上补上了 ML 路径选择与 `S3-FIFO` admission，使本地层不只是一个写缓冲。
- _Zhang et al. (FAST '24)_ — `EBS Glory` 讲述了 Alibaba 远端块存储的演进，而本文覆盖的是互补的本地存储谱系，以及重新接回 `EBS` 的桥接方案。
- _Yang et al. (SOSP '23)_ — `S3-FIFO` 提供了 `LATTE` 所采用的队列结构，用于 admission 与 eviction，避免 one-hit block 填满本地层。

## 我的笔记

<!-- 留空；由人工补充 -->
