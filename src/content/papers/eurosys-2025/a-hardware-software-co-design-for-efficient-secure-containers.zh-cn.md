---
title: "A Hardware-Software Co-Design for Efficient Secure Containers"
oneline: "CKI 用 PKS 和少量 ISA 扩展，在 host kernel 里为容器 guest kernel 造出新的特权层，避开 EPT、shadow paging 和 syscall redirection 的主要开销。"
authors:
  - "Jiacheng Shi"
  - "Yang Yu"
  - "Jinyu Gu"
  - "Yubin Xia"
affiliations:
  - "Institute of Parallel and Distributed Systems, SEIEE, Shanghai Jiao Tong University"
  - "Engineering Research Center for Domain-specific Operating Systems, Ministry of Education, China"
conference: eurosys-2025
category: security-and-isolation
doi_url: "https://doi.org/10.1145/3689031.3717473"
tags:
  - virtualization
  - isolation
  - kernel
  - security
  - hardware
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CKI 的出发点很明确：secure container 真正缺的不是另一层完整虚拟机，而是给 container guest kernel 一个介于应用和 host kernel 之间的新特权层。论文用 PKS 加上几处很小的硬件扩展，把这个层级直接塞进 ring 0 里，于是 syscall 不必重定向，page fault 也不必再走 EPT 或 shadow paging。实验里，CKI 把 page fault 压到 1.067 us，在嵌套云里把内存密集型负载的延迟最多降 72%，memcached 吞吐最多做到 HVM 的 6.8 倍。

## 问题背景

OS-level container 的轻量来自共享一个 kernel，但这也是它最脆弱的地方。论文统计了 2022-2023 年间 209 个可被容器利用的 Linux kernel CVE，发现绝大多数最后都会落成 DoS。VM-level container 通过给每个容器配一个 guest kernel 把这个问题切开了，可代价也很直接：系统实际上需要三层权限，分别给容器应用、容器 kernel 和 host kernel；而通用 CPU 对软件自然暴露的却只有用户态和内核态两层。

现有 secure container 设计都在补这第三层，但补法都很贵。像 Kata Containers 这类 HVM 路线把 guest kernel 放进虚拟化硬件提供的隔离层里，安全边界清楚，却连带吃下两阶段地址翻译和 nested VM exit 的开销。论文引用的结果显示，两维页表遍历会让 memory-intensive 应用平均多出 46% 延迟，而它自己的评测表明，在 nested cloud 里 page-fault-heavy 负载会慢 28%-226%。PVM 这类软件虚拟化路线绕开了 L0 参与的 VM exit，却把 syscall redirection 和 shadow paging 的成本重新压回 host kernel 上。

## 核心洞察

这篇论文最重要的判断是：secure container 不需要一般 VM 那套完整语义，它只需要把 container guest kernel 限权，而不是把它假扮成一台独立机器。换句话说，容器隔离更像 intra-kernel isolation，而不是 hypervisor emulation。只要 guest kernel 还能以 kernel 的身份直接服务本容器里的进程，同时又拿不到 KSM 和 host kernel 的关键能力，系统就可以同时保留 VM-level container 的隔离性与原生 syscall 路径。

由此 CKI 把两个传统负担一起拿掉。第一，它用 PKS 把 guest kernel 关进 ring 0 内部一个受限区域，而不是把它打到 user mode 或 non-root ring 0。第二，它直接放弃两阶段地址翻译，因为容器不需要一般虚拟机那种伪造出来的物理地址空间；guest kernel 只要能安全地管理分到的 hPA 段即可。

## 设计

CKI 给每个 secure container 分配独立地址空间，里面同时放 guest user、guest kernel 和一个 kernel security monitor。guest kernel 与 KSM 共享 ring 0，但通过 PKRS 权限分离：KSM 在 PKRS 为 0 时能看见全部内存，guest kernel 在 `PKRS_GUEST` 下看不见 KSM 的页。由于容器之间本来就分属不同地址空间，单个容器里只需两个 PKS domain，因此不会被 PKS 只有 16 个 key 的上限卡住。

难点在于 PKS 只管内存，不管 privileged instruction。CKI 因此补了一层很小的 ISA 扩展：当 PKRS 非零时，凡是可能破坏隔离的 privileged instruction 都会 trap 到 host。像 `wrmsr`、`iret`、写 CR3、关中断这样的操作不能由 guest kernel 直接执行，只能通过 KSM 或 host kernel 的门来做；而 `swapgs`、`sysret`、`invlpg` 这类热路径上的关键指令则继续放行。论文还引入了专门的 `wrpkrs` 指令，并对 guest kernel 做 binary rewriting，只保留预定义入口处的 PKRS 切换。

切换路径按频率分层。syscall 和用户态 exception 走最快路径，因为 guest kernel 就映射在 guest user 的地址空间里；只碰当前容器私有数据的危险操作，例如 PTE 更新和 `iret`，通过轻量 KSM gate 完成；涉及 VirtIO、timer 等全局状态的操作，则走 host hypercall gate。为了不信任可被 guest 篡改的 `kernel_gs`，CKI 为每个 vCPU 维护一个顶层页表副本，并把 KSM 的 per-vCPU 区映射到固定虚拟地址。

内存隔离靠的是对页表更新的持续审计。CKI 延续了 Nested Kernel 那类不变量思路：只有声明过的页能当 page-table page，声明过的 PTP 对 guest 是只读的，只有声明过的顶层 PTP 才能装进 CR3。与 shadow paging 不同，CKI 直接把连续的 hPA 段交给 guest kernel 管理，guest 在填 PTE 时写入的是 hPA，KSM 只负责验证这些更新是否合法。中断部分也单独加固：IDT、interrupt gate 和 IST stack 都放在 KSM 内存里，真正的 hardware interrupt 进入时硬件会自动把 PKRS 清零，从而堵住伪造中断的入口。

## 实验评估

原型把 Linux 6.7.0-rc6 作为 guest kernel，新增约 2K LoC，改动不到 80 行。实验平台是一台 2.4 GHz AMD EPYC-9654、125 GB 内存的服务器；嵌套云场景下，secure container 跑在 16 vCPU、16 GB 内存的 L1 VM 里。对比对象是 RunC、基于 HVM 的 Kata Containers，以及 PVM。

微基准非常贴合设计目标。CKI 的 page fault 延迟是 1,067 ns，PVM 是 4,407 ns，bare-metal HVM 是 3,257 ns，nested HVM 则高到 32,565 ns；其中 CKI 额外付出的 KSM 成本只有 77 ns，用在 PTE 更新与 `iret` 上。简单 `getpid` syscall 在 CKI 里依旧约 90 ns，和 RunC、HVM 基本一样；PVM 因为多了 page table switch 和 mode switch，变成 336 ns。到了 nested cloud，空 hypercall 在 CKI 上是 390 ns，PVM 是 486 ns，而 HVM 需要 6,746 ns。

这些差异会直接反映到真实应用。对 PARSEC 和 vmitosis 里的内存密集型负载，CKI 相比 nested HVM 降低 24%-72% 延迟，相比 bare-metal HVM 降低 1%-18%，相比 PVM 降低 2%-47%，同时相对 RunC 的额外开销低于 3%。在 GUPS 和 BTree lookup 这类 TLB-miss-heavy 场景里，CKI 也分别比 bare-metal HVM 快 19% 和 6%。I/O 密集型方面，SQLite 放在 tmpfs 上时，CKI 相对 PVM 最多提升 24% 吞吐；而在 nested cloud 的 memcached 与 Redis 上，CKI 最多能做到 HVM 的 6.8x 和 2.0x，也分别比 PVM 提升到 1.5x 和 1.3x 左右。

## 创新性与影响

CKI 的创新不只是把 PKS 搬到 secure container 上，而是重新定义了 guest kernel 该处在什么位置。它既不是一台完整 VM 的内核，也不是被打入 user mode 的受害者，而是 ring 0 里一个能力被精确削掉的 kernel。围绕这个定位，论文把 PKS、页表监控、KSM gate 和防中断伪造机制拼成了一套完整设计。

## 局限性

最现实的限制是硬件前提。CKI 依赖的 `wrpkrs`、中断入栈时自动切 PKRS、`iret` 恢复 PKRS 等机制，在现有商用 CPU 上都不存在；论文只能用 `wrpkru` 模拟一部分路径，再用 Gem5 估算新增检查逻辑几乎没有额外开销。因此，实验很有说服力，但还不是在目标硬件上的直接实测。

另外，CKI 用连续物理段换运行时效率，也就接受了碎片化带来的内存利用率损失。guest kernel 侧也不是零修改：需要 para-virtualization hook、新的启动流程，以及对动态 kernel code 更严格的限制。最后，CKI 继承的仍是 VM-level container 威胁模型，host kernel 与 KSM 必须可信；单个 secure container 内部的 transient execution attack 也不在论文处理范围内。

## 相关工作

- _Huang et al. (SOSP '23)_ - PVM 通过 shadow paging 和 syscall redirection 在 nested cloud 里绕开硬件虚拟化，而 CKI 进一步把这两笔开销一起拿掉。
- _Van't Hof and Nieh (OSDI '22)_ - BlackBox 走的是 shared-kernel 加 security monitor 的路线，重点是防不可信宿主机读写容器；CKI 则坚持每个容器各有 kernel，用 kernel separation 来抵御 DoS。
- _Dautenhahn et al. (ASPLOS '15)_ - Nested Kernel 通过页表不变量监控被限权的 kernel，CKI 明显继承了这类思路，但把对象换成 per-container guest kernel，并补上了快速 gate 与中断保护。
- _Gu et al. (USENIX ATC '20)_ - UnderBridge 用虚拟化硬件做 intra-kernel isolation，CKI 则刻意避免依赖这类硬件路径，以便在 nested cloud 里仍能部署。

## 我的笔记

<!-- 留空；由人工补充 -->
