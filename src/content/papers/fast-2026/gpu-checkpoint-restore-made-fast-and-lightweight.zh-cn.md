---
title: "GPU Checkpoint/Restore Made Fast and Lightweight"
oneline: "GCR 把 GPU 控制状态交给驱动检查点，数据缓冲区单独复制，再用 CPU shadow execution 做低开销增量检查点，把运行期开销压到 1% 以内。"
authors:
  - "Shaoxun Zeng"
  - "Tingxu Ren"
  - "Jiwu Shu"
  - "Youyou Lu"
affiliations:
  - "Tsinghua University"
conference: fast-2026
category: ai-era-storage
tags:
  - gpu
  - fault-tolerance
  - serverless
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`GCR` 把 GPU checkpoint/restore 拆成两条路径：GPU control states 继续交给驱动，GPU data buffers 单独复制。它再通过 page-table restore 保持虚拟地址一致，并用 CPU 上的 shadow execution 与 dirty templates 支持增量检查点，把 checkpoint 延迟相对 `cuda-ckpt` 降低 `72.1%`，同时把运行期开销压到 `1%` 以下。

## 问题背景

论文关注三类都依赖系统级 GPU checkpoint/restore 的场景：弹性 GPU serverless 扩缩容、快速 GPU 任务切换，以及故障恢复型 GPU 计算。作者强调，这应该是一个跨推理、训练和 HPC 工作负载复用的系统原语，而不是让每个框架自己做一套。

现有两类方案分别卡在不同地方。`cuda-ckpt` 这类 driver-integrated 方案几乎没有运行期开销，也更适合处理驱动私有的 GPU control states，但复制 GPU data buffers 太慢，在作者的平台上 checkpoint 只有 `3.0 GB/s`、restore 只有 `7.2 GB/s`。`PhOS` 这类 interception-based 方案能靠异步复制拿到更高带宽，却必须拦截和序列化大量 GPU driver API，导致控制状态处理昂贵，并把正常执行平均拖慢 `8.7%`，峰值 `49.6%`。

增量检查点同样失败。论文在 `Llama2-7B` 推理实验里发现，理想增量 checkpoint 只需 `4.1 GB`，但两个基线仍要写大约 `30 GB`，放大了 `7.2x`。

## 核心洞察

最重要的命题是：GPU control states 和 GPU data buffers 不该用同一种机制保存。控制状态体量小、语义由驱动私有实现掌握，适合继续交给驱动的黑盒 checkpoint/restore；数据缓冲区本质上是大块字节数据，更适合显式的高带宽异步复制。两条路径拆开以后，最关键的正确性要求就变成了恢复时保持 GPU 虚拟地址不变。

增量 checkpoint 也遵循同样思路。细粒度 dirty tracking 必须做，但不能放在 GPU 执行关键路径里。`GCR` 把 dirty-buffer identification 移到 CPU 上，用简化模板做 shadow execution，只计算脏地址和长度。

## 设计

`GCR` 由一个库和一个 checkpoint backend 组成。正常执行期间，它通过 `LD_PRELOAD` 只拦截 GPU memory allocation 和 deallocation，记录每个 buffer 的地址和长度；这部分元数据极小，论文报告运行期开销低于 `1%`。

Checkpoint 时，`GCR` 先把被拦截到的 GPU data buffers 异步复制到 CPU memory，再只释放这些 buffers 背后的 physical memory，避免后续 driver-integrated checkpoint 重复保存。之后驱动内建 checkpoint 负责剩余的 GPU control states，包括 GPU page table。恢复时，驱动先恢复控制状态和保存下来的 page table，`GCR` 再用 `cuMemCreate` 创建新的 physical memory，并借助 `cuMemMap` 把它重新映射到原先的 virtual addresses。论文报告 page-table preservation 带来的额外控制状态开销低于 `0.1%`，而 `27.3 GB` buffer 的一次重映射只需 `432 us`。

增量 checkpoint 依赖 offline 生成的 dirty templates。`GCR` 在 PTX 层做 symbolic execution，把 kernel 收缩成只关心 store instructions 的小型 C++ 函数，用 kernel arguments 与 launch dimensions 算出 dirty address 和长度。运行时它拦截 kernel launch，把实参喂给模板，再在 CPU 上并行做 shadow execution。对支持的 kernels，这一步只需微秒级时间和不到 `1 MB` 的 CPU 内存；对闭源或难分析的 kernels，则退回保守标记或关闭增量 checkpoint。

## 实验评估

实验平台是两张 `A100-40GB` GPU，带 `NVLink` 和 `PCIe 4.0`，软件栈包括 `CUDA 12.6`、`PyTorch 2.7.1`、`Transformers`、`vLLM` 和 `DeepSpeed`。工作负载覆盖 LLM inference、LLM 与 DNN training，以及一个 HPC 分子动力学应用。

在 elastic GPU serverless scaling 场景中，`GCR` 的冷启动延迟相对 `cuda-ckpt` 平均降低 `54.2%`，相对 `PhOS` 降低 `87.1%`。它的 restore 带宽达到 `23.0 GB/s`，约为 PCIe 上限的 `92%`，分别比两个基线高 `3.4x` 和 `11.5x`。在快速任务切换场景里，`GCR` 把总切换延迟相对 `cuda-ckpt` 降低 `71.6%`，相对 `PhOS` 降低 `74.1%`。在完整 checkpoint 实验中，它把 checkpoint 延迟相对 `cuda-ckpt` 降低 `72.1%`，相对 `PhOS` 降低 `63.6%`，同时把 checkpoint 带宽做到 `20.5 GB/s`。增量 checkpoint 则把 checkpoint 大小相对第一次平均降低 `86.6%`，延迟降低 `43.8%`；正常执行期间，系统平均仍保持 `99.9%` 以上的原始吞吐。

## 创新性与影响

这篇论文的新意不在于单独再做一个更快的 copy path，而在于把三件事组合起来：driver-integrated checkpoint 负责控制状态，只对数据缓冲区做拦截复制，再用 symbolic dirty templates 支持低开销增量 checkpoint。它因此会对做 GPU serverless、多租户调度和故障容错训练基础设施的人更有参考价值。

## 局限性

`GCR` 依赖厂商提供 driver-integrated checkpoint/restore、底层 GPU virtual-memory API 可用，以及 kernel 具备足够可见性以生成 dirty templates。对闭源或文档不足的 kernels，增量 checkpoint 可能只能关闭或退回粗粒度标记。当前原型也只把 checkpoint 存在 CPU memory，checkpoint 前会同步所有 kernels，concurrent checkpoint/restore 仍是未来工作。实验在 NVIDIA `A100` 上很强，但跨厂商可移植性还没有被实测验证。

## 相关工作

- _Wei et al. (SOSP '25)_ — `PhoenixOS` / `PhOS` 通过拦截整套 GPU API 并结合 validated speculation 做 C/R；`GCR` 则只拦截内存管理路径，并把控制状态重新交回驱动。
- _Yang et al. (SoCC '24)_ — 这项工作借助修改过的驱动与并行化机制优化 GPU C/R；`GCR` 面向 commodity drivers，并额外补上了增量 dirty-buffer tracking。
- _Fu et al. (OSDI '24)_ — `ServerlessLLM` 在应用层为 serverless LLM inference 做恢复；`GCR` 则提供对框架透明的系统级 GPU state C/R。
- _Lee et al. (ICS '19)_ — `GPU Snapshot` 面向 GPU-dense 系统并依赖更强的硬件假设；`GCR` 则针对现有生产 GPU 设计。

## 我的笔记

<!-- 留空；由人工补充 -->
