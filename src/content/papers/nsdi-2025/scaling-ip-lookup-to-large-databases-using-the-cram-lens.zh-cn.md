---
title: "Scaling IP Lookup to Large Databases using the CRAM Lens"
oneline: "CRAM 把 packet chip 抽象成联合使用 TCAM 与 SRAM 的流水线，并据此推导 RESAIL 与 BSIC，把 Tofino-2 上的 IP lookup 容量推到远超纯 TCAM 方案的范围。"
authors:
  - "Robert Chang"
  - "Pradeep Dogga"
  - "Andy Fingerhut"
  - "Victor Rios"
  - "George Varghese"
affiliations:
  - "University of California, Los Angeles"
  - "Cisco Systems"
conference: nsdi-2025
category: programmable-switches-and-smart-packet-processing
tags:
  - networking
  - hardware
  - smartnic
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

CRAM 不是单一的 lookup data structure，而是把现代 packet chip 视为联合使用 TCAM 与 SRAM 的查找底座。基于这个视角，作者推导出面向 IPv4 的 RESAIL 和面向 IPv6 的 BSIC，并把 Tofino-2 上可支持的路由表规模推到明显高于纯 TCAM 或传统单资源方案的水平。

## 问题背景

旧式 IP lookup 方案通常只围绕一种稀缺资源优化：要么是支持通配匹配的 TCAM，要么是适合指针结构的 SRAM/DRAM。作者认为，这个前提已经不适用于 Tofino、Pensando、BlueField 这一代 packet processor。它们同时提供 TCAM 与 SRAM，但又受限于每个 stage 的存储预算、每个 packet 可访问表的次数，以及 P4 pipeline 的实现约束。

这件事重新重要起来，是因为路由表仍在增长。论文预计 IPv4 到 2033 年可能逼近 200 万条前缀，IPv6 即使放缓后也可能达到 50 万条，而且路由器还要给 VPN、NAT、firewall 留空间。对 Tofino-2 来说，逻辑上的纯 TCAM 设计只能容纳约 25 万条 IPv4 前缀；纯 SRAM 方案也可能因为依赖片外 DRAM 或消耗过多 stage 而失效。

## 核心洞察

这篇论文最值得记住的想法，是把 IP lookup 放进联合的 CAM+RAM 成本模型里设计，而不是先想出算法，再在实现阶段硬塞进硬件。CRAM 在 RAM model 之上增加了两个一等概念：TCAM lookup，以及显式的依赖 DAG，用来描述哪些操作必须在 packet-processing stages 中串行执行。这样一来，算法就可以按 TCAM bits、SRAM bits 和最长依赖路径来比较。

一旦这些变成一阶成本，很多技巧就会系统化。少量但棘手的特殊情况可以挪到 look-aside TCAM；浪费严重的 direct-indexed array 可以改成哈希化 SRAM；稀疏逻辑表可以用 tag 合并；搜索结构可以切在下游状态最小的位置。论文的核心命题是：只要把少量 TCAM 放在正确的位置，就能消除单资源方案里最糟糕的空间爆炸。

## 设计

CRAM 程序由 parser、deparser 和一组 DAG 节点组成；每个节点做一次 exact 或 ternary lookup，再加上一组彼此独立的寄存器操作。这里最重要的 idioms 是：用 TCAM 压缩带 wildcard 的结构；当 expansion 仍比 ternary 存储便宜时用 SRAM；在能减少下游状态的位置切分搜索结构；以及当 packet 不能回访同一张表时，把状态按层 fan-out。

RESAIL 从 SAIL 的分解出发：先找匹配前缀长度，再取 next hop。对 24 位以内的 IPv4 前缀，它仍使用 bitmap；但对更长前缀，它不用 pivot pushing，而是把这些少数情况移到一个小型 look-aside TCAM。原先大量 next-hop arrays 被压缩成一张 d-left SRAM hash table，并通过 bit marking 把不同长度前缀统一成固定宽度 key。多个 bitmap lookup 可以借助 match-action 并行完成，而 `min_bmp` 用来权衡并行度与短前缀扩展开销。

BSIC 从 DXR 的区间搜索视角出发。它把原先 direct-indexed 的前置 SRAM 表改成按地址前 `k` 位匹配的 TCAM 表，因此初始切分可以设得更宽，这对 IPv6 特别有利。剩余搜索状态则被展开成 binary search trees，而不是一张会被反复访问的 range table，因为 RMT 硬件不允许 packet 无限制回访同一内存结构。这种 fan-out 会增加 SRAM，但换来了在 packet pipeline 规则下的可实现性。

第三个设计 MASHUP 是一个 hybrid trie：当 prefix expansion 低于论文使用的 3 倍阈值时，节点落成 SRAM，否则落成 TCAM，再用 tag 合并稀疏节点。作者把它主要看作 stage 更紧张时的备选。

## 实验评估

评估重点是资源是否放得下，以及规模能否继续扩展，而不是端到端转发吞吐。作者使用了 2023 年 9 月的 BGP 表快照、一个按 Tofino-2 内存几何参数构造的 ideal-RMT 模型，以及真实编译到 Tofino-2 的 P4 实现。

对 IPv4，RESAIL 的结果最强。在 ideal RMT 上，它可以扩展到约 380 万条前缀；在 Tofino-2 上，可以扩展到约 225 万条。论文把它与逻辑上的纯 TCAM 设计对比，后者只能容纳约 245,760 条 IPv4 前缀；而 SAIL 的 SRAM 和 stage 成本则使其不适合这类硬件。

对 IPv6，BSIC 在 ideal RMT 上可以做到约 63 万条前缀，在 Tofino-2 上可以做到约 39 万条；纯 SRAM baseline `HI-BST` 在 ideal model 上约为 34 万条。这里也暴露出最重要的现实约束：BSIC 在 Tofino-2 上需要 30 个 stages，因此作者是通过 recirculation 才把它塞进芯片，这会把可用端口数量减半。也就是说，实验确实支持论文关于容量扩展的主张，但这是一个带条件的部署结果。更一般地，实验说明 CRAM 能正确预测相对赢家，但它抽象里的 `steps` 会低估真实实现中的 stage 成本，因为 action bits、内存碎片和 ALU 深度限制都会放大开销。

## 创新性与影响

这篇论文更深的贡献是方法，而不只是三种派生出的 lookup structure。它把“可编程 packet chip 上同时存在的 TCAM 与 SRAM”组织成一个带有明确成本指标和命名优化招式的算法设计空间。这不仅对 routing 有意义，对 packet classification 或 in-network inference 这类同样依赖大规模查找状态的 P4 任务也有启发。

## 局限性

论文对“可推广性”的主张，目前更多还是论证性的。所有真正落地的部分都围绕 IP lookup 和类似 Tofino-2 的 RMT 硬件展开；SmartNIC、FPGA 和其他应用只是被简要讨论。评估也很少涉及稳定态转发性能，或高 churn 条件下的 update throughput。

最实际的限制来自 BSIC 在 Tofino-2 上的结果。它依赖 recirculation，而不是一次通过 pipeline 的干净映射。更广义地看，CRAM 是一个很有用的一阶设计模型，但论文自己也说明了：芯片特定细节仍然足以把 stage 成本放大到改变可部署性的程度。

## 相关工作

- _Yang et al. (SIGCOMM '14)_ - `SAIL` 通过 SRAM/DRAM 和 pivot pushing 解决 IPv4 lookup，而 `RESAIL` 在 TCAM+SRAM 硬件前提下重做同一问题，把长前缀角落情况移到 look-aside TCAM 中。
- _Zec et al. (CCR '12)_ - `DXR` 把 lookup 视为区间搜索，并依赖 direct-indexed front table；`BSIC` 保留这个视角，但把 front table 换成 TCAM，并把剩余搜索扇出成符合 packet pipeline 访问规则的 BSTs。
- _Shen et al. (GLOBECOM '18)_ - `HI-BST` 是纯 SRAM 的 IPv6 lookup 结构，并强调高效更新；`BSIC` 则用少量 TCAM 换取现代 packet chip 上更低的 SRAM 与 stage 压力。
- _Bosshart et al. (SIGCOMM '13)_ - `RMT` 给出了底层的 programmable-switch architecture，而 `CRAM` 则在其上增加了构建大规模 lookup structure 的算法抽象与成本模型。

## 我的笔记

<!-- 留空；由人工补充 -->
