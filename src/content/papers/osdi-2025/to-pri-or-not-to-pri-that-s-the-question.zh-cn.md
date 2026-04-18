---
title: "To PRI or Not To PRI, That’s the question"
oneline: "VIO 通过 snoop VirtIO 请求、锁定热点 I/O 页，并在高 IOPS 时切回 passthrough，把 I/O page fault 从 DMA 关键路径中移走。"
authors:
  - "Yun Wang"
  - "Liang Chen"
  - "Jie Ji"
  - "Xianting Tian"
  - "Ben Luo"
  - "Zhixiang Wei"
  - "Zhibai Huang"
  - "Kailiang Xu"
  - "Kaihuan Peng"
  - "Kaijie Guo"
  - "Ning Luo"
  - "Guangjian Wang"
  - "Shengdong Dai"
  - "Yibin Shen"
  - "Jiesheng Wu"
  - "Zhengwei Qi"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Group"
conference: osdi-2025
tags:
  - virtualization
  - memory
  - datacenter
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

VIO 是一种面向 oversubscribed cloud 的 host-side 方案，用来替代对 PRI 的依赖。它在设备消费 VirtIO 请求之前先做 snoop、补齐 DMA 需要的页、锁定 I/O 热页，并在高 IOPS 时切回直接 passthrough。

## 问题背景

SR-IOV 和 device passthrough 能给 VM 提供接近裸机的 I/O 性能，但它们默认设备可以顺利 DMA 到 guest 会访问的每一个页。现实是，大多数设备都无法优雅地处理 I/O page fault，因此 hypervisor 只能把 DMA 可见的 guest memory 静态 pin 住。这直接妨碍了 overcommit 与冷页回收。论文给出的生产环境数据显示，在一个 300 节点集群里，长期运行的 legacy VM 约占用 800 GB 内存，其中超过 34% 是 cold pages；启用 VIO 后，每天大约可回收 120 GB，同时仍满足 SLO。

PRI 本来想用 device-side fault handling 来解决这个矛盾，但论文认为它既“不普及”，也“放错了位置”。主流 NIC 与 storage device 普遍缺少 PRI，很多旧 guest kernel 也不支持；而即便硬件具备 PRI，把 IOPF 放在 DMA critical path 上依然很贵。论文报告 PRI 延迟大约是 CPU page fault 的 3 倍到 80 倍，而且设备丢包后，上层 TCP/RDMA 的重传会把代价进一步放大。

## 核心洞察

这篇论文最值得记住的观点是：云平台真正需要的不是“更快的 device-side page fault”，而是“让 page fault 不再位于 device critical path”。VIO 因此把 VirtIO queue 当成拦截点。只要 host 能在 backend device 消费请求之前先检查每个 VirtIO request，它就可以先把缺页处理掉，让设备在无 IOPF 的前提下继续 DMA。

这个思路还依赖一个现实观察：不同 VM 不需要长期使用同一种模式。低 IOPS workload 更在意 memory reclamation，几微秒的 snooping 开销可以接受；高 IOPS workload 通常本来就需要大部分内存驻留，此时继续 snooping 只会增加负担，所以系统应自动切回 passthrough。

## 设计

VIO 由三个互相配合的机制组成。第一是 IOPA-Snoop。标准 VirtIO 路径里，guest 会推进 available ring，随后 backend device 消费请求。VIO 在其中插入 shadow index 和 shadow available ring，让 driver 与 device 看到的进度不同步。当 guest 更新真实 ring 时，设备仍只看到旧的 shadow 状态；host-side 的 snooping thread 会先解析 descriptor、检查 EPT，并在需要时把缺页 swap in，然后才推进 shadow ring，让设备开始安全 DMA。

第二是 elastic passthrough。VIO 同时维护 native ring 和 shadow ring。进入 snooping 时，系统会短暂 unmap ring，把内容复制到 shadow ring，这一步大约 10 us，然后原子地把 IOMMU 指向 shadow ring。离开 snooping 时，由 IOPS monitor 决定是否切回，生产环境中阈值是 100k IOPS；host 会在继续 snooping 的同时主动把必要页面换回内存，随后把设备 remap 回 native ring。Orthus live upgrade 让作者能把这套机制部署到 legacy VM。

第三是 lockpage。VIO 记录 I/O page access，并把可能复用的页 pin 住，减少重复 fault。它用 2 MB 粒度的 bitmap 做快速热点检查，再用借鉴 Linux LRU 的 active/inactive list 决定哪些页继续保持 pinned。论文还给 VirtIO RX queue 设计了 static lockpage，因为这类连续缓冲区非常适合长期 pin 住。

## 实验评估

一旦 IOPF 被移出 device path，吞吐塌陷和 jitter 就会显著减少。在大型 CSP 的生产级平台上，IOPA-Snoop 的平均开销约为 4 us；lockpage hit 约 3.5 us，miss 约 4.5 us，而真正的 page fault 平均是 700 us。这个量级说明，snooping 对低 IOPS VM 是可接受的，但高 IOPS 下不能长期保留。

与 SOSP 2024 的 VPRI 基线相比，VIO 在 fault injection 下稳定得多。作者在同一 DPU 平台上实现了 VPRI，因此对比总体可信。随着 fault latency 增长到 10 ms，VPRI 在 Redis 上吞吐下降约 60%，在 Nginx 上下降 45%，在 Memcached 上下降 57%，因为 device-side fault 会引发丢包与重传。VIO 把损失控制在 10% 以内，因为它在 DMA 开始前就先把缺页处理掉。iperf 的 jitter 实验也说明了同样的事情：VPRI 的带宽会反复接近归零，而 VIO 基本稳定在接近 10 Gbps。

在 30% memory oversubscription 的一小时 Redis YCSB 运行中，系统记录了 1,464,225 次唯一页访问，却只出现 1 次 IOPF。按天统计时，I/O-side page fault 为 37，而 CPU-side page fault 为 7,474，比例低于 1%。消融实验说明了模式切换边界：lockpage 让 snooping 吞吐提升 3.4%，而高 IOPS 下 full passthrough 仍比 snooping 快 11.1%。应用基准故意让 VIO 保持在 snooping mode，所以 dynamic switching 的收益主要通过 ablation 和生产部署证据来体现。

## 创新性与影响

相对于 _Guo et al. (SOSP '24)_，VIO 不是去加速 PRI，而是直接绕开 PRI，把 fault handling 放到 host 的 VirtIO control path。相对于 _Amit et al. (USENIX ATC '11)_ 与 _Tian et al. (USENIX ATC '20)_ 这类 guest-cooperative 路线，它不要求 guest 修改，这对充满多年未升级 legacy VM 的公有云尤其关键。

它的影响更偏工程落地。VIO 不是新的应用接口，而是一套可以在 PRI 普及之前就部署的 hypervisor 技术，用来在 passthrough VM 上安全回收内存。论文声称它已在 300K VM 上运行一年，这让它的实用价值更可信。

## 局限性

VIO 的兼容性虽然广，但不是无条件。它仍要求 guest 使用 VirtIO，并假设后端存在支持 VirtIO offload 的 DPU 或等价组件，因此不能无缝修补所有 passthrough 栈。整个方案还依赖 hypervisor 对 EPT 与 IOMMU mapping 的控制权。

论文也留下了一些工程层面的开放问题。生产环境使用的是 static 而非 adaptive lockpage，主要因为更易维护；Windows VirtIO driver 会把 p99 lockpage rate 推到 79%，说明软件栈质量仍显著影响收益；100k IOPS 的切换阈值也是人工调参结果。

## 相关工作

- _Amit et al. (USENIX ATC '11)_ — vIOMMU 依赖 guest 与 hypervisor 的 para-virtual 协作来支持动态 DMA pinning，而 VIO 则完全在 host 侧截获 VirtIO queue 的推进过程，不要求 guest 改动。
- _Tian et al. (USENIX ATC '20)_ — coIOMMU 同样尝试用软件解决 direct I/O 的内存管理问题，但仍依赖 cooperative tracking，而且论文自己的消融实验也显示它在高 IOPS 下明显落后于 VIO。
- _Guo et al. (SOSP '24)_ — VPRI 通过硬件加速 PRI 风格的 page fault，而 VIO 的策略是直接把 device-side fault handling 从 critical path 里拿掉。
- _Dong and Mi (Internetware '24)_ — IOGuard 用专用 CPU core 来承担 software IOPF handling，VIO 则通过 VirtIO snooping 和 lockpage 把 host 开销压低，同时保持 guest 无修改。

## 我的笔记

<!-- 留空；由人工补充 -->
