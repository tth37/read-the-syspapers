---
title: "Accelerating Model Loading in LLM Inference by Programmable Page Cache"
oneline: "PPC 把页缓存策略做成可编程服务，MAIO 再用按服务生成的 I/O 模板，在不改内核和框架的前提下把 LLM 模型加载延迟最高降低 79%。"
authors:
  - "Yubo Liu"
  - "Hongbo Li"
  - "Xiaojia Huang"
  - "Yongfeng Wang"
  - "Hanjun Guo"
  - "Hui Chen"
  - "Yuxin Ren"
  - "Ning Jia"
affiliations:
  - "Huawei Technologies Co., Ltd."
conference: fast-2026
category: ai-era-storage
tags:
  - llm-inference
  - filesystems
  - caching
  - storage
  - memory
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

这篇论文的判断是，LLM 启动慢更像是页缓存策略问题，而不只是 SSD 带宽问题。PPC 把页缓存做成可编程且非侵入的服务，MAIO 再利用按服务可复现的 I/O 模板来预取、放置和淘汰模型页面，因此在内存充足时把模型加载延迟最高降低 `79%`，在内存受限时也能降低 `74%`。

## 问题背景

论文面向的是 MaaS 式弹性推理：服务按需拉起，启动时延直接影响 QoS 和加速器利用率。作者给出的生产案例是，启动一个 `DeepSeek-R1-671B` 推理服务大约要一个小时，其中超过 `70%` 的时间花在加载模型权重。把热点模型放在本地 SSD 上并不够，因为真正决定启动是否快起来的，仍然是页缓存如何在 SSD、DRAM 和加速器之间搬运数据。

作者对既有工作的主要批评是“难部署”。像 ServerlessLLM 这类方案把优化嵌进推理框架，BlitzScale 则依赖特殊互连和硬件共享能力。论文要求的兼容性包括三点：对推理生态透明，不做侵入式内核修改，也不依赖特定硬件。默认内核策略恰好踩中了三个瓶颈：模型加载阶段 SSD 平均带宽只有峰值的大约 `17%`；若按 XPU 亲和性把数据放到对应 NUMA 节点，加载延迟可下降约 `20%`，但内核并不知道数据最终会送到哪块 XPU；当可用页缓存约为模型大小的 `45%` 时，加载延迟会增加 `38%`，因为内核无法判断哪些页面其实已经进入设备内存、在主机侧已经变冷。

## 核心洞察

论文最核心的主张是：模型加载不该继续交给通用的 readahead 加 LRU 去猜。只要模型和运行参数固定，同一个推理服务的加载 I/O 顺序就是可复现的，因此更适合用模板驱动策略，而不是热度驱动策略。PPC 提供安全、非侵入的替换机制，MAIO 则利用按服务生成的 I/O 模板来决定该预取什么、放到哪里、何时淘汰，把内核的隐式猜测变成显式调度。

## 设计

PPC 分成两层。内核侧的 `RFS` 是一个只读 routing file system，堆叠在已有文件系统之上，并镜像其命名空间。每当 `read` 或 `mmap` 的 page fault 发生 cache miss，`RFS` 就把文件句柄、偏移、长度和 PID 封装成非阻塞 `UPC` 事件发给用户态。用户态的 `CPRT` 则把策略加载成动态库，暴露 `ppc_init`、`ppc_prefetch`、`ppc_evict` 等接口，并由 cache manager 执行。淘汰走 `fadvise(..., POSIX_FADV_DONTNEED)`；加载走线程池加 `ioctl`，同时支持可中断预取和 XPU-aware placement。

MAIO 则根据模型名和运行参数生成 service ID，并为它维护一个 I/O template。若模板不存在，就通过记录 miss 事件并把 PID 映射回 XPU worker 来生成；若模板已存在，则直接复用。运行时，MAIO 先把 miss 映射到某个 worker 的 I/O group，再执行三个机制：从当前 miss 一路预取到组尾、但必要时会中断重启的 interruptible prefetching；把预取页放到目标 XPU 最近 NUMA 节点的 XPU affinity loading；以及带默认 `1 GB` 安全间距的 `Burn-after-Reading` (`BAR`) 淘汰。

## 实验评估

实验平台包含四颗 `48` 核 Kunpeng 920 CPU、八张 Ascend 910B2 NPU、`1 TB` DRAM 和 `3.75 TB` SSD，软件栈是 Linux `5.10`、`vLLM-Ascend 0.9.2` 和 PyTorch `2.5.1`。作者评测了从 `7B` 到 `72B` 的五个 Qwen 和 Llama 模型，并把 MAIO 与 `Native`、`EagerLoad`、`PreCache` 以及一个 NPU 版 ServerlessLLM 做比较。核心结果很明确：内存充足时，MAIO 的模型加载延迟最高降低 `79%`；只有 `64 GB` 可用于加载时，降幅仍有 `74%`。端到端启动延迟分别最高降低 `38%` 和 `51%`。消融实验也和设计逻辑一致：Interruptible prefetching 带来最大收益，XPU affinity 再增加约 `6-8.5%`，而 `BAR` eviction 主要在内存受限时发挥作用，可再叠加约 `19-23%` 的收益。

系统开销不大。PPC 在 `memcpy-after-mmap` 微基准上，相比原生文件系统，在 EXT4 上最高增加 `3.7%` 开销，在 XFS 上最高增加 `6.4%`，而 RFUSE 的开销达到 `14-15%`；PPC 自身内存开销大约 `30 MB`。在真实部署的 `Intelligence BooM` 里，MAIO 把 `DeepSeek-R1-671B` 的冷启动模型加载时间从 `649 s` 降到 `452 s`，甚至快过整模型驻留 DRAM 的 `561 s`，因为它把 I/O 和其他启动工作重叠了。需要保留的 caveat 是：ServerlessLLM 的对比只覆盖内存充足、且使用 Transformers 的情况。

## 创新性与影响

相对于 _Fu et al. (OSDI '24)_ 和 _Zhang et al. (OSDI '25)_，论文的新意在于把模型加载优化从推理框架内部下沉到文件系统缓存路径。相对于 _Cao et al. (ATC '24)_ 和 _Yelam et al. (ATC '25)_，PPC 选择的是“stacked file system + 用户态 runtime”，而不是把复杂策略直接塞进内核 hook 里，以此换取更强的策略表达能力和更容易部署的实现。它的影响也偏实用：做 AI 基础设施的人可以把模型加载视为缓存策略问题，而不是继续 fork 推理框架；做操作系统和存储的人则能把 PPC 看成一个比 MAIO 更广的可复用机制。

## 局限性

MAIO 最适合“加载顺序稳定、I/O 仍是启动主瓶颈”的场景。如果推理框架频繁改变加载顺序，或者启动时间主要耗在 tensor formatting 等非 I/O 环节，模板驱动预取的收益就会下降。它也默认有一个控制面在运行参数变化时负责重建模板，这在 MaaS 里自然，在更随意的部署里未必如此。系统层面也有边界：`RFS` 目前只读，只覆盖 `read` 和 `mmap` fault；`BAR` 的 `1 GB` 安全距离是经验值；多服务竞争问题主要交给 cgroup QoS，并没有被完整评测。另外，实验集中在华为 NPU 平台，因此一些具体调参在 GPU、不同 SSD 或其他 NUMA 拓扑上的可迁移性仍然是开放问题。

## 相关工作

- _Fu et al. (OSDI '24)_ — ServerlessLLM 在推理框架内部优化加载；MAIO 则把框架当作黑盒。
- _Zhang et al. (OSDI '25)_ — BlitzScale 依赖硬件辅助共享；MAIO 聚焦本地文件系统加载。
- _Cao et al. (ATC '24)_ — FetchBPF 用 eBPF 定制预取，而 PPC 面向更复杂的用户态策略逻辑。

## 我的笔记

<!-- 留空；由人工补充 -->
