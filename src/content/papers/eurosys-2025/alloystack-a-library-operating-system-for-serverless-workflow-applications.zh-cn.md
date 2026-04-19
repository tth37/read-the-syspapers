---
title: "AlloyStack: A Library Operating System for Serverless Workflow Applications"
oneline: "AlloyStack把整个 serverless workflow 放进同一个 MPK 分区的 LibOS 中，按需加载模块并直接传引用，从而同时压低冷启动和中间数据搬运成本。"
authors:
  - "Jianing You"
  - "Kang Chen"
  - "Laiping Zhao"
  - "Yiming Li"
  - "Yichi Chen"
  - "Yuxuan Du"
  - "Yanjie Wang"
  - "Luhang Wen"
  - "Keyang Hu"
  - "Keqiu Li"
affiliations:
  - "College of Intelligence & Computing, Tianjin University, Tianjin Key Lab. of Advanced Networking, China"
  - "Tsinghua University, China"
conference: eurosys-2025
category: os-kernel-and-runtimes
doi_url: "https://doi.org/10.1145/3689031.3717490"
code_url: "https://github.com/tanksys/AlloyStack"
tags:
  - serverless
  - kernel
  - isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AlloyStack 把一条 serverless workflow 当作基本执行单元：多个 function 共享同一个 workflow domain、同一个地址空间和同一个 LibOS，再用 MPK 隔开用户代码与系统层，并用按需加载和零拷贝缓冲区把平台开销压下去。论文报告冷启动只有 1.3 ms；在中间数据密集的 workflow 上，Rust 端到端延迟提升 7.3x-38.7x，C/Python 提升 4.8x-78.3x。

## 问题背景

论文关注的是由许多短小 function 组成的 serverless workflow。作者引用的已有测量显示，31% 的 serverless application 采用 workflow 形态，而 Azure Durable Functions 调用量最高的 5 条 workflow 就占了总调用的 46%。在这种工作负载里，平台开销比用户代码更容易主导端到端延迟。

最主要的两项成本是反复冷启动和中间数据搬运。作者在 OpenFaaS 上运行 `ParallelSorting`、输入 50 MB 时测得，冷启动占端到端延迟的 45%，中间数据传递再占 48%。现有方案往往只解决一侧：warm start 和 snapshot 能隐藏启动，但要付出预测难度与内存常驻；specialization 依旧保留了过多 guest OS；线程级 runtime 去掉了拷贝，却削弱了隔离，还常把 host kernel 更直接地暴露出来。论文要找的是同时压低启动和通信成本、又不放弃 workflow 间强隔离的执行底座。

## 核心洞察

论文的核心判断是，多数场景下真正自然的隔离边界不是单个 function，而是整条 workflow。商业平台一般只让同一租户把自己的 function 组合成 DAG，所以跨 workflow 必须强隔离，workflow 内部则往往可以接受更弱、甚至按需加强的隔离。

一旦边界这样划定，两件事就能同时成立：整条 workflow 可以共享一个 LibOS，不再为每个 function 重复冷启动；中间对象也可以直接按引用传递，不必经过存储系统或 socket。AlloyStack 把这个抽象命名为 WFD：一个地址空间、一个 LibOS、若干共享缓冲区，以及可选的 MPK 加固。关键不在于单纯把 function 改成线程，而在于它们是在 LibOS 边界内共享，因此用户代码仍不能直接调用 host kernel。

## 设计

WFD 是 AlloyStack 的核心抽象。一个 WFD 用一个进程承载整条 workflow 所需的用户 function、堆、LibOS 模块和运行时元数据，地址空间再被 Intel MPK 划成 user partition 与 system partition。`as-visor` 负责创建和销毁 WFD、管理线程与内存区域，并在需要时为特定 function 额外分配 MPK 分区。

开发者面对的是 `as-std`，也就是对 Rust `std` 的替代层。它拦截原本会变成 syscall 的操作，并通过 trampoline 切换 PKRU 权限后进入 `as-libos`。`as-libos` 本身被拆成多个 Rust 模块，例如 `mm`、`fdtab`、`fatfs`、`socket`、`stdio` 和 `time`。

冷启动之所以低，是因为模块按需加载。新建 WFD 时不预先实例化任何 `as-libos` 模块，只有在第一次 `open()` 等调用发生时，`as-visor` 才把所需模块装进来并缓存入口。数据传递则依赖 `AsBuffer`：发送方按 slot 名称分配缓冲区并写入，接收方用相同 slot 取回内存引用；slot 机制因此既能支持链式传递，也能支持 DAG 的 fan-out 和 fan-in。C 和 Python 支持通过 AOT 编译的 WASM、Wasmtime 以及 WASI 适配层实现。

## 实验评估

评测同时用了 microbenchmark 和三类真实 workflow：`WordCount`、`ParallelSorting`、`FunctionChain`。对手则覆盖 Unikraft、gVisor、Wasmer、Virtines、OpenFaaS、Faastlane 和 Faasm。

最清楚的结果来自冷启动。AlloyStack 在保留 LibOS 边界的前提下做到 1.3 ms；如果关闭按需加载，同一系统会退化到 89.4 ms。传输 16 MB 中间数据时，Rust/C/Python 分别需要 951 us、697 us、9631 us，对应论文给出的 2.6x、13.2x、1.8x 改进。即便开启更严格的 function 间隔离，传输延迟也只增加 0.8%-33.7%。

端到端结果大体支持作者的机制解释。收益最大的场景是重复启动和中间数据搬运占主导的时候，因此 headline 才会达到 Rust 7.3x-38.7x、C/Python 4.8x-78.3x。可论文也清楚交代了失利场景。`rust-fatfs` 的读性能比 ext4 慢 4.4x，所以文件较重的 `WordCount` 会吃掉不少优势；C 版 `ParallelSorting` 也可能输给 Faasm，因为 AlloyStack 使用的 Wasmtime 比 WAVM 慢。也就是说，这套设计的收益是真实的，但主要集中在 intermediate-data-intensive workflow 上。

## 创新性与影响

AlloyStack 的新意在于把两条常被分开讨论的路线合到一起：一条是用 LibOS specialization 缩短启动路径，另一条是用 workflow 内共享地址空间压低数据传递成本。论文把它们统一成 workflow 级操作系统抽象，因此贡献不只是更快的 benchmark，而是重新定义了 serverless DAG 的合适部署粒度。

它最能打动的对象，是单租户、阶段间要交换大量中间数据的 workflow runtime 与 workflow engine。对这类系统来说，这篇论文非常有力地说明了每个 function 一个重沙箱往往是错误粒度。

## 局限性

最大的限制来自信任模型。AlloyStack 默认假设同一条 workflow 中的 function 大多属于同一租户，因此可以共享地址空间。系统虽然能用 MPK 加强 function 间隔离，但这会削弱它本来想获得的效率与简洁性。与此同时，平台还必须在部署前拒绝或重写包含 `wrpkru`、`syscall`、`sysenter` 等指令的二进制。

它在工程能力上也有明显边界。AlloyStack 不会自动把超大 workflow 切到多机；有状态 function 的恢复主要依赖外部系统；更现实的是，`rust-fatfs`、`smoltcp` 和 Wasmtime 在论文里都成了失分项。换句话说，AlloyStack 最适合作为单机、中间数据密集型 workflow 的设计答案，而不是通用 serverless substrate 的最终形态。

## 相关工作

- _Kotni et al. (USENIX ATC '21)_ - Faastlane 同样利用进程内共享和 MPK 来加速 workflow，但 AlloyStack 额外引入了 workflow 级 LibOS 与按需模块加载，因此在避免数据拷贝的同时保留了更强的 kernel 边界。
- _Mahgoub et al. (OSDI '22)_ - ORION 通过 sizing、bundling 和 prewarming 来降低 serverless DAG 的延迟；AlloyStack 则直接改写每个 workflow 实例的执行底座，让启动和传递本身更便宜。
- _Mahgoub et al. (USENIX ATC '21)_ - SONIC 会在链式 serverless application 中为每条边挑选更合适的存储式数据传递路径，而 AlloyStack 直接消除了这一步，把通信双方留在同一地址空间内。
- _Kuenzer et al. (EuroSys '21)_ - Unikraft 证明了 specialized LibOS 可以显著缩短启动路径，但它并不面向 workflow 内多 function 的模块复用，也不提供同域内的零拷贝 function-to-function 传递。

## 我的笔记

<!-- 留空；由人工补充 -->
