---
title: "FastIOV: Fast Startup of Passthrough Network I/O Virtualization for Secure Containers"
oneline: "FastIOV 把 secure container 上的 SR-IOV 冷启动拆成 VFIO 并发、DMA 映射和来宾驱动三类开销，再分别压缩掉这些控制路径成本。"
authors:
  - "Yunzhuo Liu"
  - "Junchen Guo"
  - "Bo Jiang"
  - "Yang Song"
  - "Pengyu Zhang"
  - "Rong Wen"
  - "Biao Lyu"
  - "Shunmin Zhu"
  - "Xinbing Wang"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Cloud"
  - "Zhejiang University"
  - "Hangzhou Feitian Cloud"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696066"
code_url: "https://github.com/AlibabaResearch/fastiov-eurosys25"
tags:
  - networking
  - virtualization
  - isolation
  - serverless
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文的判断很直接：SR-IOV 不适合 secure container，并不是因为 dataplane 不够快，而是因为把 VF 接进 microVM 的控制路径太慢。FastIOV 分别处理 VFIO devset 串行化、DMA 映射里的无效工作，以及 guest VF driver 暴露在关键路径上的初始化开销，把 VF 相关启动成本压低 96.1%，并把端到端平均 / p99 启动时间分别降低 65.7% 和 75.4%。

## 问题背景

SR-IOV 在普通容器上几乎是理想选项：吞吐和时延接近裸机，部署密度高，启动时也只是把预先创建好的 VF 网卡搬进容器 namespace。可 secure container 不一样。像 Kata、Firecracker、RunD 这类系统把应用放进 microVM，VF 必须经过 VFIO 注册、IOMMU DMA 映射，以及 guest 内 NIC driver 初始化，网络才真正可用。

作者的测量说明，这会直接压垮冷启动。在 200 个 secure container 并发启动时，仅仅打开 SR-IOV 就会额外引入 12.2 秒开销，让平均启动时间比无网络基线高 305%。拆开看，VFIO devset 中打开 VF 占了平均启动时间的 48.1%、p99 的 59.0%；DMA 映射 RAM 和 image memory 再分别贡献 13.0% 与 5.6%；guest 里 VF driver 初始化还有 3.4%。所以真正拖后腿的不是 dataplane，而是 passthrough I/O 的控制路径。

## 核心洞察

FastIOV 最重要的洞察，是把 secure-container 的 SR-IOV 启动拆成三类性质不同的问题：VFIO devset 里不必要的串行化、DMA 映射里过早或多余的工作，以及 guest VF driver 本可隐藏却暴露在关键路径上的初始化。既然原因不同，修法也应该分开：独立 VF 的打开操作并行，永远不会 DMA 到的内存不映射，page zeroing 放到 guest first touch 再做，而 NIC bring-up 与其他启动步骤重叠执行。

## 设计

FastIOV 一共做四件事。第一，拆开 VFIO devset 的粗粒度锁：把原来一个全局 mutex 改成 parent 上一个 `rwlock`、每个 VF 上一个独立 mutex，让不同 VF 的打开操作并行，而真正涉及全局状态的路径仍保持串行。第二，把 guest 里的 VF driver 初始化移出关键路径，让 secure-container framework 在继续 launch container 的同时异步 bring up NIC，由 guest agent 在应用用网前确认接口已就绪。

第三，FastIOV 直接跳过 microVM image memory 的 DMA 映射，因为这部分内存是只读镜像和 agent 代码，容器应用不会把 DMA 打到这里。第四，对真正要给设备访问的 RAM，FastIOV 把 zeroing 从物理页分配里拆出来。`fastiovd` 内核模块记录哪些页仍待清零；KVM 在 guest 首次访问某页、EPT miss 即将建立映射时，先让 FastIOV 清零对应 host page，再插入 EPT entry。这样拦截只发生在 first touch。

这套 lazy zeroing 还补了两个例外。像 BIOS、kernel image 这类在 guest 启动前就被 hypervisor 写入的页，会被放进 instant-zeroing 白名单；`virtioFS` 的共享 buffer 则在 guest 把地址写进 vring 时主动触发 EPT fault，避免 host 先写入的数据随后被误清零。实现里作者还修掉了 Kata 的 rebinding 低效点，用 dummy host interfaces 代替真实 host NIC interface 的探测用途，使 VF 不必反复在 host driver 和 VFIO 之间切换。

## 实验评估

实验平台是双路 Intel Xeon Gold 6348、256 GB 内存、25 GbE Intel E810 NIC，secure-container 栈使用 Kata-QEMU，每个 microVM 分配 0.5 vCPU、512 MB 内存，并开启 2 MB hugepages。和已经修复 Kata rebinding 缺陷的 Vanilla SR-IOV CNI 相比，FastIOV 把 VF 相关启动时间压低 96.1%，把端到端平均启动时间降低 65.7%，p99 降低 75.4%。它距离 No-Net 这个下界已经很近：平均只高 39.1%，p99 只高 11.6%；而 Vanilla 分别高 305.2% 与 354.5%。

这些收益不是只在单一点上成立。并发度从 10 到 200 时，FastIOV 的启动时间降幅始终有 46.7%-65.6%；单容器内存增大到 2 GB 时，Vanilla 平均启动时间增加 60.5%，FastIOV 只增加 21.5%。即便是最激进的内存预清零基线 Pre100，平均启动时间也仍比 FastIOV 慢 56.4%。Tinymembench 还表明它没有偷 steady-state 性能，内存吞吐和时延与 Vanilla 的差距都在 1% 以内。

到了系统级 workload 上，这些改动仍然有效。四个 SeBS 风格的 serverless workload 中，FastIOV 把平均任务完成时间降低 12.1%-53.5%，p99 降低 20.3%-53.7%。任务越短、启动时间占比越大，收益越明显。

## 创新性与影响

FastIOV 的创新点不在于新 dataplane，而在于第一次把 secure-container 上 SR-IOV 的冷启动拆成一条跨越 CNI、VFIO、KVM、IOMMU 和 guest driver 生命周期的完整控制路径，并证明最慢的是这条路径的串行结构，而不是 SR-IOV 硬件本身。和 _Zhang et al. (EuroSys '24)_ 的 HD-IOV 相比，它关心的是大量 VF 并发 attach 的时延；和 _Tian et al. (ATC '20)_ 的 coIOMMU 相比，它不依赖延迟映射，而是直接把 eager page zeroing 找出来。

这让它对 secure-container CNI、serverless 平台，以及后续的 passthrough I/O / vDPA 系统都很有参考价值。它给出的不是单个优化点，而是一张可复用的冷启动瓶颈地图。

## 局限性

FastIOV 很依赖云厂商对整套基础设施的控制。它不仅改了 VFIO 和 KVM，还动到了 QEMU、Kata runtime、guest agent、`virtioFS` 等组件，因此并不是一个通用即插即用的 CNI plugin。对其他 SR-IOV 设备也是类似问题：如果换成 RDMA NIC 或 NVMe，它们的 driver 需要配合满足懒清零的安全条件；若 driver 是 closed-source，这件事就未必做得成。

另外，论文的评估范围有意收得很窄。它默认 hugepages 已开启，主要围绕启动路径展开，也没有重新评估 steady-state network throughput。因此更合适的读法，是把它看成一篇 cold-start 优化研究。

## 相关工作

- _Agache et al. (NSDI '20)_ - Firecracker 降低通用 microVM 启动成本，FastIOV 处理剩下的 passthrough networking 路径。
- _Li et al. (ATC '22)_ - RunD 提升 secure container 启动效率，但没有优化 SR-IOV 特有的 VF attach 成本。
- _Tian et al. (ATC '20)_ - coIOMMU 用延迟 DMA mapping 服务 overcommitment，FastIOV 直接攻击 eager page zeroing。
- _Zhang et al. (EuroSys '24)_ - HD-IOV 改善 SR-IOV 的可扩展性，FastIOV 专注高并发 VF attach 时延。

## 我的笔记

<!-- 留空；由人工补充 -->
