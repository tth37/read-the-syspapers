---
title: "CEMU: Enabling Full-System Emulation of Computational Storage Beyond Hardware Limits"
oneline: "CEMU 在主机执行 CSD 任务时冻结虚拟机时间，把功能正确性与设备算力建模解耦，从而做可配置的全系统 computational storage 研究。"
authors:
  - "Qiuyang Zhang"
  - "Jiapin Wang"
  - "You Zhou"
  - "Peng Xu"
  - "Kai Lu"
  - "Jiguang Wan"
  - "Fei Wu"
  - "Tao Lu"
affiliations:
  - "Huazhong University of Science and Technology, Wuhan, China"
  - "Research Center for High Efficiency Computing Infrastructure, Zhejiang Lab, Hangzhou, China"
  - "DapuStor, Shenzhen, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790137"
tags:
  - storage
  - hardware
  - virtualization
  - filesystems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CEMU 是一个建立在 QEMU 和 FEMU 之上的全系统 computational storage 模拟平台。它把卸载任务放到主机上真实执行以保留系统行为，再冻结来宾虚拟机时间并单独注入建模后的计算时延，因此即使被模拟的 CSD 算力强于主机，也能保持较高的系统保真度。

## 问题背景

这篇论文抓住的是 CSD 研究里一个长期存在的缺口：我们想研究的是“带计算能力的存储系统”整体怎么工作，但现有平台通常只能让我们看到其中一半。真实硬件平台如 SmartSSD 的优点是端到端路径都在，软件、缓存、驱动、I/O 干扰都是真的；缺点是昂贵、难获取，而且算力被板上的 FPGA 或嵌入式核绑定。纯软件模拟器则相反，便宜又灵活，却往往不运行真实的全系统软件栈，于是 page cache、主机-设备同步和存储/计算干扰都消失了。

作者强调，这些缺失会改变结论。比如 LevelDB 的 compaction 卸载到 CSD 后，可能因为绕开主机 page cache 反而变慢；压缩时延也会随数据模式变化，常数延迟模型并不可靠。现有软件接口还很碎片化，有的甚至把 `pread` 重载成“触发盘内计算”。所以论文要做的不是再堆一个原型，而是做一个既像模拟器一样可配置、又像真实系统一样保留端到端行为，并且贴近 SNIA/NVMe 标准的平台。

## 核心洞察

论文最重要的判断是：功能保真和“设备看起来有多快”不必来自同一个物理执行资源。主机 CPU 可以承担卸载函数的真实执行，从而保留真实代码路径和真实数据流动；与此同时，模拟器再单独决定从来宾视角看，这个任务应该耗时多久。只要这两件事被解耦，CEMU 就既能模拟算力弱于主机的 CSD，也能模拟算力远强于主机的未来 CSD。

这个判断之所以成立，是因为虚拟机时间本身可控。当输入数据已经进入设备内存、CSD 任务开始在主机上运行时，CEMU 会暂停虚拟机并冻结其虚拟时钟。主机上的计算继续进行，但来宾系统无法观察这段真实时间流逝。等主机执行完成后，CEMU 恢复虚拟机，再按照模型补上应有的停顿。对来宾而言，真正存在的只有建模后的设备时延。围绕这个机制，论文再配上一套遵循标准的软件栈，使得存储 namespace、memory namespace、compute namespace 真正构成一个连贯的 CSD 系统。

## 设计

CEMU 分成模拟器和软件栈两大部分。模拟器一侧，它在 QEMU/FEMU 之上扩展出 NVMe、CSF、调度和 FEMU 存储四个模块，并暴露普通存储 namespace、memory namespace、compute namespace 三类接口。CSF 支持 eBPF、共享库和 FPGA bitstream 三种执行环境。

性能建模围绕 compute unit 和比例因子 `S_csf` 展开。主机上的真实执行时间是基准，再通过缩放得到被模拟设备上的执行时间。若目标 CSD 比主机还快，就依赖 VM freezing 来把真实执行时间隐藏在来宾视角之外。论文报告其暂停/恢复开销约为 `21 us`，所以太细粒度的任务需要先合并。调度模块本身可插拔，不同 compute unit 还能模拟异构加速器。

存储一侧，CEMU 复用 FEMU 的闪存时序和 FTL 行为，再补上 PCIe 传输建模，避免把主机到设备、设备到设备的数据搬运当成“免费”。多盘情况下，它把每个 CSD 的设备内存暴露到 BAR 空间，并利用 PCIe peer-to-peer 在 CSD 之间直接传数据。软件栈一侧最核心的新东西是 FDMFS。它把 CSD 设备内存抽象成文件，因此应用可以用 `fallocate` 分配内存、用 `copy_file_range` 搬数据、用 `pread` 读取输出，并通过 `ioctl` 触发计算。整套栈同时支持 direct 和 indirect 两种 SNIA 编程模型，还接进了 `io_uring`。

## 实验评估

实验分成三层：设备级精度验证、软件栈开销分析，以及两个全系统 case study。硬件验证部分，作者用 Samsung SmartSSD 和 ScaleFlux CSD2000 对 CEMU 做标定和对比，任务包括 `grep`、`kNN`、`lz4`、SQL query 和压缩。结果里端到端误差都控制在 `10%` 以内：单个 SmartSSD 平均精度 `96%`，三个 SmartSSD 平均 `95%`，CSD2000 平均 `97%`。这说明它不是只在一个微基准上对齐。

软件栈分析部分也比较扎实。direct 模型下总软件开销不超过 `7.5%`，FDMFS 本身很轻量。indirect 模型在单 chunk、小粒度任务上更快，因为它省掉了频繁的主机-设备同步；一旦 chunk 变大或开始流水化，这个差距就明显缩小。扩展性结果也很可信：`lz4` 的吞吐几乎线性涨到六个 CSD，而 LevelDB 更早饱和，因为主机侧仍然有不少工作没消失。

真正有意思的是两个 case study。LLM training 里，作者把 Smart-Infinity 移植到 CEMU，只改了大约 200 行代码；按真实 SmartSSD 参数配置的 CEMU 与硬件平台平均偏差仅 `2.4%`。CSD 数量从 1 增长到 3 时，训练时间能提升大约 `2x-2.5x`。但更重要的结论其实是负面的：即便把被模拟 CSD 的计算带宽提高到极端设置，额外收益也只有最高 `2.4x`，因为瓶颈转移到了 I/O。

LevelDB case study 更能说明“全系统平台”和“只看局部加速”之间的差别。100% 写入负载下，在主机和 CSD 算力相当时，LevelDB-CSD 吞吐从 `501 Kops/s` 提升到 `721 Kops/s`。但在混合读写场景里，LevelDB-CSD 可能反而变差，因为盘内 compaction 失去了主机 page cache 的好处，还在闪存内部制造了 I/O 干扰。作者进一步展示，一个简单的 I/O 优先级调整可以缓解这种干扰；而在多 CSD 布局优化后，P2P 传输量从 `17.3 GB` 降到 `12 GB`，吞吐提升 `7.4%`。整体来看，这些实验很有力地说明，CEMU 的价值不只是把设备时延“拟合准”，而是能暴露出简化模拟器看不到的系统级副作用。

## 创新性与影响

相对 _Li et al. (FAST '18)_，CEMU 的创新点不只是继续做 SSD 模拟，而是把 SSD 模拟器扩展成一个具备可配置计算子系统、标准化 namespace 和软件栈的 computational storage 平台。相对 _Barbalace et al. (Middleware '20)_ 和 _Wilcox and Litz (CHEOPS '21)_，它的关键推进是从“只能做功能性 offload 模拟”走向“功能执行与性能建模解耦”。相对 _Yang et al. (FAST '23)_，它的软件贡献在于尽量保持现有 I/O 语义清晰，不把普通文件读写和设备内执行混为一谈。

这使得论文既是基础设施论文，也是一篇方法论文。它既给 CSD 研究提供了共享平台，也提醒读者：near-storage 的收益必须在全系统里重新验证。

## 局限性

CEMU 的灵活性仍然依赖标定。每个 CSF 的比例因子都需要来自真实硬件测量、外部模拟器或别的性能模型；如果标定不准，结论就不会准。VM freezing 本身也有下界，论文给出的暂停/恢复开销约为 `21 us`，所以特别细粒度的任务必须做批处理；而且 QEMU 目前只能冻结全局 VM 时钟，做不到更细的 per-vCPU 时间控制。

部署层面也有明显边界。CEMU 只能在单机内扩展，因此总闪存容量、总带宽和可模拟的 CSD 数量都受主机 DRAM 与 CPU 核数限制。FDMFS 当前要求预分配连续设备内存，若要调整大小，往往需要删除旧文件再重建新文件。最后，虽然验证结果已经相当不错，但覆盖面仍有限：只有两类真实硬件和一组代表性 kernel，还不足以证明所有未来 CSD 工作负载都能同样精确地被建模。

## 相关工作

- _Li et al. (FAST '18)_ — FEMU 提供了便宜且高保真的 SSD 模拟基础，而 CEMU 在此之上补上计算子系统、CSD 调度和标准化 namespace。
- _Ruan et al. (USENIX ATC '19)_ — INSIDER 是真实 FPGA in-storage computing 平台，但它对硬件的依赖和对存储子系统的简化正是 CEMU 试图摆脱的限制。
- _Barbalace et al. (Middleware '20)_ — blockNDP 同样采用 QEMU 式全系统模拟，而 CEMU 进一步加入了可配置的性能建模，使主机上的真实执行不再限定被模拟 CSD 的表观速度。
- _Yang et al. (FAST '23)_ — `lambda-IO` 关注统一的软件栈，而 CEMU 更强调与 SNIA/NVMe 标准以及现有 POSIX 接口的兼容性。

## 我的笔记

<!-- 留空；由人工补充 -->
