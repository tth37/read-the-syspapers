---
title: "Managing Scalable Direct Storage Accesses for GPUs with GoFS"
oneline: "GoFS 把 F2FS 元数据、块分配和 NVMe 队列控制移到 GPU 上，让 GPUDirect Storage 从原始 I/O 通道变成可扩展的 POSIX 文件系统。"
authors:
  - "Shaobo Li"
  - "Yirui Eric Zhou"
  - "Yuqi Xue"
  - "Yuan Xu"
  - "Jian Huang"
affiliations:
  - "University of Illinois Urbana-Champaign, USA"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764857"
tags:
  - storage
  - filesystems
  - gpu
category: gpu-and-accelerator-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

GoFS 试图把 GPUDirect Storage 从“GPU 能直接碰 SSD 的快路径”提升成一个真正可用的文件系统。它保留 F2FS 的磁盘格式，但把元数据管理、块分配和 NVMe 队列处理搬到 GPU 内存里，并用面向 GPU 并行模型的并发控制让大规模 GPU 线程的直接存储访问真正扩展起来。

## 问题背景

GPUDirect Storage 解决了一个很直观的低效点：数据不再必须先读进 host DRAM，再拷贝到 GPU memory，而是可以由 SSD 直接 DMA 到 GPU。但现有软件栈并没有把 host 真正移出关键路径。像 `cuFile`、`GPUfs` 这样的方案虽然缩短了数据搬运路径，文件路径解析、元数据访问、权限检查、块映射这些控制路径仍然要经过 host file system。在高并发 GPU 工作负载下，真正先撞上的瓶颈就变成了 CPU 侧的文件系统控制路径。

已有替代方案各有明显缺口。`BaM` 允许 GPU 直接发 NVMe 命令，但面对的是 raw block device，应用开发者必须自己承担文件系统原本负责的组织和一致性职责。`GeminiFS` 让 host 继续管理元数据，再把一部分元数据预加载到 GPU，这要求访问模式可预测、元数据能放进 GPU memory，而且负载基本只读。论文指出，这些假设对 graph analytics、GNN training、intelligent queries、RAG 等代表性 GPU 应用并不成立，因为它们往往有数据相关的访问模式、很大的元数据规模，以及运行时产生的新写入。

## 核心洞察

这篇论文最重要的判断是：只有当 GPU 同时掌握数据路径和文件系统控制路径时，GPUDirect Storage 才会从一个特化优化技巧变成通用能力。只要 GPU 能自己遍历元数据、分配块、发起 NVMe I/O、执行访问控制，那么“直接存储访问”就不再只是 raw I/O fast path，而是一个可以扩展的 POSIX 文件系统。

这件事不能靠简单移植 CPU 代码完成。GoFS 之所以成立，是因为作者按 GPU 的执行模型重写了文件系统的关键内存结构：并发单位是 warp 和 thread block，而不是彼此独立的 CPU thread，因此更合适的抽象是 batched metadata operation、per-SM 分配状态、level-synchronous pointer traversal，以及直接 DMA 到用户 buffer 的 zero-copy I/O。与此同时，GoFS 又刻意保留 F2FS 的磁盘布局，这样 host 和 GPU 可以共享同一份磁盘镜像，而不必引入一套全新的存储格式。

## 设计

GoFS 包含三部分：host 侧的 FUSE client、GPU 侧 daemon，以及给 GPU 应用调用的 `libgofs`。真正的文件系统逻辑运行在 GPU daemon 里。它在 GPU memory 中缓存 dentry、inode 和块管理状态，通过 `libnvm` 在 GPU memory 中维护 NVMe queue pair，并向上提供 POSIX 风格接口以及 vector/batch API。

为了让文件系统元数据在 GPU 上可扩展，GoFS 做了几项关键重构。首先，它把传统 inode mutex 换成基于 ring buffer 的 range lock，使同一文件上互不重叠的访问区间可以并发执行；冲突检测则用 warp-level reduction 并行完成，这比 CPU 风格的 interval-tree 更适合 SIMT。其次，针对大量小文件场景，GoFS 引入 `bnode`，一次针对目录的 open 就能批量 materialize 许多文件，把 inode/dentry 开销摊到整个 batch 上。再次，块分配采用 per-SM bitmap，而不是中心化分配器，并把一个 thread block 内所有线程的分配请求合并成一次操作，以减少跨线程竞争。

数据指针遍历路径也被重新设计。GoFS 不让每个线程各自从 inode 独立追 direct/indirect pointer，而是采用两阶段的 level-synchronous 遍历：先按层并行扫描 pointer block，找出所有逻辑页地址；再并行抓取叶子数据块。这样可以避免不同线程走到不同深度时造成的 branch divergence 和 straggler。数据路径上，GoFS 把多个 NVMe queue 放进 GPU memory，并让 SSD 与应用 buffer 之间直接做 zero-copy DMA。默认情况下它不维护 page cache，因为目标工作负载大多是流式或吞吐导向。CUDA dynamic parallelism 负责按请求大小自动选择 I/O 线程数，同时 GoFS 既支持 synchronous，也支持 asynchronous 接口。

CPU/GPU 一致性并不是隐藏起来的魔法，而是一个明确的主从协议。GoFS 保持 F2FS 磁盘格式不变，让 GPU 作为 primary owner，host 通过 FUSE 作为 secondary。只读共享是允许的；如果任一方要以读写模式重新打开文件，则必须等待另一方释放 ownership。崩溃一致性继承自 F2FS 的 log-structured 和 checkpoint 机制。保护方面，GoFS 通过 daemon process、GPU virtual-memory isolation，以及由可信 host client 生成并传递的 HMAC 签名身份来执行访问控制，使普通 GPU 用户代码无法伪造文件权限。

## 实验评估

实验平台是一台 16-core Xeon W5-3435X、一张 40 GB A100，以及启用 GPUDirect Storage 的 Samsung 990 Pro SSD。microbenchmark 的结果很好地支撑了论文主张：真正的扩展瓶颈不是 SSD，而是 host 侧控制路径。单 SSD 上，GoFS 达到 `5.5 GB/s` 顺序读、`6.5 GB/s` 顺序写、`5.1 GB/s` 随机读和 `6.1 GB/s` 随机写，已经接近裸设备吞吐。随机写结果尤其有意思，因为 GoFS 基于 log-structured 布局并行追加日志，所以随机写几乎接近顺序写速度。

应用评估覆盖面较广，也基本证明了设计价值。论文在 intelligent queries、graph analytics、GNN training、RAG 和 dataset preprocessing 上报告了相对现有 GPU 存储方案平均 `1.61x` 的加速。对 intelligent queries，GoFS 依靠 batched metadata handling，平均分别比 Basic、`GPUfs`、`cuFile`、`GeminiFS` 快 `6.2x`、`7.5x`、`21.3x`、`2.1x`；作者还用消融实验说明 batch API 单独就贡献了平均 `1.41x`。对 graph analytics，GoFS 相比 CPU-centric baseline 平均快 `1.53x`，相比 `GeminiFS` 快 `1.2x`，与随机读吞吐提升是一致的。RAG 场景里，它又最多比 Basic、`GPUfs`、`GeminiFS` 快 `1.6x`、`1.8x`、`1.4x`，同时避免了 `GeminiFS` 为常驻 `7.2 GB` 元数据而压缩 KV cache 的问题。扩展到四块 SSD 的 RAID0 后，GoFS 可达到 `20.4 GB/s` 顺序读和 `22.1 GB/s` 顺序写。不过，评估也主要集中在单一 GPU 代际、单一 SSD 家族和 F2FS 原型上，因此它证明的是“这个设计点可行且有效”，还不是“已经覆盖广泛部署环境”。

## 创新性与影响

GoFS 的创新点不只是“让 GPU 发 NVMe 命令”，因为 `BaM` 已经展示过这一点。真正新的地方在于，GoFS 把 GPU 提升成完整的文件系统 orchestrator：元数据、块分配、访问控制、崩溃一致性和 host 协调都被纳入同一设计。相较于 `GeminiFS`，它去掉了“靠预加载元数据、服务可预测读多写少负载”的前提；相较于 `GPUfs`，它不是把 host file system 包装成 RPC，而是把 CPU 从关键路径上真正移开。

因此，这篇论文的影响不只在 storage 方向，也在更广义的数据密集型 GPU 系统。凡是需要流式处理大数据集、进行图采样、或者把 GPU 计算和细粒度持久数据访问混在一起的系统，都可以把 direct SSD access 当作标准文件系统服务，而不是一套定制 I/O 子系统。换句话说，它既提出了新机制，也推动了一种新的系统视角：如果 accelerator 正在成为一等计算宿主，它也需要一等的存储软件栈。

## 局限性

GoFS 依赖一套相对特定的硬件和软件环境：支持 GPUDirect 的 GPU 与 NVMe 设备、CUDA、GPU virtual-memory isolation，以及愿意运行 FUSE 和可信 host client 的系统栈。实现上它还默认依赖 F2FS 兼容的磁盘布局；对其他文件系统、remote storage，以及透明的 multi-GPU sharing，论文都留给了未来工作。

CPU/GPU 一致性模型也比较保守。只读共享是支持的，但读写 ownership 仍通过 primary/secondary 协议串行化，因此 CPU 和 GPU 还不是完全对称的文件系统参与者。运行时开销同样没有消失：在 synchronous 模式下，GoFS 在重 I/O 场景中最多可能占用 A100 的 `108` 个 SM 中的 `16` 个做 polling。最后，评估虽然覆盖了多类应用，但平台多样性不足，因此还无法说明它在不同 SSD firmware、其他 GPU 厂商，或真正需要 page cache 的工作负载上会表现如何。

## 相关工作

- _Silberstein et al. (ASPLOS '13)_ - `GPUfs` 让 GPU thread 能调用 host file-system API，但它的 RPC 设计仍把元数据和块管理留在 CPU；GoFS 则把这些职责移到了 GPU。
- _Bergman et al. (USENIX ATC '17)_ - `SPIN` 展示了 SSD 与 GPU 之间的 peer-to-peer DMA，但其上层软件栈仍依赖 host；GoFS 则在 direct access 之上补齐了 GPU-resident file system。
- _Qureshi et al. (ASPLOS '23)_ - `BaM` 让 GPU 直接对 raw storage 发 NVMe 命令，而 GoFS 进一步保留了 POSIX 语义、块分配和崩溃一致性的文件系统结构。
- _Qiu et al. (FAST '25)_ - `GeminiFS` 把数据 I/O 下放到 GPU，同时把元数据预加载自 host，但它依赖可预测、以只读为主的负载；GoFS 则支持按需管理元数据，并把写入路径也纳入 GPU 控制。

## 我的笔记

<!-- 留空；由人工补充 -->
