---
title: "ODRP: On-Demand Remote Paging with Programmable RDMA"
oneline: "ODRP 用 chained RDMA work requests 把 RNIC 变成远端 swap device，在 swap 路径上实现 4 KB 远端分页分配、理想内存利用率和零 MNode CPU 参与。"
authors:
  - "Zixuan Wang"
  - "Xingda Wei"
  - "Jinyu Gu"
  - "Hongrui Xie"
  - "Rong Chen"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, SEIEE, Shanghai Jiao Tong University"
conference: nsdi-2025
code_url: "https://github.com/SJTU-IPADS/ODRP"
tags:
  - memory
  - rdma
  - disaggregation
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ODRP 通过 chaining native RDMA work requests，把 commodity RNIC 变成真正的 remote swap device。借助 CNode 侧的 client-assisted 预处理，它实现了 `4 KB` 远端分配、`100%` 远端内存利用率，以及 swap 快路径上零 MNode CPU 参与；相对 one-sided static swapping，应用开销为 `4.1%-14.2%`。

## 问题背景

基于 swap 的内存解耦不仅需要远端读写，还必须在页粒度上完成分配、释放、地址翻译和隔离。RDMA 让 one-sided 页面 I/O 很便宜，但动态内存管理仍经过 CPU 驱动的 memory registration；论文测得注册 `4 KB` 和 `1 MB` MR 大约分别要 `80 us` 和 `600 us`。所以旧方案只能在两种坏结果之间选择: 用 static slab 浪费远端内存，或者用 dynamic / two-sided 设计把弱小的 MNode CPU 拉回关键路径。

## 核心洞察

ODRP 的核心判断是: allocator 可以放到 RNIC 上，但前提是 RNIC 只执行固定而很小的逻辑。CNode 预先计算 TT 地址、记录 swap slot 是否已映射，并 piggyback work queue recycle 所需的元数据；RNIC 只负责 queue 更新、TT 写入、页面搬运和完成通知。为了避免 WR chain 膨胀，论文再用两个小 building block 补上 RDMA 语义缺口: 带 modulo 的 FAA 和 `EndianSwap`。

## 设计

ODRP 在每个 CNode 上暴露 Linux `frontswap` backend，并把 MNode 的全部内存预注册成一个大 MR。MNode 再把内存切成 `4 KB` 页，用 FIFO free-page queue 管理，并为每个 CNode 维护一张 translation table（TT）。

RNIC 上实现了四条 WR chains: `load`、`mapped store`、`unmapped store` 和 `invalidate`。关键路径是 `unmapped store`: 它先 FAA 弹出 free page，再把得到的指针做 endian conversion，写进 TT，写入页面数据，并发送完成信号；`invalidate` 则把页放回 queue 并清空 TT。ODRP 通过客户端 piggyback 的 WAIT/ENABLE 索引和 doorbell 状态重用旧 WR chains，而不是让 MNode CPU 重新 post WR。heartbeat 用于回收崩溃 CNode 的页，registration 边界和 protection fault 则把访问限制在各自 TT 内。

## 实验评估

实验平台包含一个共享 MNode 和最多八个 CNodes，每台机器都配有 `12` 核 Xeon E5-2650、`128 GB` DRAM 和 `100 Gbps` ConnectX-5 RNIC；每个 CNode 有 `12 GB` swap 空间。相对 one-sided static、`1 MB` slab 的 one-sided dynamic、`4 KB` two-sided 和 `4 KB` dynamic，ODRP 达到 `100%` 远端内存利用率。one-sided static 只有 `58.3%`，one-sided dynamic 在 Quicksort 且本地内存 `50%` 时会掉到 `55%`。MNode CPU 使用率上，ODRP 的测量值为零，而 one-sided dynamic 和 two-sided 会打满单个 MNode 核心。

应用结果也支持这个机制。相对 one-sided static，ODRP 在 Quicksort 上增加 `9.7%` 开销，在 Kmeans 上增加 `14.2%`，在 Memcached 上增加 `7.2%`，在 VoltDB 上带来 `4.1%` 的吞吐下降。超过 `60%` 的 swap 请求都是 page load，而 ODRP 的 page load 在高 I/O depth 下达到 native one-sided 吞吐的 `92.1%`，延迟为 `5.5 us`，raw RDMA 则是 `2.9 us`。在八个 CNodes 下，ODRP 达到 one-sided static `87.3%` 的 swap throughput，只付出 `14.6%` 的执行时间开销，却把远端内存利用率提升了 `3x`。

## 创新性与影响

和 `Fastswap` 相比，ODRP 把页粒度分配与释放推进 RNIC 侧逻辑，而不是依赖 coarse slab 或 CPU-assisted allocator。和 `RedN` 相比，它把 RNIC 可编程性从“可以做到”变成了“如何系统化做到”: client-assisted decomposition、紧凑 meta operators，以及不依赖 MNode CPU 的 WR recycling。更大的启发是，RNIC offload 可以承载带有分配、隔离和恢复语义的小型有状态服务，而不只是更快的数据通路。

## 局限性

ODRP 强依赖当前 Mellanox/NVIDIA 的能力，包括 enhanced atomics、scatter-gather list 和可修改的 WAIT/ENABLE 元数据。它也不是在所有情况下都“绝对零 CPU”: free queue 空时的恢复、崩溃 CNode 的资源回收，以及懒惰预算监控仍然需要 MNode 软件参与。最后，实验只覆盖了单 MNode 的 Linux `4.15` / ConnectX-5 集群，多 MNode 和非 swap 场景仍未验证。

## 相关工作

- _Amaro et al. (EuroSys '20)_ - _Fastswap_ 让基于 Linux frontswap 的 far memory 变得高效，而 ODRP 可以看成是把其中 coarse 或 CPU-assisted 的远端分配器替换成 page-granularity RNIC offload。
- _Reda et al. (NSDI '22)_ - _RedN_ 从理论上确立了 chained RDMA WR 的可编程性，而 ODRP 展示了如何把这种能力包装成一个完整的 remote-memory service。
- _Qiao et al. (NSDI '23)_ - _Canvas_ 通过隔离和 adaptive asynchrony 优化 CNode 侧的 remote swapping，而 ODRP 则直接改变 remote device 本身，让细粒度分配无需 CPU 中介。

## 我的笔记

<!-- empty; left for the human reader -->
