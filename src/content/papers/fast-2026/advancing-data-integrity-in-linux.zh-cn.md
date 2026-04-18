---
title: "Advancing Data Integrity in Linux"
oneline: "论文补齐 Linux 的 PI 支持：既增加灵活 PI 布局和 io_uring 元数据接口，又让 BTRFS 用设备 PI 取代 checksum tree，并为 XFS 引入数据校验。"
authors:
  - "Anuj Gupta"
  - "Christoph Hellwig"
  - "Kanchan Joshi"
  - "Vikash Kumar"
  - "Javier González"
  - "Roshan R Nair"
  - "Jinyoung CHOI"
affiliations:
  - "Samsung Semiconductor"
  - "EPFL"
conference: fast-2026
category: reliability-and-integrity
tags:
  - storage
  - filesystems
  - kernel
reading_status: read
star: true
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Linux 早就同时拥有支持 PI 的存储设备和 block layer 的 integrity 框架，但缺少一条完整的端到端路径。论文补上了灵活 PI 布局、可携带保护元数据的 `io_uring` 接口，以及 `FS-PI` 这一文件系统主导的设计，使 `BTRFS` 可以去掉 checksum tree，也让 `XFS` 以较小代价获得数据校验能力。

## 问题背景

论文的出发点很直接：设备侧 ECC 只能保护介质，不能覆盖数据穿过主机软件栈的整条路径。数据在内存里、在各层之间传递时，或者在 block request 真正到达设备前的软件转换过程中，仍可能发生损坏。所谓 end-to-end data protection，就是要让每个 block 的保护信息和数据一起流动，让 checksum、reference tag、application tag 能在整条 I/O 路径上被共同检查。

Linux 虽然早就有相关基础设施，但留下了三个关键缺口。第一，block-integrity 假定 PI 总在 metadata tuple 的开头，因此无法支持一些把 PI 放在其他偏移、甚至 metadata 尾部的 NVMe 设备格式。第二，Linux 没有常规 read/write 接口能同时传数据和保护元数据，导致数据库、分布式文件系统或厂商库若想用 PI，只能走私有路径。第三，完整性策略停在 block layer，而不是停在真正掌握数据语义的文件系统层。结果就是 `BTRFS` 长期承担 checksum tree 的额外开销，而 `XFS` 迟迟没有数据 checksumming。

## 核心洞察

论文最重要的判断是：只有当 PI 由“已经在决定数据布局与可见性”的那一层来控制时，它才真正有价值，也就是文件系统层。只要 Linux 能把保护元数据从应用一路带到设备，并让文件系统在映射、缓存、回写和对外可见的关键点上生成与校验这些元数据，PI 就不再只是 block device 的附属功能，而会变成真正的端到端完整性机制。

这也让 `Type 0` PI 变得很有意思。即便硬件自己不强制做 checksum 检查，保留下来的 per-block metadata 空间仍会随 block 一起流动，文件系统就可以把它拿来装自己的校验策略，例如 `CRC32c`，从而避免维护额外的 checksum tree。

## 设计

整套实现分成三层。第一层是 block layer 的修补。作者为 Linux block-integrity 增加了 `pi_offset`，让 driver 能明确告诉 block layer：PI 在每个 metadata tuple 里的具体位置。这样无论 PI 在开头还是结尾，校验逻辑都能覆盖正确字节范围；论文称这部分已经在 Linux `6.9` upstream。

第二层是新的 `io_uring` PI 接口。论文没有引入新 syscall，而是在现有 `io_uring` 读写请求上增加属性指针，指向 `io_uring_attr_pi`，其中携带 metadata buffer 地址、长度、application tag、校验标志和 reftag seed。block layer 也随之扩展，可以接收用户自己生成的 metadata、在物理扇区变化时 remap reftag，并在大 I/O 被拆成多个 bio 时正确切分 metadata。作者还补充了 capability-query `ioctl`。这个接口只支持 direct I/O，因为若支持 buffered I/O，就必须处理 page cache、按字节覆盖写以及 `mmap` 导致的 PI 失效。

第三层是 `FS-PI`。在 `BTRFS` 中，`dev_pi` mount option 让文件系统放弃 checksum tree，改为按 I/O 直接生成和校验 PI；在 `Type 0` 下，它把 PI 空间用来存 `CRC32c`。对 `XFS`，论文引入 `IOMAP_F_INTEGRITY`，让通用 `iomap` 层在 direct 和 buffered I/O 路径上统一分配 PI buffer 并调用共享 helper。另一个新标志 `REQ_NOINTEGRITY` 则允许那些已经有强 metadata 校验的元数据 I/O 跳过重复的 integrity 计算。

## 实验评估

实验平台是 Linux `6.15`、Ryzen `9 5900X`、`16 GB` 内存和一块 `1.88 TB` Samsung `PM9D3` SSD。对 `BTRFS` 而言，结果相当有说服力。direct random write 下，`FS-PI` 把 host writes 从 `813.66 GiB` 降到 `391.14 GiB`，把 NAND writes 从 `839.91 GiB` 降到 `403.76 GiB`，FS write amplification 从 `3.39` 降到 `1.62`。buffered random write 也有明显改进。Filebench 大多持平，但 `varmail` 从 `83K` 升到 `94K` ops/s，约 `13%`。在速率匹配的 direct random write 下，idle CPU 大约从 `12%` 提升到 `70%`。耐久性实验里，估算 `DWPD` 从 `27.33` 降到 `22.15`，对应 SSD 预期寿命提高约 `23%`。

`XFS` 的结论更克制。direct I/O 代价较小：random write 吞吐下降约 `4%`，sequential write 下降约 `1-2%`，读路径基本接近基线。buffered sequential write 是最明显的弱点，开销约 `20%`。不过 Filebench 几乎都和基线一致，所以更准确的结论不是 "`XFS` 变快了"，而是 "`XFS` 获得了数据校验能力，而且成本总体可接受"。

## 创新性与影响

这篇论文的创新点不只是“Linux 多支持了一种 PI 用法”。它把过去分离的三层真正连了起来：设备 PI 布局、用户态 I/O 接口，以及文件系统策略。相较 raw NVMe passthrough 或 `SPDK`，这里得到的是一个协议无关、能融入普通 Linux I/O 的路径；相较 `BTRFS` 式的 checksum tree，它把 integrity metadata 放回每个 block 自带的字段；相较历史上的 `XFS`，它提供了一条无需重做磁盘格式也能增加数据 checksumming 的现实路线。

## 局限性

这篇论文的局限也很明确。新的用户态 PI 接口只支持 direct I/O，而整套方案又依赖 PI-capable device 和相应格式，因此它不是适用于所有 Linux 存储设备的通用解法。`FS-PI` 保护的是 data block，而不是所有 metadata；在 `BTRFS` 中，冗余 profile 下的修复和副本恢复被留给未来工作，在本文评测使用的单副本模式里，PI mismatch 只会被上报成 I/O error。评测也只覆盖了一套硬件，而 `XFS` 的结果说明，buffered 写密集路径仍可能付出可见代价。

## 相关工作

- _Bairavasundaram et al. (FAST '08)_ — 展示了存储栈各层都会真实发生数据损坏；本文则把这种问题诊断落实为 Linux 里的端到端检测机制。
- _Joshi et al. (FAST '24)_ — 上游化了面向存储设备的灵活 `io_uring` passthrough，而本文进一步给普通 read/write I/O 增加了协议无关的 PI 交换能力。
- _Rodeh et al. (TOS '13)_ — `BTRFS` 依赖 out-of-place checksum metadata，并承担递归更新成本；`FS-PI` 则把完整性信息重新和 block 绑定，去掉了 checksum tree。

## 我的笔记

<!-- 留空；由人工补充 -->
