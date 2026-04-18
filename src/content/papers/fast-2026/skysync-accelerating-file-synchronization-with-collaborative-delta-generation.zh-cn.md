---
title: "SkySync: Accelerating File Synchronization with Collaborative Delta Generation"
oneline: "SkySync 复用存储层已有校验和并用代数方式组合，让 rsync/dsync 式同步在不增加网络流量的前提下显著减少 delta 生成 CPU 开销。"
authors:
  - "Zhihao Zhang"
  - "Huiba Li"
  - "Lu Tang"
  - "Guangtao Xue"
  - "Jiwu Shu"
  - "Yiming Zhang"
affiliations:
  - "NICE Lab, XMU"
  - "SJTU"
  - "Alibaba Cloud"
  - "Tsinghua University"
conference: fast-2026
category: cloud-and-distributed-storage
code_url: "https://github.com/skysync-project/skysync"
tags:
  - storage
  - filesystems
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`SkySync` 通过复用存储栈为了完整性校验、去重和管理而早已计算好的校验和，来加速 `rsync` 式和 `dsync` 式文件同步。它的关键技术是代数式 checksum combination 与更扁平的哈希搜索结构，因此能把 delta 生成阶段的 CPU 开销压低到足以把端到端同步性能提升到约 `1.1x-2x`，同时基本不改变网络流量。

## 问题背景

随着跨区域、跨云提供商的数据处理越来越常见，整文件传输在 WAN 上显然是浪费的，delta sync 因而成为自然选择。问题在于，现有 delta sync 的主要成本并不总是在“传输了多少字节”，而是在“如何找出哪些字节变了”。在 `rsync` 中，服务器先把旧文件切成固定大小块并计算 `Adler32` 和 `MD5`，随后客户端对新文件逐字节滑动 KB 级窗口，不断重算弱校验和并探测哈希表，直到找到匹配块。在 `dsync` 中，CDC 虽然减少了一部分冗余工作，但两端仍需对文件字节大规模计算弱校验和，再进行额外匹配。

论文在接近 inter-cloud 场景的虚拟机上直接量化了这一点：客户端与服务器端的计算时间占总同步时间的 `71.2%-93.7%`，而 checksum calculation 加上 chunk searching 最多占到 `95%`。即便加入 AVX-512 与 SHA 指令集加速，哈希计算量仍然太大、访问模式仍然太不规则，所以整体收益有限。真正的系统问题于是变成：既然存储层本来就为了完整性、去重和校验维护了大量 metadata，文件同步为什么还要把这些信息重新算一遍？

## 核心洞察

论文的核心命题是，delta sync 不应把 storage metadata 视作独立于同步算法之外的背景设施，而应把它直接纳入 delta generation。现代 block device、file system、deduplication system 和 distributed storage service 已经维护了按块或按 chunk 的校验和与摘要。如果同步协议能够先协商 chunk size 与 checksum type，这些既有 checksum 往往就可以被直接复用，或者通过代数组合，生成 delta generation 所需的弱校验和与强校验和。

这样一来，成本结构就变了。系统不再需要对所有字节重新做一轮 checksum 计算，再在指针密集的哈希结构中反复查找；SkySync 更多是在读取已有 metadata，只对边界不对齐的少量片段重新计算 checksum，并在更扁平的 bucket 结构里完成搜索。它没有改变 sync 的语义，而是用更便宜的方法实现了同一种语义。

## 设计

`SkySync` 有两个变体。`SkySync-F` 面向 FSC-based sync，对应接入 `rsync` 工作流；`SkySync-C` 面向 CDC-based sync，对应接入 `dsync`。整体架构相当克制：客户端和服务器仍然交换 checksum list、matching tokens 与 literal bytes，但 checksum calculation 和 chunk searching 模块开始与存储层协同工作。

对于 FSC，最简单的情况就是直接复用：如果存储层已经暴露了固定大小 chunk 的 checksum，SkySync 就可以直接把它当作服务器返回的 checksum list。对于 CDC，论文最关键的技术点是 checksum combining。假设存储层暴露的是 `4 KB` 粒度的 `CRC32C`，而 CDC 产生的是变长 chunk，那么 SkySync 就通过 XOR 与 append-zeros 操作，把多个固定块的 checksum 组合成一个变长 chunk 的 checksum，只对那些因边界错位而无法直接复用的边界字节重新计算 CRC。论文指出，这类差异字节通常不到平均 chunk 大小的一半，因此弱校验和生成里最昂贵的部分被显著削掉。论文还强调，这个思路并不局限于 `CRC32C`，凡是具有类似代数结构的多项式校验和都可套用。

第二个设计点是 chunk searching。不同于 `rsync` 从 `16-bit` hash index 走到 `32-bit` 弱校验和、再走到强校验和的多级查找，SkySync 使用一个预分配 bucket 的扁平数组，并采用简化版 Cuckoo hashing。它直接从 chunk 已有的 `CRC32C` 推导出两个候选 bucket，按不同同步模式存储仅弱校验和或“弱加上强”的条目，并把每个 bucket 的容量固定为四个 entry。这样能减少 pointer chasing，降低碰撞处理成本，让搜索路径更适合 CPU。

由于客户端和服务器可能运行在不同存储栈之上，SkySync 还加入了 protocol negotiation。FSC 模式下，客户端对齐服务器的 chunk size，因为 checksum list 由服务器先发；CDC 模式下，服务器对齐客户端的 chunking policy。对于 checksum type，只要任一端提供 `CRC32C`，SkySync 就优先把它当作弱校验和；强校验和则优先采用服务器已有的 cryptographic hash，以减少额外重算。论文最终用 HTTP(S) 消息把这些机制串起来，在 `librsync` 之上用约 `1100` 行 C++ 实现 `SkySync-F`，并在作者重写的 `dsync` 原型之上再增加约 `1600` 行实现 `SkySync-C`。

## 实验评估

这篇论文的实验总体上是扎实且相对公平的。作者在两个位于不同数据中心的 Alibaba Cloud 虚拟机上，把 SkySync 与 `rsync`、`dsync` 做对比，所有系统采用同一套 multithreading policy，同时也给出了纯软件版与 hardware-accelerated 版结果。这与论文的中心论点吻合：在 inter-cloud sync 场景里，瓶颈往往先是 computation，而不是 bandwidth。

在 micro-benchmark 中，客户端结果很清晰。`SkySync-F` 比 `rsync` 快 `1.2x-2.0x`，把客户端计算开销降低 `32.1%-64.9%`；`SkySync-C` 比 `dsync` 快 `1.3x-1.7x`，降低 `25.7%-42.3%`。在服务器端，SkySync 更多是在读取 metadata，而不是从头重算并查找，因此论文报告相对 baseline 最多可降低 `89.3%` 的 computational overhead。分解图也支持其因果解释：相对 `rsync`，`SkySync-F` 把 checksum calculation 时间减少 `23.4%-88.3%`，把 chunk searching 时间最多减少 `61.3%`；相对 `dsync`，`SkySync-C` 把 checksum 时间减少 `24.5%-33.6%`，把 chunk searching 时间减少 `65.7%`。

真正重要的是实数据集。面对聊天记录、Ubuntu 镜像、快照、Wikipedia dump 和 Linux kernel tree，SkySync 带来了约 `1.2x-1.5x` 的同步加速，并把客户端与服务器端合计 sync time 降低 `19.2%-43.7%`。同时，网络侧结果并没有抵消这些收益：它的 sync traffic 与 `rsync`、`dsync` 基本相当，只是因为携带更多 strong-checksum bits 而略有增加。Metadata extraction 本身也足够便宜，在 `BTRFS` 上仅为 `1.8-119.2` 秒，占 SkySync 总时间的 `0.11%-7.14%`。这说明论文的核心收益确实来自更便宜的 delta generation，而不是某种隐含的流量交换。实验的主要短板不在一致性，而在覆盖范围：大部分实验建立在 `BTRFS` 云虚拟机场景上，因此“可推广到各种存储系统”更多是被论证，而不是被完全验证。

## 创新性与影响

这篇论文的新意不在于提出一种全新的 delta-sync 语义，也不在于重新设计 chunking 规则，而在于把 delta generation 跨越存储层边界重新理解，主动利用那些本来为其他目的存在的 metadata。相对于 `dsync`、`WebR2sync+`、`PandaSync` 这一类工作，SkySync 真正攻击的是 checksum generation 与 searching 这两个主导成本，而不是只把工作从客户端移到服务器，或者只决定何时该做 delta sync。

这使它成为一个很有价值的 systems 贡献，因为它优化的并不只是 file sync 本身。任何已经为完整性校验或去重计算摘要的存储栈，都可能几乎“白拿”一部分同步加速；而论文也展示了如何在 chunk size 与 checksum type 异构的条件下，把这种收益接进现有协议。若这种思路进入生产级同步工具，最可能带来的影响不是进一步减少 WAN 字节数，而是降低云节点上的 CPU contention。

## 局限性

SkySync 的前提是存储层必须能暴露出可用的 metadata。若 checksum 不可得、粒度不匹配，或者提取成本过高，系统就会退回更接近传统 sync 的行为。论文通过三类 extraction path 间接承认了这一点：user-space tools 方案需要每种文件系统单独配置，API 方案可能承担远端 metadata 访问延迟，而 custom parser 则会带来长期维护负担。

此外，它并没有消除所有 sync bottleneck。Chunking 过程仍然存在，网络流量也只是基本不变而不是下降，收益最大的前提依然是 computation 主导而非 bandwidth 主导。论文在 `100-500 Mbps` WAN 上证明了这一点，但没有展示在更慢链路上这些优势还是否显著，也没有充分覆盖那些 metadata interface 远弱于 `BTRFS` 或 `MeGA` 的系统。最后，`SkySync-C` 的实现建立在作者自己的 `dsync` 重写版本之上，因此它与其他生产级 CDC sync 工具的互操作性，目前更像是一个合理推断，而不是部署层面的实证。

## 相关工作

- _Muthitacharoen et al. (SOSP '01)_ - `LBFS` 奠定了基于 chunk 的低带宽同步思路，而 SkySync 更关注在现代云环境里降低这些 delta 的生成 CPU 成本。
- _He et al. (MSST '20)_ - `dsync` 简化了 CDC-based matching，但 SkySync 更进一步，复用存储层 metadata，从而避免对所有字节重新计算弱校验和。
- _Xiao et al. (FAST '18)_ - `WebR2sync+` 把 chunk search 推到服务器侧并利用局部性，而 SkySync 的重点是先减少那些必须被计算和搜索的新 checksum 数量。
- _Wu et al. (ICDCS '19)_ - `PandaSync` 解决的是何时选择 full sync 与 delta sync，而 SkySync 假定 delta sync 本身就是正确抽象，并直接压低它的热路径成本。

## 我的笔记

<!-- 留空；由人工补充 -->
