---
title: "JOSer: Just-In-Time Object Serialization for Heavy Java Serialization Workloads"
oneline: "JOSer 在运行时为每个 Java 类生成专用 serializer，并按类共享 metadata，让 JVM JIT 把重复序列化优化成热路径代码。"
authors:
  - "Chaokun Yang"
  - "Pengbo Nie"
  - "Ziyi Lin"
  - "Weipeng Wang"
  - "Qianwei Yu"
  - "Chengcheng Wan"
  - "He Jiang"
  - "Yuting Chen"
affiliations:
  - "Ant Group, Hangzhou, China"
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Alibaba Group, Shanghai, China"
  - "Ant Group, Shanghai, China"
  - "East China Normal University, Shanghai, China"
  - "Dalian University of Technology, Dalian, China"
  - "Shanghai Key Laboratory of Trusted Data Circulation and Governance, and Web3, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790179"
tags:
  - compilers
  - pl-systems
  - datacenter
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

JOSer 把 Java 对象序列化重新表述成一个 JIT 优化问题，而不是继续把它当作固定库函数问题来做。它在运行时生成按类专用的 serializer / deserializer，把 metadata 按类只写一次，并让 JVM 在重复工作负载里持续优化这些热代码路径。论文在基准测试中报告了最高 `83.7x` 的序列化吞吐提升和 `229x` 的反序列化吞吐提升，并把收益带到了 Flink 与生产级搜索推荐服务里。

## 问题背景

这篇论文抓住的是一个常被低估、但在 Java 大系统里非常贵的成本：对象在内存、存储和网络边界之间来回搬运时，序列化会吞掉大量 CPU。论文的动机案例来自一个基于 Flink 的搜索推荐流水线；在那里，基于 Kryo 的序列化占到一次执行时间的 `14%` 以上，在一个典型 percentile task 中又吃掉了 `22.45%` 的 CPU。到这个量级时，序列化已经不是“底层杂务”，而是会直接限制系统吞吐和延迟的一等瓶颈。

现有方案各有明显短板。像 Protobuf、FlatBuffers 这样的静态方案可以很快，但前提是开发者要手写 schema，并在代码里显式调用对应 serializer。对于接口稳定的场景，这没问题；但对大型 Java 代码库来说，对象定义会频繁演化，有时甚至在运行期才形成，这时手工 schema 的成本会迅速失控。另一方面，Java 内建序列化、Kryo、FST、Hessian 这类动态方案足够灵活，但它们依赖 omni-functional serializer：反射、类型检查、查表分派、虚调用，以及一大堆为了兼容任意对象形状而存在的条件分支。

论文真正指出的问题不只是“这些动态 serializer 本身很慢”，而是“它们还长得很不适合 JVM 去优化”。JIT 擅长处理热、小、结构稳定的方法，却不擅长充满多态和复杂控制流的大型序列化路径。作者甚至给出了很具体的 JVM 门槛：方法太大时会被跳过，或者难以被积极 inline。于是，试图继续把一个通用 serializer 打磨得更快，与直接生成一批适合 JIT 吃下去的小型专用 serializer，并不是同一个问题。JOSer 针对的正是那类重度、重复、长生命周期的工作负载：同一批类的很多实例不断穿过云系统和 AI 系统，而 JIT 与通用 serializer 的错配会被放大成真成本。

## 核心洞察

论文最重要的洞察是：在重度 Java 序列化工作负载里，重复性已经高到足以支持“按类现生成代码”了。系统第一次看到某个类之后，后续序列化就不必继续表现成“每次都解释一个任意对象图”。它完全可以变成“反复执行一段只服务这个类的小程序”。这样一来，原本依赖大量运行时判断的通用问题，就被改写成 JVM 已经非常擅长处理的热代码优化问题。

要让这个思路成立，论文依赖两个配套判断。第一，把 metadata 和 value 分离后，某个类的描述信息只需在对象流里写一次，后面大量对象都可以复用。第二，生成出来的 serializer 必须刻意做成 JIT-friendly：按类专用、控制流扁平、并且在热路径上不再解析 metadata。也就是说，JOSer 真正生效的原因不只是“它会生成代码”，而是它改变了优化表面。JIT 看到的不再是反射和虚调用堆起来的通用逻辑，而是直接字段访问、静态子方法和更少分支组成的稳定路径。只要调用次数够多，JVM 就能在这条路径上做 inline、dead-code elimination、constant propagation 和指令级优化。

## 设计

JOSer 的设计可以拆成三块。第一块是带 meta sharing 的紧凑二进制格式。一个对象流里，metadata 与 value 被分开存放，value 通过引用指向 metadata pool 中的条目。于是，只要很多对象属于同一个类，JOSer 就只需要把该类描述写一次，后续不断追加 value 即可。这个设计同时影响吞吐和数据大小，特别适合成千上万个对象反复复用同一 schema 的场景。

第二块是运行时生成按类专用的 serializer。JOSer 先从类 metadata 构造一个 `ExprTree`，表示这个对象该如何写出各个字段。对 primitive 字段，它直接生成“取字段值 + 写入 buffer”的代码块；对嵌套自定义类型，则递归展开成更多生成代码。最后得到的 serializer 被刻意约束成 small-scale、flat、meta-free：热路径里不再做反射，不再保留大量动态分支，也不再靠通用 dispatcher 去找字段处理逻辑，而是直接访问字段。JOSer 还维护一个 serializer pool，因此某个类第一次出现时才支付生成成本，后面都直接复用。

第三块是让生成代码真正容易被 JVM 优化。因为 JIT 对字节码大小很敏感，JOSer 会用启发式方法把热点 serializer 切分成多个子方法，使每个代码块都尽量落在 JVM 的优化阈值以内，论文给出的默认门槛是 `325` 字节。生成出来的 Java 代码由 Janino 在运行时编译成字节码，再动态加载进 JVM；随着调用次数积累，JIT 会进一步把这些 serializer 编译成高效 native code。反序列化也采用同样的思路：JOSer 按类生成 deserializer、缓存并优化它们，并通过对字段名和字段类型做整数编码，再配合双游标匹配，来处理引用完整性与 schema 变化下的兼容问题。

## 实验评估

这篇论文的实验很贴合它宣称的目标场景，也就是长时间运行、重复序列化的 Java 服务。JOSer 本身用大约 `70K` 行 Java 实现，并在 OpenJDK 11 上借助 JMH，与六个基线比较：Kryo、Hessian、FST、JDK serialization、Protobuf 和 FlatBuffers。基准套件既包含 primitive 对象，也包含 `Sample`、`MediaContent`、`Struct`、`LongStruct` 这样的自定义类；同时还构造了两个更难的变体：带自引用字段的 `Benchmark R`，以及在反序列化阶段故意制造 schema 不一致的 `Benchmark I`。

核心数字相当强。八个基础基准上，JOSer 的序列化吞吐达到 `1.0E+7` 到 `1.4E+8` objects/s，反序列化吞吐达到 `4.3E+6` 到 `8.2E+7` objects/s。若与每个工作负载里最强的基线相比，JOSer 平均还能再快 `4.4x` 的序列化和 `2.3x` 的反序列化；若与最弱基线相比，最高增益则达到 `83.7x` 与 `229x`。更关键的是，作者没有只挑简单 workload 报喜：在需要维护引用完整性和 schema 兼容性的复杂变体里，JOSer 仍然保持最高吞吐，序列化最高领先 `77.6x`，反序列化最高领先 `184.1x`。

消融实验也支撑了设计主张。去掉 JIT 优化，性能最多损失 `3.95x`；去掉 metadata sharing，最多损失 `1.49x`；两个一起去掉则更差。在 `10K` 个 schema 不一致对象组成的对象流上，JOSer 的 meta-packing 让二进制大小比 Kryo 小 `20.46%`，比 Hessian 小 `50.21%`。真正让论文显得不只是“微基准工程”的，是部署结果：在 Flink 任务中，JOSer 把序列化 CPU 使用率降低 `35.32%` 到 `41.14%`，并把某些任务吞吐最高提升到 `83.09x`；在一个生产级搜索推荐系统里，整体 p99 延迟从 `350 ms` 降到 `316 ms`，其中序列化延迟从 `50 ms` 降到 `16 ms`。这些工作负载确实足够重复，也确实在检验论文的中心主张。

## 创新性与影响

和 Kryo、Hessian、Java 内建序列化相比，JOSer 的新意在于它没有继续尝试把“一个通用 serializer”做得没那么差，而是把优化单位改成“许多个按类拆开的微型程序”，再交给 JVM 去专门化。和 Protobuf、FlatBuffers 这样的静态方案相比，它试图在保留 schema-free 灵活性的同时，追回一大块通常只有生成代码才拿得到的性能。和 _Jang et al. (ISCA '20)_ 这种硬件加速思路相比，它则说明：只要把序列化问题重新摆成 JVM 易于优化的形状，软件路径本身也能拿回很大收益。

因此，这篇论文最可能影响两拨人。对 JVM runtime / compiler 研究者来说，它是一个很具体的 domain-specific JIT surface 案例；对数据系统和 Java 服务框架工程师来说，它提供了一条现实路径：不必把整套系统改写成手工 schema 驱动，也能显著回收序列化带来的 CPU 成本。它不是单纯的测量论文，而是把代码生成、meta sharing 和 JIT-aware partitioning 组合成了一条序列化专用的软件机制链条。

## 局限性

论文对代价并不回避。JOSer 通过缓存生成的 serializer 来换速度，因此会额外占用 metaspace。它也保留了引用跟踪、schema 兼容等昂贵功能，只是把它们做成可配置项，而不是假装这些能力没有成本。安全性方面，动态反序列化依然有老问题；JOSer 通过 class registration 和可定制检查策略来缓解，但风险并不会自动消失。

它也有很明确的适用边界。primitive 类型工作负载的收益较小，因为原本就没有太多复杂逻辑可供 JIT 继续优化。更重要的是，JOSer 依赖“serializer 变热”之后才开始真正起飞，所以对短生命周期任务、或对象类型非常分散的工作负载，收益理应更有限；这一点是根据论文的运行时设计和 warmup 行为做出的推断，论文本身没有直接量化。除此之外，实验主体集中在 Java 和重复型云工作负载，因此它没有告诉我们 mixed-language 部署、短作业场景，或者单个 JVM 中类数量极多时的运维开销到底会怎样。

## 相关工作

- _Jang et al. (ISCA '20)_ — 这项工作用专用硬件加速对象序列化，而 JOSer 试图通过暴露 JIT-friendly 的按类代码，在纯软件路径里拿到类似收益。
- _Nguyen et al. (ASPLOS '18)_ — Skyway 通过连接分布式系统中的 managed heap 来绕开序列化；JOSer 则面向那些仍然必须物化成字节流的场景去加速序列化本身。
- _Taranov et al. (USENIX ATC '21)_ — Naos 走的是 serialization-free RDMA 路线，因此是在绕开问题，而不是优化 schema-free Java serialization 的执行路径。
- _Wu et al. (USENIX ATC '22)_ — ZCOT 消除了分析流水线中的对象转换成本，与 JOSer 形成互补：前者尽量不做序列化，后者保留完整序列化语义并把它做快。

## 我的笔记

<!-- 留空；由人工补充 -->
