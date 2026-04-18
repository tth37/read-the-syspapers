---
title: "Building Bridges: Safe Interactions with Foreign Languages through Omniglot"
oneline: "Omniglot 用沙箱、typestate 包装和编译期 scopes 约束 Rust 与不可信外部库的交互，在保留零拷贝共享的同时维持宿主程序 soundness。"
authors:
  - "Leon Schuermann"
  - "Jack Toubes"
  - "Tyler Potyondy"
  - "Pat Pannuto"
  - "Mae Milano"
  - "Amit Levy"
affiliations:
  - "Princeton University"
  - "University of California, San Diego"
conference: osdi-2025
code_url: "https://github.com/omniglot-rs/omniglot"
tags:
  - security
  - isolation
  - pl-systems
category: kernel-os-and-isolation
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Omniglot 让 Rust 调用外部语言库时不必在安全性和效率之间二选一：外部代码被放进内存沙箱，而来自外部的指针和返回值则被建模成必须先 `upgrade`、再 `validate` 的 typestate。它最关键的设计是把验证、写入、回调和内存回收之间的时序约束编码成编译期 scopes，因此既能保住 Rust 的 soundness，又能把开销压到接近“只有隔离、没有额外检查”的水平。

## 问题背景

论文关注的是一个非常现实的迁移问题。越来越多的系统软件开始用 Rust 重写，因为 Rust 能从语言层面消灭大量内存错误；但真正的内核、服务和嵌入式系统又离不开多年打磨的 C 库或其他外部语言组件。现有做法通常是沿用 C ABI，再配合 `rust-bindgen` 之类的工具生成绑定。然而这条边界会把高层语言语义压平成原始指针和 `unsafe` block，编译器几乎帮不上忙，开发者必须自己证明外部库不会破坏 Rust 对内存布局、别名、有效值、生命周期以及并发的假设。

文中的 `aes_encrypt` 例子把这个风险讲得很具体。外部代码可能越界覆盖 `Vec` 的元数据，从而直接破坏内存安全；可能返回一个与现有可变借用别名的指针，违反 Rust 的 aliasing-XOR-mutability 规则；也可能返回一个既不是 `0` 也不是 `1` 的 `bool`，借由 Rust 的 niche-filling 优化让枚举值被解释成另一个 variant。仅靠“把库关进沙箱”并不能解决这些问题，因为即便外部库只能访问自己的页面，它仍然可以把在语义上对 Rust 无效的值交还给宿主。反过来，如果每次跨 FFI 都拷贝或序列化数据，安全性会容易很多，但这又抹掉了 FFI 在内核和高性能库场景中的意义。

## 核心洞察

Omniglot 的中心论点是：Rust 并不需要证明整个混合语言程序都正确，它只需要在边界上重新建立 Rust 自己在乎的那些不变量。于是 Omniglot 把所有来自外部代码的数据都先降格成更弱、带污染语义的表示，然后分阶段恢复其可用性。

这些阶段对应两类不同的事实。第一，Rust 需要知道某个指针确实指向仍然存活、大小和对齐都足够的外部内存。第二，Rust 需要知道那片字节内容满足目标 Rust 类型的有效值约束，并且在 Rust 使用期间不会被外部代码悄悄改掉。Omniglot 把这两类事实做成 typestate 转换，再把它们绑定到词法作用域 token 上。由于 Rust 的 borrow checker 本来就能区分共享访问和独占访问，同一套机制也就能顺带禁止那些会让旧验证失效的操作，比如外部写入、再次调用外部函数、回调导致的分配变化等。结果是它既保留了零拷贝共享，又把宿主语言的 soundness 守住了。

## 设计

Omniglot 的设计由三部分组成。第一部分是可插拔运行时 `OGRt`。它负责把外部库加载进沙箱、在外部内存区域内分配对象、准备回调入口，并保证外部函数只在受保护的域内运行。论文实现了两个 runtime：面向 Tock 内核、使用 RISC-V PMP 的 `OGPMP`，以及面向 Linux 用户态、使用 x86 MPK 的 `OGMPK`。其中 `OGPMP` 属于强 runtime，因为它能严格限制外部代码的内存访问并阻止不受控并发；`OGMPK` 则被作者明确归为弱 runtime，因为 MPK 可能被 `mmap`、signal 或后台线程等机制绕过，除非部署者再加额外控制。

第二部分是 Omniglot 的引用阶梯。最底层是原始指针，它可能指向任意地址，因此不带任何保证。`upgrade` 会在检查地址是否位于一个仍然有效的外部分配里、且尺寸与对齐满足 `T` 的要求后，把它变成 `OGMutRef<T>`。随后，`validate` 可以进一步把它变成 `OGVal<T>`，前提是底层字节模式满足 Rust 对 `T` 的有效值约束。Omniglot 为基础类型以及可通过布局检查验证的类型实现了这套校验，但对于 Rust 引用、typestate 这类依赖 provenance 或 lifetime 的类型，它无法事后验证，只能改用符号句柄之类的表示。为了让外部内存中的潜在可变别名不破坏 Rust 假设，`OGMutRef<T>` 在内部被表示成 `&UnsafeCell<MaybeUninit<T>>`，从而关闭 Rust 默认的别名和初始化推理。

第三部分也是论文最有意思的机制：用 branded allocation scopes 和 access scopes 去编码时间约束。`OGRt::new` 为某个库实例返回唯一的 `AllocScope` 与 `AccessScope` 标记。升级指针时会借用 allocation scope，因此引用不能活得比它依赖的分配状态更久。验证值时会借用 access scope，而任何可能让已验证值失效的操作，例如 `write` 或 `invoke`，都必须独占借用同一个 scope。换句话说，Omniglot 把“外部写入、回调或回收之后不能继续使用旧的已验证值”这种原本很微妙的时序规则，直接变成普通的 borrow-checking 错误。再加上修改后的 `rust-bindgen` 和一个 `invoke` trampoline，Omniglot 就能在不依赖 libffi 式动态封送的前提下，继续复用编译器对 C ABI 的参数布局知识。

## 实验评估

评估的组织方式主要想证明两件事：Omniglot 不是只适用于一种接口形态，而且它的额外成本很低。作者在两个环境中测试：一个是基于 OpenTitan 的 RISC-V FPGA 平台上的 Tock 内核，用来跑 `OGPMP`；另一个是 CloudLab Xeon 节点上的 Linux 用户态，用来跑 `OGMPK`。工作负载覆盖了三类 Tock 库 `CryptoLib`、`LittleFS`、`LwIP`，以及三类 Linux 库 `Brotli`、`libsodium`、`libpng`。这些例子横跨一次性调用、带状态库、回调、需要字符串验证的接口，以及字节数组这类可被编译器消掉验证开销的类型，覆盖面是够的。

最重要的结果是：相对于“只有内存隔离、没有 Omniglot 检查”的基线，Omniglot 自己再增加的开销非常小。Table 2 里，`CryptoLib`、`Brotli` 和 `libsodium` 相对 isolation-only 的额外开销都是 `0%`，`LittleFS` 是 `0.5%`，`libpng` 是 `0.8%`，回调最重的 `LwIP` 也只有 `3.4%`。和 unsafe FFI 相比，较大的慢下来主要来自保护域切换，而不是来自 `upgrade` / `validate` 本身。`libpng` 对 Sandcrust 的对比也很关键：Omniglot 因为能零拷贝访问外部内存，所以性能接近原生 FFI；Sandcrust 需要 IPC、序列化和复制，图像越大，额外成本越明显。微基准进一步支持这个机制解释：`validate` 对字符串是线性成本，但对 `u8` 这类无条件有效类型会被编译器直接优化掉；`invoke` 的热路径成本在 MPK 上是 `98.90 ns`，在 PMP 上是 `6.57 us`。需要保留的判断是，这套实验更有力地证明了效率和接口覆盖面，而不是真正恶意的用户态库在 `OGMPK` 下会怎样表现，因为论文自己就承认那不在其强威胁模型之内。

## 创新性与影响

和先前那些 Rust 沙箱或进程内隔离系统相比，Omniglot 的贡献不只是又造了一个更快的 protection-domain switch。它真正的新意在于把沙箱、运行时值验证和编译期 temporal scopes 组合成一套统一的 FFI discipline，使得 Rust 在调用未经修改的外部库时依然能够保持 soundness。和 linking types 那类工作相比，它也明显更偏工程实践：不是去完整表达外部语言语义，而是在运行时检查并约束 Rust 可以安全信任的部分。

这让它会同时吸引几类读者。对正在逐步把内核或服务改写成 Rust 的工程团队来说，它给出了一种不必退回“整个边界全靠 `unsafe`”的迁移路径。对研究 cross-language attacks 的安全方向来说，它提供了一个把不可信 FFI 包装成可防御接口的具体机制。对 PL 与 systems 交叉领域来说，它则是一个很好的例子，说明 typestate 和 borrow checking 不只是语言内部的漂亮理论，也能拿来解决真实的系统集成问题。这更像是一种新的机制设计，而不是单纯的基准测试论文。

## 局限性

最明显的限制是 Omniglot 的保证强度取决于 runtime。`OGPMP` 能满足论文设定的对抗性模型，但 `OGMPK` 不能：敌对库仍可能借助系统调用、signal handler 或并发线程绕过 MPK，除非部署者额外做审计或加入 seccomp 一类限制。Omniglot 维护的是 Rust 的 soundness，而不是应用级正确性。外部库仍可能返回错误结果、通过侧信道泄漏信息，或者因为宿主写坏了外部内存而行为异常。

它在表达能力和落地成本上也有边界。那些安全性依赖 provenance、lifetime 或更强逻辑不变量的类型，Omniglot 无法靠字节级观察直接验证，所以部分 API 必须改写成符号句柄而不是直接引用。它也不是现有 unsafe FFI 的即插即用替代品，调用方必须配合 Omniglot 的分配、回调和调用约定；`libpng` 案例甚至需要额外写一个 C wrapper，把 `longjmp` 风格错误转成正常返回值。最后，论文评估的是库级 benchmark，而不是大型端到端应用，因此在真实大代码库里推广 Omniglot 的工程复杂度仍不够清楚。

## 相关工作

- _Lamowski et al. (PLOS '17)_ - Sandcrust 通过 IPC 和序列化隔离 Rust 中的不安全组件，而 Omniglot 面向任意外部库，并保留对外部内存的零拷贝访问。
- _Bang et al. (USENIX Security '23)_ - TRust 提供了对不可信代码的进程内隔离，但 Omniglot 进一步把类型有效性、别名关系和时间约束都纳入了 FFI 边界管理。
- _Kirth et al. (EuroSys '22)_ - PKRU-Safe 利用 MPK 分隔安全语言与不安全语言的堆，而 Omniglot 还必须处理外部返回值验证以及跨库调用的引用生命周期。
- _Patterson et al. (PLDI '22)_ - Semantic soundness for language interoperability 从语义层面分析多语言组合，而 Omniglot 为未经修改、且不可信的外部库提供了一套务实的运行时 discipline。

## 我的笔记

<!-- empty; left for the human reader -->
