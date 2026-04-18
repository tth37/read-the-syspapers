---
title: "Asynchrony and GPUs: Bridging this Dichotomy for I/O with AGIO"
oneline: "AGIO 让 GPU 线程直接发起显式异步 SSD I/O，把发起与等待解耦，用计算重叠和更高并行 I/O 来隐藏存储延迟。"
authors:
  - "Jihoon Han"
  - "Anand Sivasubramaniam"
  - "Chia-Hao Chang"
  - "Vikram Sharma Mailthody"
  - "Zaid Qureshi"
  - "Wen-Mei Hwu"
affiliations:
  - "The Pennsylvania State University, University Park, PA, USA"
  - "Nvidia, Santa Clara, CA, USA"
  - "Nvidia Research, Santa Clara, CA, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3779212.3790130"
code_url: "https://doi.org/10.5281/zenodo.18333270"
tags:
  - gpu
  - storage
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

AGIO 为 GPU 线程补上了显式异步 SSD I/O，而且整个控制路径不再回到 CPU。它的核心做法是把 I/O 发起与完成解耦，并允许由另一个 GPU 线程在之后消费结果。这样的解耦既能在存在可重叠计算时隐藏微秒级存储延迟，也能在指针追踪这类几乎没有计算可遮挡的代码里，通过提高并发在途 I/O 数量来提升吞吐。

## 问题背景

论文讨论的是一个越来越普遍的失配：现代 GPU 工作负载的数据集经常放不进板载显存，因此必须继续访问主存，甚至直接访问 SSD；但 GPU 的执行模型仍然主要是同步的。线程发起一次操作后会阻塞，再依赖 SIMT 多线程去掩盖延迟。这个思路对 cache miss 或普通内存搬运还算成立，但对 SSD 这种微秒级延迟的访问就明显不够用了。

现有系统只解决了问题的一部分。像 GPUfs、GPUDirect Storage 这样的 CPU 编排路径，虽然可以在 SSD 与 GPU 内存之间搬运数据，但发起和管理传输的仍然是主机 CPU。BaM 更进一步，让 GPU 线程直接编程 NVMe 队列，把 CPU 从控制路径中拿掉；可它暴露给应用的依然是阻塞式接口，发起线程必须等数据到达后才能继续执行。对于 GPU 来说，这种阻塞尤其昂贵，因为 warp 不是一组彼此独立的 Unix 进程。一个 warp 内的线程常常会同时走到 I/O 点，而只要其中某个线程的 I/O 更多或更慢，整个 warp 都会被拖住。

因此，真正的问题不只是“GPU 访问 SSD 很慢”，而是现有 GPU-存储接口仍然强迫应用采用同步消费模型，而存储访问的延迟已经长到必须用异步机制来重新组织程序。

## 核心洞察

论文最重要的论点是：GPU 侧存储 I/O 必须同时在时间和空间上解耦。时间解耦指的是线程应该能尽早发起 I/O，然后继续做别的工作，稍后再等完成；空间解耦则意味着消费数据的线程不必与发起该请求的线程是同一个。

为什么这件事这么关键？第一层收益比较直观：如果未来访问在较早时刻就能知道，那么异步发起就像应用指导的 prefetch，可以把存储延迟和计算重叠起来。第二层收益更有意思，也更不直观。即便几乎没有计算可以拿来重叠，非阻塞发起仍然让线程有机会继续往前跑，提前制造更多 outstanding request，从而更充分地利用 SSD 带宽。再加上等待线程被解耦后，已经准备好的线程可以去消费任何一个已完成请求，而不是傻等自己原先发起的那一个，这就减轻了 SIMT 负载不均带来的伤害。

## 设计

AGIO 暴露给 GPU 线程的 API 很小：`g_aio_read`、`g_aio_write`、`g_wait`，以及 GPU 侧动态分配辅助函数。每个请求都由一个 control block 描述，其中包含目标 buffer、offset、size、device id、application pointer、command id 和可选 tag。这里的 application pointer 用来把某次 I/O 对应的应用元数据从发起线程传给消费线程。

它的编程模型支持三种典型场景。第一种最简单：同一个线程发起 I/O，然后用 `g_wait((cid,*))` 等待这个特定请求完成，这适合 dense matrix 一类较静态的 kernel。第二种面向 BFS 这类动态图应用，任何线程都可以通过 `g_wait((*,*))` 等待任意完成项，从而把“谁发起”与“谁消费”拆开。第三种则处理相关联的多次 I/O，例如 SSSP 中边数组和权重数组必须一起到齐，AGIO 提供分组接口，只有整组完成后才把结果交付给消费线程。

控制路径完全在 GPU 上实现。AGIO 在一组专用 runtime SM 上运行一个 persistent megakernel，应用线程则运行在其余 SM 上。作者没有采用 warp specialization，而是选择了基于 Nvidia Green Contexts 的 SM specialization，因为前者更容易带来放置困难、同步成本和 cache 干扰。在默认配置中，A100 的 108 个 SM 里有 32 个被分给 runtime 线程。

应用线程与 runtime 线程之间通过双向 request/completion 队列通信。每个 channel 都是带有 slot 和原子状态位的 ring buffer。与严格 head/tail FIFO 不同，AGIO 使用 `nextinsert` 和 `nextpoll` 这种“占坑式”索引，允许队列里暂时出现 holes：线程先原子地保留自己的 slot，再各自填充或轮询，从而避免 doorbell 式单点串行化。作者在吞吐实验里选择每个 SM 配 4 个 channel，认为这已经远高于 SSD 本身能提供的 IOPS 上限。

数据路径仍然走直接的 GPU-NVMe 交互。NVMe 队列被映射到 GPU 内存，runtime 线程在 GPU 上直接发命令，SSD 通过 DMA 直接把数据搬到 GPU buffer，中间不需要 CPU bounce buffer。AGIO 还复用了 BaM 的 cache 层，但因为 AGIO 是显式 I/O，而不是 memory-mapped access，所以论文也明确承认它要在底层 system buffer 和应用可见数据结构之间多付出一次拷贝。GPU 侧动态内存则由一个按大小分槽的 pool allocator 管理，必要时还负责 GPU 虚拟地址到 DMA 地址的转换。

## 实验评估

实现运行在 Nvidia A100 40GB PCIe GPU、Micron 7450 NVMe SSD、Linux 6.8、CUDA 12.8 和 Nvidia driver 570 的平台上。工作负载有意分成静态和动态两类。静态工作负载是 `gemv` 与 `kmeans`，其访问模式足够可预测，因此可以较早插入 I/O。动态工作负载则是 BFS、SSSP、PageRank 和 connected components，输入图同时改变平均度和方差，用来刻意制造负载不均。

最核心的结果是，AGIO 相对最强同步基线 BaM-coalesced，在静态工作负载上平均加速 `1.65x`，在动态工作负载上平均加速 `1.32x`。静态部分很好地说明了“重叠”这个论点：`gemv-1M` 和 `kmeans-128` 因为每次传输后能覆盖更多计算，分别达到 `1.54x` 和 `2.33x`；但 `gemv-4K` 只有 `0.93x`，略输给 BaM-coalesced。这个结果反而增加了说服力，因为它表明 AGIO 不是零成本魔法；当所有线程围绕很小的请求同步前进、又几乎没有计算可隐藏延迟时，异步化收益确实会缩小甚至消失。

动态部分更能体现“增加在途 I/O 数量”的价值。在 `k16-k48` 这类低平均度、高方差图上，AGIO 比 BaM-coalesced 快 `1.31x`，因为它对 warp 内负载不均不那么敏感；在 `u16-u48` 这类低平均度、低方差图上，它仍然能比 BaM-coalesced 快 `1.87x`，并且大致追平 BaM-baseline，尽管它并没有依赖人工调好的 work assignment。论文给出的 NVMe 队列快照也显示，AGIO 能更快把存储管线灌满，因此更早结束执行。

与 CPU 编排异步方案的比较同样很关键。使用 CUDA streams 加 cuFileAsync 时，AGIO 在请求粒度达到 `8 KiB` 左右就能跑到约 `3.3 GiB/s`；而 stream 方案要到 `128 KiB` 甚至更大才接近这个带宽。更重要的是，当主机 CPU 同时运行 `sysbench` 时，cuFileAsync 路径会明显退化，而 AGIO 几乎不受影响。最后，小 GPU 实验也支撑了“提升利用率”这一主张：即便只给 AGIO `48` 或 `32` 个 SM，它在很多高方差图上仍能匹配甚至超过使用完整 `108` 个 SM 的 BaM-baseline 和 BaM-coalesced。

总体来看，这组实验比较有说服力。论文明确操纵了自己声称最关键的两个变量，即可重叠计算量和 I/O 并行度，而性能结果也基本沿着这个解释框架展开。

## 创新性与影响

相对 _Qureshi et al. (ASPLOS '23)_，AGIO 的新意不在“GPU 能直接访问 SSD”这件事本身，而在于把这种访问变成显式异步，并把发起与完成解耦后对程序结构产生的影响直接暴露给程序员。相对 _Silberstein et al. (ASPLOS '13)_ 这类 CPU 管理路径，它把主机从控制路径中完全移除。相对 _Wapman et al. (PMAM '23)_ 这种更通用的 GPU 异步编程工作，它讨论的是一个具体的存储 I/O 运行时，包括队列、完成通知和应用层相关请求的组合交付。

因此，这篇论文对 GPU-存储边界上的系统研究者，以及构建 GPU 数据处理运行时的工程实践者都很有价值。它提出的更广义结论是：一旦 GPU 线程真的能直接够到 SSD，阻塞式语义就会成为下一个主要瓶颈。

## 局限性

AGIO 需要应用显式改写，引入 control block、wait 以及有时必须手工传递的 app-specific metadata，因此它并不透明。当前设计只支持通过 `g_wait` 做显式等待，没有实现中断或 callback 风格的完成通知。它的 runtime 采用轮询方式，并且默认要为后台线程保留相当数量的 SM；在 A100 上这还说得过去，但在更小的 GPU 上是否划算就未必了。

系统还继承了把显式异步 I/O 叠加到 BaM 的缓存化 memory-mapped 底座上的一些别扭之处：论文明确提到，在底层 system buffer 与应用数据结构之间会多出一次拷贝。最后，AGIO 的收益明显依赖工作负载。如果既没有足够的计算可以重叠，也没有足够的负载不均让部分线程先跑出去发起更多请求，那么异步机制就可能不如一个做得很好的同步 coalescing 方案，这一点在 `gemv-4K` 结果里已经体现出来。

## 相关工作

- _Qureshi et al. (ASPLOS '23)_ — BaM 证明了 GPU 线程可以直接驱动 NVMe 队列，但它仍然保留了同步访问模型，而 AGIO 放松了这一点。
- _Silberstein et al. (ASPLOS '13)_ — GPUfs 把文件访问带进 GPU kernel，但依赖 CPU 侧编排和多阶段数据搬运，这是 AGIO 试图避免的。
- _Chang et al. (ASPLOS '24)_ — GMT 同样把 GPU 的访问范围扩展到板外层级，但关注点是 memory tiering 策略，而不是面向 SSD 的显式异步 I/O。
- _Wapman et al. (PMAM '23)_ — Harmonic CUDA 研究的是 GPU 上更一般的异步编程结构，而 AGIO 在这一需求之上构建了面向存储的 runtime 与 API。

## 我的笔记

<!-- empty; left for the human reader -->
