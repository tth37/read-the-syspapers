---
title: "Nemo: A Low-Write-Amplification Cache for Tiny Objects on Log-Structured Flash Devices"
oneline: "Nemo 通过缩小 flash cache 的哈希空间、按 Set-Group 批量刷写与淘汰，并配合 Bloom filter 索引，把 tiny-object 的写放大压到接近下界。"
authors:
  - "Xufeng Yang"
  - "Tingting Tan"
  - "Jingxin Hu"
  - "Congming Gao"
  - "Mingyang Liu"
  - "Tianyang Jiang"
  - "Jian Chen"
  - "Linbo Long"
  - "Yina Lv"
  - "Jiwu Shu"
affiliations:
  - "Xiamen University, Xiamen, China"
  - "Chongqing University of Posts and Telecommunications, Chongqing, China"
  - "Openharmony Community, Beijing, China"
  - "Tsinghua University, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790191"
code_url: "https://github.com/XMU-DISCLab/Cachelib-Nemo"
tags:
  - storage
  - caching
  - databases
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Nemo 的出发点是：在现代 log-structured SSD 上，tiny-object cache 的主要浪费往往已经不是设备 GC，而是缓存布局导致的应用级重写。它保留 set associativity 的查找便利性，但只在 Set-Group 足够“满”时才按组刷写和淘汰，再用 Bloom-filter 索引控制元数据成本。论文在 Twitter trace 上测得的稳态写放大为 `1.56`，而 FairyWREN 是 `15.2`。

## 问题背景

tiny-object KV cache 同时受 miss ratio、延迟、metadata 成本和 flash 磨损约束。log-structured 设计写得很漂亮，但当对象只有几百字节时，精确索引会很贵；set-associative 设计则节省内存，却可能为了插入一个 200B 对象去重写整个 4 KB set，于是 application-level write amplification 成为主导成本。

论文强调，ZNS 和 FDP 主要解决的是 device-level amplification，不是 cache 自身的写放大。Kangaroo 和 FairyWREN 仍然要把对象迁移进一个哈希空间很大的 set 布局，所以每次重写 set 时真正新增进去的对象很少。作者复现并修复 FairyWREN 的开源代码后，在平均对象大小 `246 B` 的 Twitter trace 上测到超过 `15x` 的写放大，并把原因归结为低 set fill rate，而不是 SSD 内部机制。

## 核心洞察

这篇论文最重要的命题是：tiny-object flash cache 在 flush 前不该一味避免碰撞，反而应该主动提高 collision probability，让每次真正落到 flash 的写里聚集更多有用对象。Nemo 因而放弃 FairyWREN 那条 log-to-set migration 路径，改为直接把高填充度的 Set-Group 写入 flash。

之所以成立，是因为 lookup 依赖的逻辑单位与 write batching 依赖的物理单位不必一致。Nemo 在 Set-Group 内部仍保留 set associativity，使定位逻辑保持简单；但它缩小哈希空间，并等到同组中许多 set 都较满时才持久化。这样写放大近似等于 Set-Group fill rate 的倒数。

## 设计

Nemo 把 flash 组织成不可变的 Set-Group（SG），每个 SG 包含大量 4 KB set，并在内存中保留少量 buffered SG。系统按 SG 粒度刷写和淘汰，而不是先写前端 log、再逐个迁移到 set，因此直接去掉了 FairyWREN 中最伤写放大的那条反复 read-modify-write 路径。

第一个难点是短期哈希偏斜：一个新 SG 里常常只有某个 set 很早填满，其他 set 仍然稀疏。Nemo 用 buffered in-memory SG、probabilistic flushing，以及从被淘汰 SG 中挑选 hot objects 回写到待 flush SG 这三个机制来对抗它，从而把持久化时机尽量往后拖，直到 SG 更“满”为止。

第二个难点是索引。精确维护 object-to-SG mapping 会吃掉内存优势，所以 Nemo 使用 Parallel Bloom Filter Groups（PBFG）。它不再按 SG 维护粗粒度 Bloom filter，而是按 set offset 组织：不同 SG 中、同一 intra-SG offset 的 set 组成一个 Set-level PBFG。lookup 时先算出 intra-SG set，再查询对应 PBFG 找到 candidate SG，并并行读取这些 set。

第三个难点是淘汰。Nemo 把 PBFG cache 提供的 recency 信号，与 1-bit access bitmap 提供的 frequency 信号结合起来，并对不再热门的 PBFG 周期性 cooling。这样既能在 SG 淘汰时回写真正的 hot objects，又不必维护昂贵的细粒度计数器。

## 实验评估

作者把 Nemo 实现在 CacheLib 中，在一台 `24` 核服务器、`128 GB` DRAM 和 Western Digital ZN540 ZNS SSD 上进行实验。使用合并后的 Twitter traces、平均对象大小 `246 B` 时，Nemo 的稳态写放大为 `1.56`，FairyWREN 为 `15.2`，普通 set-associative cache 为 `16.31`，Kangaroo 为 `55.59`。完全 log-structured 的 cache 可以做到 `1.08`，但 metadata 开销超过 `100 bits/object`。

Nemo 同时保持了较低元数据成本。它的 metadata 为 `8.3 bits/object`，略低于 FairyWREN 的 `9.9 bits/object`。tail latency 也更稳：`p99` 读延迟约 `131 us`，FairyWREN 约 `350 us`；`p9999` 分别为 `523 us` 与 `1488 us`。与此同时，两者 miss ratio 基本相近。ablation 也与设计解释一致：SG fill rate 从 naive Nemo 的 `6.78%`，提升到 buffered SG 加 probabilistic flushing 的 `64.13%`，再到加入 hotness-aware writeback 后的 `89.34%`。

## 创新性与影响

相对于 _McAllister et al. (OSDI '24)_，Nemo 指出：对 tiny objects 来说，log-to-set migration 这条基本抽象本身就不对。相对于传统 log-structured flash cache，它的创新则在于把接近 log-structured 的写行为，与近似索引结合起来，从而把内存成本压回紧凑 set-associative 设计的量级。

## 局限性

Nemo 用更复杂的读路径换来了更低的写放大。论文明确报告，它的 read amplification 超过 FairyWREN 的 `3x`，只是因为这些额外读取大多可以并行、且写请求干扰更少，最终读延迟仍然更低。这意味着该设计默认 SSD 内部具有足够并行性，也默认“多读一些 candidate set”仍比“频繁重写”便宜。

另外，hotness 与索引逻辑都是近似的：PBFG 的 false positive 会引入额外读取，group-level recency 也可能让冷对象在热 set 中“搭便车”。实验在一块 ZNS SSD 上很有说服力，但对不同设备和 workload mix 的参数稳健性，论文没有完全回答。作者还指出，把 Bloom filter 做得更准确也可能适得其反，因为更大的 filter 会让 on-flash index pool 更分散。

## 相关工作

- _McAllister et al. (SOSP '21)_ — Kangaroo 提出了面向 billions of tiny objects 的 hierarchical front-log/back-set cache，而 Nemo 认为正是这种迁移到大哈希空间 set 的过程，使写放大长期居高不下。
- _McAllister et al. (OSDI '24)_ — FairyWREN 通过把 garbage collection 与 log-to-set migration 合并来改进 Kangaroo，但 Nemo 说明这种改良后的层次结构仍然离理想 application-level write amplification 很远。
- _Berg et al. (OSDI '20)_ — CacheLib 提供了 Nemo 所依赖的生产级 set-associative substrate，而 Nemo 改变的是物理写入单位：从 per-set rewrite 改为 SG-level batched persistence。
## 我的笔记

<!-- empty; left for the human reader -->
