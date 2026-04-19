---
title: "HyperAlloc: Efficient VM Memory De/Inflation via Hypervisor-Shared Page-Frame Allocators"
oneline: "HyperAlloc把hypervisor直接接到guest页帧分配器上，用2 MiB粒度DMA-safe地回收和归还VM内存，把ballooning与hotplug的代理开销拿掉。"
authors:
  - "Lars Wrenger"
  - "Kenny Albes"
  - "Marco Wurps"
  - "Christian Dietrich"
  - "Daniel Lohmann"
affiliations:
  - "Leibniz Universität Hannover"
  - "Technische Universität Braunschweig"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717484"
code_url: "https://github.com/luhsra/hyperalloc-bench"
tags:
  - virtualization
  - memory
  - kernel
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

HyperAlloc 不再让 VM 内存回收绕一圈 guest 里的 balloon driver，而是把 hypervisor 直接接到 guest 的 page-frame allocator 状态机上。这样，2 MiB huge page 的回收主要变成元数据更新和映射撤销；guest 真要重新使用这些页时，再通过 install hypercall 把 backing memory 显式装回去，所以 DMA safety 也能保住。论文在 Linux/QEMU 上报告，收缩速度达到 344.8 GiB/s，最多比 virtio-balloon 快 362x、比 virtio-mem 快 10x；在自动回收的 Clang 场景里，memory footprint 也比 virtio-balloon 低 17%。

## 问题背景

这篇论文抓的是 IaaS 里一个长期存在的矛盾：VM 的内存需求会剧烈波动，但 cloud provider 仍然不敢把 memory overcommitment 做得太激进，因为从运行中的 guest 手里拿回内存，现有方案要么太慢、要么太扰动、要么和 device passthrough 冲突。

virtio-balloon 支持自动回收，可它依赖 guest 内代理驱动、4 KiB 粒度和 fault-on-access 的补页路径，host-guest 往返很多，也不适合 GPU、NIC 这类 DMA 设备。virtio-mem 是 DMA-safe 的，也把粒度提到 2 MiB，但 grow 时要预填充内存，而且没有自动回收。VProbe 更接近目标，却仍然是通过 `struct page` 的副作用去推断 allocator 行为。论文真正瞄准的是 prior work 没有同时给出的组合：快速 de/inflation、自动弹性，以及 DMA safety。

## 核心洞察

HyperAlloc 的关键判断是，hypervisor 不该隔着 balloon driver、hotplug driver 或 `struct page` 的副作用去猜 guest allocator 在做什么，而应该直接参与 allocator 的状态切换。它把 LLFree 那套紧凑、无锁的元数据共享给 hypervisor，于是回收 free huge page 变成状态更新加 unmap，而不是一串代理协议或 fault。

这样一来，性能和 DMA safety 能一起成立。回收时，guest 会明确看到哪些页已经被 evict；以后真要重新分配到这些页时，再通过 install hypercall 先把 backing memory 映射并 pin 好。论文想表达的核心其实是：真正有用的改动不是单纯把粒度做大，而是把 host/guest 的协作提前到 allocator 层。

## 设计

HyperAlloc 建在 LLFree 之上。LLFree 是作者团队之前做的 lock-free Linux page-frame allocator，最适合 HyperAlloc 的地方在于元数据紧凑、没有指针链表、状态更新全靠 atomic 操作完成，所以 hypervisor 能通过 shared memory 直接读写 guest allocator 的状态，而且不用闯进复杂的 guest 控制流。

论文把每个页框拆成 host 侧 `(M, R)` 和 guest 侧 `(E, A)` 两组状态：有没有 host backing、当前是 installed 还是 reclaimed、guest 是否看到 evicted hint，以及这块 huge page 是否已被 guest 分配。hard reclamation 会把页标成 `A=1`、`E=1`，再从 EPT 和 IOMMU 中 unmap 掉，用来真正降低 VM 的 hard limit；soft reclamation 则保留重新分配的可能，服务自动弹性。以后 guest allocator 若选中了 evicted 页，就发 install hypercall，把内存先映射并 pin 好，再交给 CPU 或设备使用，这就是 DMA-safe 的关键一环。

自动回收每 5 秒跑一次，只扫描那些稠密数组里的 installed 且未分配 huge page。HyperAlloc 还改了 LLFree 的 reservation policy，尽量减少 huge-page fragmentation，这对自动回收效果非常关键。原型放在 user-space QEMU 里而不是 KVM 内核，因此 install 仍然多一次 context switch，EPT/IOMMU 的处理也要借助 `madvise(DONT_NEED)` 和 VFIO 接口。

## 实验评估

实验环境是双路 Intel Xeon Gold 6252、Debian 12、Linux 6.1 和 QEMU/KVM 8.2.50。主要基线包括 virtio-balloon、huge-page ballooning 和 virtio-mem，并在需要时加上 VFIO。唯一缺掉的重要对手是 VProbe，作者讨论了它，但拿不到可运行实现。

在 microbenchmark 上，HyperAlloc 的优势很直接。回收 19 GiB 已访问内存时，它达到 344.8 GiB/s；virtio-balloon 只有 0.95 GiB/s，virtio-mem 大约 34 GiB/s。对已经 unmapped 的内存，HyperAlloc 还能冲到 4.92 TiB/s，因为这时主要只是修改 allocator 元数据。return+install 大约 4 GiB/s，和 virtio-mem 接近，略低于 huge-page ballooning，差距主要来自 QEMU 原型多出的一次 context switch。

更关键的是，live resize 几乎不打扰 guest。12 线程 STREAM 下，HyperAlloc 的 1st-percentile bandwidth 是 70.1 GB/s，virtio-balloon 和 virtio-mem 在 shrink 时则掉到 30.9 GB/s 和 31.9 GB/s。Clang 16 构建实验里，HyperAlloc 相比 virtio-balloon 又把 memory footprint 压低了 17%，runtime 基本不变；drop page cache 后，它能把 VM 缩到 1.9 GiB，而 virtio-balloon 只能到 8 GiB。三台 VM 错峰运行时，总峰值内存则从 virtio-balloon 的 35.98 GiB 进一步降到 28.11 GiB。不过，这些自动回收收益不只是控制路径更快，也明显受益于 LLFree 更好的抗碎片能力，所以论文评估的是整套联合设计。

## 创新性与影响

HyperAlloc 的新意不是单纯把粒度做成 2 MiB，而是重画了抽象边界：hypervisor 和 guest 围绕同一份 allocator state 协作，但又只共享最必要的状态位，避免把安全边界一并拆掉。相比 virtio-balloon、virtio-mem 和 VProbe 仍然从外部影响 guest allocator 的做法，这是一种更激进也更系统化的设计。

这个方向的影响很实际。对研究来说，它证明 allocator co-design 可以同时带来速度和 DMA safety；对 cloud operator 来说，如果未来 VM memory billing 更细，或者 CXL/disaggregated memory 让闲置 DRAM 更值钱，这类机制会直接影响 consolidation 上限。

## 局限性

HyperAlloc 最大的现实门槛，是它要求 guest 把 page allocator 换成 LLFree。这比装一个 balloon driver 或 hotplug driver 激进得多，论文也明确说，把这个思路移植到传统的 pointer-heavy、lock-based allocator 上既困难又可能有风险。

另外，它的效果和 2 MiB huge page 的可用性绑得很紧，fragmentation 与 page cache 行为都会直接影响可回收量。原型现在还在 QEMU 而不是 KVM 里，install 多一次 context switch；它不能在不结合 hotplug 的前提下长到初始内存以上，也不处理 host 级别的临时 DRAM 超卖。最后，最像它的 DMA-safe 自动回收方案 VProbe 只讨论了，没有进入实测。

## 相关工作

- _Hu et al. (MEMSYS '18)_ - HUB 用 huge page ballooning 降低了 ballooning 的粒度开销，但重新安装仍靠 fault 路径，因此 DMA safety 这关并没有过。
- _Hildenbrand and Schulz (VEE '21)_ - virtio-mem 提供显式的 2 MiB hot(un)plug 和 DMA safety，可它没有自动回收，而且 grow 时要承担预填充成本。
- _Wang et al. (USENIX ATC '23)_ - VProbe 也让 hypervisor 读 guest 内存元数据并做 DMA-safe auto deflation，但它依赖 `struct page` 的分配副作用来跟踪事件，不像 HyperAlloc 那样直接共享 allocator state。
- _Wrenger et al. (USENIX ATC '23)_ - LLFree 是 HyperAlloc 的底座；前者解决的是可扩展、低碎片的页帧分配，后者则把它扩展成 host/guest 双边协作的内存管理接口。

## 我的笔记

<!-- 留空；由人工补充 -->
