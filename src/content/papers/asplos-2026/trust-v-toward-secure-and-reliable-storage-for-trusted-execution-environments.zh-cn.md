---
title: "Trust-V: Toward Secure and Reliable Storage for Trusted Execution Environments"
oneline: "Trust-V 通过锁定存储控制器 MMIO 并在沙箱化 Virtual-M 中执行驱动片段，让 TEE 在无需新硬件的前提下获得具备完整性保护的持久存储。"
authors:
  - "Seungkyun Han"
  - "Jiyeon Yang"
  - "Jinsoo Jang"
affiliations:
  - "Chungnam National University, Daejeon, Requblic of Korea"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790242"
code_url: "https://github.com/Trust-V-opensource/Trust-V"
tags:
  - confidential-computing
  - storage
  - security
  - kernel
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Trust-V 的核心观点是：TEE 持久化数据的完整性问题，本质上可以通过控制存储控制器的 MMIO 访问路径来解决，而不必额外依赖专用安全存储硬件。它把 SD 卡划分为可信区和非可信区，禁止 Linux 直接访问控制器 MMIO，并仅将少量经过插桩的驱动代码放进一个沙箱化的 M-mode 执行环境 Virtual-M。作者在 RISC-V 原型上表明，这种做法既能保留 TEE 对私有分区的访问能力，也不会让普通块 I/O 的开销失控。

## 问题背景

论文首先指出，很多 TEE 已经解决了“写到磁盘前要加密”这个问题，但还没有真正解决“写到磁盘后不被操作系统破坏”这个问题。像 SGX、OP-TEE、Keystone 这样的系统都支持 sealing 或类似机制，因此 hostile OS 看不到明文；但它仍然可以删除密文文件、重格式化分区、重放旧数据，或者直接把密文块覆盖成垃圾。哈希校验只能在事后发现部分篡改，却无法阻止 OS 破坏 enclave 持久状态赖以生存的存储命名空间。

这会让任何需要长期状态的 enclave 变得很难落地。论文中的例子包括 enclave 持久页、一个 key-value store，以及由 security monitor 管理的 device root key。现有的硬件支持方案，例如 RPMB 一类的安全存储能力，并不是所有设备都有，尤其在面向 legacy 或成本敏感平台时更是如此。RISC-V 上的问题更明显：商品 SoC 里的 PMP 支持并不总是可用，H-extension 虚拟化能力也仍然不够普及。于是问题被收敛为：在只依赖普遍可得硬件特性的前提下，如何让 TEE 拿到一种即使 OS 被攻破也不会失去完整性的持久存储？

## 核心洞察

这篇论文最值得记住的命题是：持久存储完整性可以被收缩成一个狭窄的 I/O 仲裁问题。只要不可信 OS 既碰不到存储控制器的 MMIO 寄存器，也碰不到安全传输缓冲区，而且所有指向 TEE 私有分区的请求都必须经过知道“请求来自谁、分区归谁”的可信代码检查，那么 OS 就失去了悄悄篡改 enclave 磁盘状态的能力。

真正让这个想法可实现的，是作者没有把整套驱动栈搬进高特权固件。Trust-V 只把 Linux 驱动里少量必须直接操作 MMIO 的片段提升到更高特权执行。Virtual-M 用 `MPRV`、共享页表和临时打开的 `SUM` 组合出一个受限的 M-mode：这些代码能够访问受保护的 MMIO 和 trusted buffer，但仍然服从类似内核态的虚拟内存权限。换句话说，Trust-V 把高特权只花在“必须碰控制器的几条指令”上，而把策略判断留给由 security monitor 维护的元数据。

## 设计

Trusted Storage 把物理介质划分为普通 Linux 使用的 non-trusted 区域，以及为 security monitor 和各个 enclave 保留的多个 trusted partitions。Trust-V 明确提出四个要求：OS 不能访问控制器 MMIO 和安全 I/O buffer；TCB 要尽量小；每个 trusted partition 必须有唯一 owner；所有 I/O 请求都必须可验证且抗篡改。

第一层是内存隔离。Trust-V 把受保护区域，例如被锁定的 MMIO、secure I/O buffer 和 Virtual-M 的栈，标成 user page，并在正常情况下清除 `SUM`，从而让 S-mode Linux 无法访问。考虑到内核有时会合法地打开 `SUM`，而且 U-mode 也不应该看到这些区域，security monitor 还会在上下文切换或特定时机移除这些 trusted memory 的映射。为了防止 Linux 重新打开这些映射，Trust-V 进一步把 OS 去特权化：对 `SATP`、`SSTATUS`、`STVEC` 等寄存器的写入，以及页表更新，都会被替换成 `ECALL`，交由 security monitor 检查并模拟执行。共享页表本身也被设成只读，避免 OS 静默改写受保护区域的映射。

第二层是 M-mode 沙箱。Physical-M mode 是真正全能的 monitor 上下文，负责改元数据和页表；Virtual-M 则是 secure I/O 使用的受限上下文：代码虽然运行在 M-mode，但借助 `MPRV` 强制通过内核页表做访问控制，只在需要触碰 trusted memory 时临时打开 `SUM`。进入和退出由 `enterVirtualM()`、`exitVirtualM()` 严格控制。monitor 会利用 `MEPC`、覆盖 `RA` 并关闭中断，确保“进入、执行指定驱动片段、退出”这个序列具备原子性，不会被 loadable module 或 ROP 链劫持。

在此基础上，Trust-V 再建立一套围绕元数据的存储协议。monitor 维护被锁定设备的信息、secure-I/O context，以及从 trusted partition number 到 enclave hash 的映射表。分区 0 保留给 monitor，自 enclave 使用的分区从 1 开始并按需分配。一次 secure I/O 从 enclave 请求读取或写入自己分区开始；monitor 先写入元数据，把一个 4 KB 的 secure buffer 映射给 enclave，随后在两个阶段里校验请求：命令阶段检查目标 MMIO 和 sector 范围，数据阶段检查实际传输是否使用了受保护缓冲区，并在每次 block 交换后更新已传输计数。作者刻意让 Trusted Storage 只处理 raw block，而不引入文件系统，这样就不用把文件系统代码一并搬进 TEE。

## 实验评估

原型运行在 SiFive HiFive Unleashed 板卡上，硬件为 U540-C000 SoC、8 GiB DRAM，软件栈是 Linux `5.10.186` 与 Keystone `v1.0.0`，介质是 Samsung 64 GB Evo Plus microSD。整套实现总共 `5,053` 行代码，其中 Linux kernel 修改 `1,223` 行，而真正跑在 Virtual-M 里的驱动逻辑只有 `66` 行。这个数字很重要，因为论文很大一部分安全论证都建立在“被提升特权的代码足够小、易审计”这一点上。

系统级结果说明代价主要来自去特权化，而不是来自安全存储本身。CoreMark-Pro 几乎没有显著开销，但 LMBench 显示，凡是频繁因为页表或状态寄存器保护而陷入 monitor 的操作，都会明显变慢：某些内存分配、fork、exec 和 context switch 场景最高达到 `3.86x`；文件删除延迟最高增加 `45%`。作者将其归因于对敏感内核操作的多次 mode switch。相比之下，面向普通 ext4 非可信存储的块 I/O 开销要温和得多：Fio 的最大吞吐损失为 `6.6%`，IOzone 开销不超过 `0.2%`，mount 几乎没有差异。这说明论文的部署主张基本成立：额外仲裁是可见的，但没有把整条块设备栈拖垮。

应用级实验更有解释力。简单的 enclave block I/O 在 `512 B` 到 `4 KB` 范围内，读延迟约为 `0.14-0.55 s`，写延迟约为 `0.15-0.58 s`。若与“先 sealing，再把数据写到 non-trusted storage”的基线相比，Trust-V 在论文测到的 `4 KB` 场景里反而略快，写快约 `0.6%`，读快约 `0.3%`，原因是它省掉了加解密和文件系统额外开销。key-value store 的结果则更真实地暴露了代价：读路径几乎没有开销，但写密集型操作明显更慢，`key_put` 与 `key_delete` 在 32 次操作时有 `52%` 开销，在 64 次操作时最高达到 `2.05x`。最后，monitor 负责的 device root key provisioning 总耗时约 `0.83 s`，其中 `0.55 s` 用于读出 key material，`0.28 s` 用于派生并映射 enclave key。综合来看，这些结果足以支持“在 legacy RISC-V + SD 卡平台上可行”的主张，但对更快介质、更高并发或多设备环境的外推仍然有限。

## 创新性与影响

相对于 _Lee et al. (EuroSys '20)_ 所代表的 sealing 型 TEE 存储思路，以及 OP-TEE 这类厂商栈，Trust-V 的新意在于它保护的是“存储访问路径”本身，而不只是加密之后的字节。相对于 _Dhar et al. (NDSS '20)_ 这类借助更强硬件支持的 secure I/O 方案，它选择了设计空间的另一端：不增加新硬件，而是用更严格的软件 MMIO、页表与请求来源控制来兜住安全性。相对于 intra-mode privilege separation 的既有工作，论文最有意思的地方是把 RISC-V 的 `MPRV` 与共享页表组合起来，做出了一个面向驱动代码、而不是全权 monitor 的 M-mode sandbox。

因此，这篇论文对两类读者会比较有价值。做 TEE 架构的人可以把它当成“在特性贫瘠 SoC 上怎样实现具备完整性保护的持久化”的具体方案；做 RISC-V security monitor 或 secure peripheral 的系统研究者，则可以把它看成一个证据，说明在专用硬件尚未成熟前，围绕现有驱动做精细化 privilege structuring 也足以搭出可工作的 secure I/O 原型。

## 局限性

论文非常明确地限定了自己的威胁模型。它信任 secure boot、M-mode firmware，以及主机和外设硬件本身；它不处理物理攻击、side channel，也不处理阻止 enclave 被调起的 denial-of-service。这样的范围界定是合理的，但也意味着它给出的存储完整性保证只在这个信任边界内成立。

工程上也有几处明显限制。Trust-V 通过单一受监控上下文串行化 secure I/O，Trusted Storage 只处理 raw block，没有文件系统，而且 trusted partition 的数量和大小需要重新编译才能调整。写密集型应用的代价可能比较高，而整套评估又建立在 SD 卡而不是 NVMe 一类更快设备上，因此固定的 monitor 切换成本在其他介质上可能呈现不同占比。最后，原型为了模拟 legacy hardware 还主动关闭了 Keystone 的 PMP 使用，所以这篇论文更像是在证明“做得到”，而不是在展示“已经达到最佳实现”。

## 相关工作

- _Lee et al. (EuroSys '20)_ — Keystone 提供了开放的 RISC-V TEE 框架，而 Trust-V 在这个生态之上补上了具备完整性保护的持久存储能力。
- _Dhar et al. (NDSS '20)_ — ProtectIOn 借助更强的硬件根与 I/O 保护来应对受攻陷平台，而 Trust-V 则刻意只依赖通用 RISC-V 特性与软件仲裁。
- _Feng et al. (ASPLOS '24)_ — sIOPMP 通过硬件机制为 TEE 提供可扩展 I/O 保护，Trust-V 可以看作在缺少这类支持时的纯软件对照点。
- _Shinagawa et al. (VEE '09)_ — BitVisor 用薄 hypervisor 强化 I/O 设备安全，而 Trust-V 只把最小驱动片段下放到沙箱化 M-mode，并专门面向 TEE 私有存储场景。

## 我的笔记

<!-- empty; left for the human reader -->
