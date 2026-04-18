---
title: "Cylon: Fast and Accurate Full-System Emulation of CXL-SSDs"
oneline: "Cylon 用动态 EPT 重映射让 CXL-SSD 命中走直接 load、未命中落到 FEMU，使全系统 CXL-SSD 研究同时具备速度、保真度与策略扩展性。"
authors:
  - "Dongha Yoon"
  - "Hansen Idden"
  - "Jinshu Liu"
  - "Berkay Inceisci"
  - "Sam H. Noh"
  - "Huaicheng Li"
affiliations:
  - "Virginia Tech"
conference: fast-2026
category: flash-and-emerging-devices
code_url: "https://github.com/MoatLab/FEMU"
tags:
  - storage
  - memory
  - caching
  - hardware
  - virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Cylon 是一个面向 CXL-SSD 的全系统模拟器，它让快路径真正像内存访问，而只把未命中送进 SSD 仿真。它的关键机制是 Dynamic EPT Remapping 加 Shared EPT Memory，这让 QEMU 原本昂贵的每次访问 trap 成本大幅下降，因此能够在不修改软件栈的前提下同时重现亚微秒级命中、几十微秒级未命中，以及缓存策略本身的效果。

## 问题背景

像 Samsung CMM-H 这样的真实原型已经证明，CXL 后面的 SSD 可以用一个小型 DRAM cache 吸收热点访问，再用大容量 NAND 提供低成本、字节可寻址的扩展空间；问题在于，这类平台数量少、细节黑盒，而且缓存行为大多被固件锁死。研究者很难系统地比较 eviction、prefetching 或 host-device cooperation。现有软件工具也无法同时满足需求。Trace-driven 和 cycle-accurate simulator 能看到更多设备内部细节，但速度太慢，或者与真实 OS 和应用脱节。上游 QEMU 虽然能跑 unmodified guest，却把每次 CXL 访问都压到 MMIO 和 VM-exit 路径上，使延迟膨胀到 `10-15 us`，直接抹掉了 CXL-SSD 最关键的“命中像内存、未命中像存储”这一不对称性。论文要补上的，正是这样一个既保留完整软件栈、又保留真实访问分层的全系统平台。

## 核心洞察

论文最核心的命题是，CXL-SSD 模拟器不该让所有访问走同一条路径。只要某页已经在模拟出来的 DRAM cache 中，CPU 就应该像访问普通内存一样，通过二级地址翻译直接命中它；只有 cache miss 才应该 trap 到模拟器，进入 SSD backend，并在访问结束后更新驻留状态。这样一来，cache hit 不再为 hypervisor 切换付费，cache miss 仍然保留可分析的 NAND timing，而且缓存驻留也被显式化，足以支撑 eviction、prefetching、observability 和 application hints 的系统化研究。

## 设计

对 guest 来说，Cylon 就是一个标准的 CXL 2.0 Type-3 memory device，外部可见容量等于 backend SSD 容量，而 DRAM cache 完全隐藏。关键机制是 Dynamic EPT Remapping。每个页只有 `Direct` 和 `Trap` 两种状态。在 `Direct` 下，EPT entry 直接指向作为 CXL-SSD cache 的 host DRAM，因此 guest 的 load/store 以普通内存访问方式完成；在 `Trap` 下，权限位被清零，下一次访问就会触发 EPT violation，把请求交给 KVM 再交给 FEMU。

Miss 路径遵循严格的 fill-and-flip 协议。Cylon 先把 guest physical address 映射成 SSD offset，经由 FEMU 读取数据页，将其插入 DRAM cache，再重写该页的 EPT entry，使后续访问能直接绕过模拟器。Clean eviction 只需翻回 `Trap`；dirty eviction 则要先写回。为了降低过渡成本，Cylon 采用定向的 `INVEPT` 和 `INVVPID` invalidation，并把 leaf EPT entries 预分配到一段由 KVM 与 userspace 共享的连续区域。这样 FEMU 就能按逻辑页号写入紧凑 descriptor，而不必在每次 fill 或 eviction 时都支付一次 KVM ioctl 和 page-table walk。

Cylon 在这条快路径之上又叠加了策略框架。它支持可插拔的 eviction 和 prefetching 模块，可通过 accessed-bit sampling 或 PEBS 恢复 hit-side 可观测性，并提供面向应用的控制面，支持 prefetch、pin、evict、tuning 和 statistics。由于 backend 与 policy 层是模块化的，同一套框架也能继续用来探索超出 CMM-H 的 CXL-storage 设计。

## 实验评估

这篇论文的评估有说服力，是因为它同时验证了模拟器开销和与真实硬件之间的行为一致性。作者主机上的 local DRAM 约为 `90 ns`，remote NUMA DRAM 约为 `150 ns`。当命中率被强制设为 `100%` 时，Cylon 的访问延迟约为 `0.16 us`，几乎就是 remote DRAM；而 QEMU 的 MMIO 式 CXL 路径则是 `14.74 us`。把 NAND latency 设为零、只看 miss 路径时，最初基于 ioctl 的设计需要 `23.04 us`，引入 Shared EPT Memory 后降到 `16.27 us`。在一个 `8 GB` working set 和 `4.8 GB` cache 的 pointer-chasing 工作负载上，Cylon 也呈现出正确的双峰分布，命中侧平均延迟为 `977 ns`，而 QEMU 仍是一个约 `14.6 us` 的单峰。

与 Samsung CMM-H 的对比采用 normalized working-set size，因为 CMM-H 的 DRAM cache 是 `48 GB`、backend 是 `1 TB`，而 Cylon 模拟的是更小设备。趋势匹配得很好。只要 working set 能放进 cache，两者都停留在纳秒级；一旦超过 cache 容量，延迟就一起跳到几十甚至上百微秒。带宽上也呈现相同的两阶段行为：Cylon 一直维持 remote-NUMA 级别带宽，直到 cache 被填满；CMM-H 会因原型 controller 的额外开销更早下滑；但在 cache 饱和之后，两者最终都收敛到 NAND-bound 吞吐。Redis YCSB-C 与 GAPBS 也沿着同样的边界变化，只是在 cache-resident 区间里，Cylon 因 hit path 更接近理想 DRAM 而略快一些。

更重要的是，Cylon 不是只在复刻硬件。策略实验表明，它确实能承担研究平台角色。Eviction choice 在存在局部性时影响很大：例如在微基准中，`Stride-4096` 的 hit rate 从 FIFO 下的 `0%` 提升到 LIFO 下的 `60%`。Prefetch 只有在存在空间局部性时才有效；同样是 `Stride-4096`，Next-`N` 会把 hit rate 从 `18%` 拉到 `86%`，而随机访问基本一直停留在约 `25%`。

## 创新性与影响

相对于上游 QEMU，这篇论文的新意不在于“又做了一个 CXL device model”，而在于把 cache-hit path 从 MMIO 挪到了 second-stage page translation 上。相对于 trace-driven 或 cycle-accurate 的 CXL-SSD simulator，Cylon 用一部分最微观 controller 细节换来了能启动 stock kernel、能运行真实 workload、同时还保留命中与未命中不对称性的系统级平台。因此，它既能服务于探索新型 CXL-SSD 组织方式的架构研究者，也能服务于研究 eviction、prefetching 与 cooperative host-device caching 的系统研究者。

## 局限性

这篇论文更像是在刻画“理想化的 CXL-SSD”，而不是逐时钟复刻 Samsung 原型。Cylon 有意把 cache hit 建模为 remote-NUMA DRAM，也就是约 `150 ns`，而实测的 CMM-H hit path 更接近 `800 ns`。它的 backend 也仍然带有理想化成分：当前实现把 SSD backend 放在 host DRAM 中，并依赖 FEMU 的 timing model 表达 NAND 行为，因此可模拟容量仍受 host memory 约束，而 SPDK/NVMe backend 还是未来工作。最后，面向应用的接口更多被当作机制提出，而不是以完整 co-design case study 深入评测；many-core 可扩展性也更多是被论证，而不是被彻底压测。

## 相关工作

- _Yang et al. (ATC '23)_ - MQSim-CXL 提供了可配置的 trace-driven CXL-SSD simulation，而 Cylon 保留了真实运行中的 host software stack，并支持 unmodified workload。
- _Chung et al. (MASCOTS '25)_ - OpenCXD 支持结合真实设备的 hybrid experimentation，但它依赖专门硬件，并且抽象掉了 NAND timing。
- _Li et al. (FAST '18)_ - FEMU 是 Cylon 借用的 SSD timing backend，但 FEMU 本身并不提供 CXL.mem semantics，也没有无 VM-exit 的 hit path。
- _Wang et al. (TCAD '25)_ - CXL-DMSim 把全系统 CXL simulation 推向 cycle accuracy，而 Cylon 更强调面向策略和 workload 研究的实时执行能力。

## 我的笔记

<!-- 留空；由人工补充 -->
