---
title: "Demeter: A Scalable and Elastic Tiered Memory Solution for Virtualized Cloud via Guest Delegation"
oneline: "Demeter 把 VM 分层内存管理搬进 guest，用 EPT-friendly PEBS 和虚拟地址区间识别热点页，再用 double balloon 保住云端弹性。"
authors:
  - "Junliang Hu"
  - "Zhisheng Hu"
  - "Chun-Feng Wu"
  - "Ming-Chang Yang"
affiliations:
  - "The Chinese University of Hong Kong"
  - "National Yang Ming Chiao Tung University"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764801"
tags:
  - memory
  - virtualization
  - datacenter
category: memory-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Demeter 的核心主张是，VM 的分层内存不该继续由 hypervisor 主导，而应该由 guest OS 自己完成。它利用 guest 可见的 EPT-friendly PEBS 直接采样 guest virtual address，把热点分类单位从零散页面改成虚拟地址区间，并把 hypervisor 的职责收缩为用 double balloon 提供按层弹性配额。这个分工同时避开了虚拟化环境下最昂贵的跟踪开销，并在多数场景中优于已有的 host-side 和 guest-side 方案。

## 问题背景

云平台越来越需要分层内存，因为 DRAM 容量增长速度明显慢于 CPU 核数增长，而 PMEM 与 CXL.mem 则提供了更便宜但更慢的第二层。真正困难的不是把慢内存接进来，而是在多 VM 共享机器时判断哪些页面值得放进稀缺的 fast memory。现有面向虚拟机的方案大多把这件事交给 host，让 hypervisor 通过页表状态推断冷热，并负责迁移 guest 页面。

论文证明，这种设计和现代硬件虚拟化的代价模型并不匹配。在 two-dimensional paging 下，hypervisor 侧的访问跟踪高度依赖 PTE access/dirty bits，而重置这些 bit 需要破坏性的 TLB flush。更糟的是，host 主要看到的是 guest physical address，看不到应用真正保留下来的 guest virtual address 局部性。理论上可以像近期 kernel-tiering 工作那样用 PEBS，但过去大家普遍认为它对 guest 不可用或不安全；即便直接把已有 guest-side 方案搬进 VM，多租户场景下的 CPU 消耗也太高。因此，Demeter 必须同时解决两件事：让 guest 内部的冷热识别既便宜又准确，同时保留云平台需要的弹性配额与 QoS 控制。

## 核心洞察

这篇论文最重要的判断是，过去 VM 分层内存系统把 guest 和 hypervisor 的职责边界放错了。如果 hypervisor 只负责决定一台 VM 当前拿到多少 fast memory 和 slow memory，而把完整的 tracking-classification-migration 流水线交给 guest，那么系统就重新获得了 host 最缺失的两样东西：guest virtual address 空间里的局部性，以及 guest 内部可直接使用的 EPT-friendly PEBS。

这之所以有效，是因为 guest 看到的内存布局仍然接近应用创建对象时的语义结构，而 guest physical address 已经被 lazy allocation、内核分配器和 host 重映射打散。Demeter 因而把“热度”定义成 guest virtual address 区间的属性，而不是彼此无关的物理页属性，并直接用 guest 中采到的 PEBS 样本驱动这些区间。这样既省掉了每个样本都要走页表翻译的成本，也避免了围绕 PTE bit 的反复 TLB flush，让 hypervisor 回到它真正擅长的事情上：跨租户做弹性资源供给。

## 设计

Demeter 把系统拆成两部分。每个 VM 内部有一个 guest 模块负责完整的 tiered memory management；hypervisor 侧则单独负责暴露分层资源并按需调整容量。host 通过 ACPI 把 fast 和 slow memory 暴露成两个虚拟 NUMA node，并用 NUMA distance 表达相对性能，让 guest 不需要新抽象或应用修改，就能重建正确的层次拓扑。

guest 侧最关键的算法是 range-based classifier。Demeter 从两个粗粒度区间开始，一个覆盖 heap，一个覆盖 `mmap` 区域，同时故意排除 code、data 和 stack，因为这些区域规模较小且天然偏热。之后它维护一个类似 segment tree 的区间层次：当某个区间相对邻居显著更热时就继续二分，不热以后再合并；每个 epoch 都把访问计数减半，让旧热点自然衰减。最小切分粒度是 2 MiB，以保住 hugepage 级别的 TLB 效率。最终系统按“访问频率除以区间大小”排序，并用年龄作为时间局部性的并列裁决，从而尽量把真正高价值的区间塞进 fast memory。

访问跟踪不再扫描 PTE bit，而是直接用 guest 可见的 EPT-friendly PEBS。PEBS 样本本来就携带 guest virtual address，所以 Demeter 可以把样本直接送进区间分类器，而不用像先前的 PEBS 系统一样为每个样本再反查页表、恢复物理页。为了把 CPU 成本压住，它放弃激进的动态采样频率，改用固定采样周期，并在进程 context switch 时顺手排空 PEBS buffer，通过无锁通道把样本送到分类器，避免专门的 polling thread 和大量 PMI 开销。为了同时兼容 DRAM、PMEM 和未来的 CXL 层，它选用 `MEM_TRANS_RETIRED.LOAD_LATENCY` 事件，并用 64 ns 阈值过滤 cache hit。

迁移阶段采用 balanced relocation。系统先根据排序结果找出处在热区间但位于 slow memory 的页面，形成 promotion list；再从最冷区间里找出同样数量、却还占着 fast memory 的页面，形成等长的 demotion list。随后批量执行 unmap、直接交换内容、再 remap，从而避免临时 buffer、缩短锁持有时间，并减少 TLB flush。配额侧则由 Demeter 的 double balloon 完成，它为两个虚拟 NUMA tier 分别维护 page-granular balloon，使一台 VM 可以在“几乎全快”到“几乎全慢”之间平滑切换。额外的 VirtIO statistics queue 把分层利用率和压力暴露给 host，把 QoS 与重平衡策略保留在机制之外。

## 实验评估

实验平台是一台双路 36 核 Xeon 8360Y 服务器，配有 DRAM 与 Optane PMem，并额外用 remote DRAM 模拟了一套 CXL.mem 环境。每个 VM 配置 4 个 vCPU、16 GiB 分层内存，默认 fast:slow 比例为 1:5。microbenchmark 结果很扎实。Demeter balloon 在保持动态伸缩能力的同时，性能基本追平静态分配，并比不感知 tier 的 VirtIO balloon 高出 68% 的 GUPS 吞吐。它的访问跟踪原语只消耗 0.64% CPU，而 PTE.A/D-bit 扫描是 3.08%，PML 方案则高达 14.61%。放到完整 guest-side 系统比较里，Demeter 的 PEBS draining 只花 3 秒 CPU 时间，Memtis 要 49 秒；它的迁移开销也只有 TPP 的 28%。

真实工作负载结果同样有说服力。论文选了 7 个 workload，覆盖数据库、科学计算、图处理和机器学习。Demeter 的整体最好加速达到 2.2x，相对下一名 guest-side 方案 TPP 的几何平均优势为 28%。它在 XSBench、LibLinear、Silo 这类静态或动态热点明显的程序上尤其强。对 hypervisor-side 的 TPP-H 变体做公平比较时，Demeter 在 7 个 workload 里赢了 6 个，平均仍快 16%，而且作者还额外给了 hypervisor baseline 更多 DRAM 余量。Silo 的延迟实验也很有价值：相对 TPP，Demeter 把 99th percentile latency 再降了 23%。不过证据并非全线压倒。PageRank 仍然是明显弱点，因为图数据里热冷对象细粒度交织，TPP 在这种场景下更容易占优，Demeter 在 guest-vs-hypervisor 比较里也因此输给了对手。

## 创新性与影响

Demeter 的新意不只是又一个页面迁移策略，而是重新定义了虚拟化云里谁应该负责分层内存。相对 RAMinate、vTMM 这类 hypervisor-based 工作，它指出 host 试图通过页表去恢复 guest 局部性，本身就是错误方向。相对 Memtis、TPP 这类 kernel-tiering 工作，它展示了这些思想要想在多租户 VM 环境里成立，必须连采样路径、分类对象和供给机制一起重做。

这让论文对云基础设施很有现实意义。它很可能是第一篇把 guest 可用的 EPT-friendly PEBS 当成 VM 分层内存一等原语来系统利用的工作，并把这条硬件线索和一套可部署的软件分工真正结合起来：guest 负责 TMM，host 负责 provisioning。若未来云平台通过 CXL 暴露越来越多异构内存，Demeter 这种 guest-delegated 结构很可能会成为一个有吸引力的模板，因为它能保住控制面的弹性，而不用在每个 memory epoch 都支付 host-side 跟踪成本。

## 局限性

论文明确承认了两个技术边界。第一，Demeter 不处理 2 MiB 以下的 intra-hugepage skewness，因此如果热数据和冷数据紧密混在同一个 hugepage 里，它仍可能放错位置。第二，它的区间管理天然不覆盖 file page cache，因为那部分页是由内核在物理地址空间里管理，而不是位于 Demeter 追踪的 guest virtual 区域。

此外还有部署与评估层面的约束。Demeter 依赖 guest kernel 支持以及较新的 PEBS 虚拟化能力，因此并不是对任意 guest image 的零改动增强。host 侧的 QoS 叙事也刻意停留在机制层：系统会导出统计，但论文没有实现和评估真正的集群级控制器。最后，性能表现虽然总体很强，却并非无死角。PageRank 是清晰反例，而安全性讨论也主要停留在设计论证，并没有给出对抗性评估。

## 相关工作

- _Hirofuchi and Takano (SoCC '16)_ - RAMinate 同样在 hypervisor 里做 VM 分层内存；Demeter 的立场则是 hypervisor 正是最难恢复访问局部性的地方。
- _Sha et al. (EuroSys '23)_ - vTMM 仍把管理主逻辑放在 host，只让 guest 协助暴露页表信息；Demeter 则把整条 TMM 流水线都搬进 guest，只把 provisioning 留在 host。
- _Lee et al. (SOSP '23)_ - Memtis 证明了 PEBS 适合做 kernel-tiering 的热点来源，而 Demeter 进一步为虚拟化 guest 和多 VM 可扩展性重写了这条采样路径。
- _Al Maruf et al. (ASPLOS '23)_ - TPP 面向 CXL-enabled tiered memory 的内核页放置；Demeter 在此基础上增加了 guest virtual 区间分类和面向云环境的弹性供给设计。

## 我的笔记

<!-- 留空；由人工补充 -->
