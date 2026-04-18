---
title: "Sharpen the Spec, Cut the Code: A Case for Generative File System with SysSpec"
oneline: "SysSpec 用结构化的功能、模块与并发规格替代模糊提示，让 LLM 能生成并演化可用文件系统，而不是持续手改底层 C 代码。"
authors:
  - "Qingyuan Liu"
  - "Mo Zou"
  - "Hengbin Zhang"
  - "Dong Du"
  - "Yubin Xia"
  - "Haibo Chen"
affiliations:
  - "Institute of Parallel and Distributed Systems, Shanghai Jiao Tong University"
conference: fast-2026
category: os-and-io-paths
code_url: "https://github.com/LLMNativeOS/specfs-ae"
project_url: "https://llmnativeos.github.io/specfs/"
tags:
  - filesystems
  - formal-methods
  - pl-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

`SysSpec` 的核心观点是：如果开发者不再用自由文本提示 LLM，而是改写成覆盖行为、模块接口和并发规则的结构化规格，那么 LLM 就能生成并持续演化一个不算简单的文件系统。它的原型 `SpecFS` 在已实现功能上达到了与人工基线相当的实际正确性，而且可以通过 spec patch 吸收十个来自 `Ext4` 的真实特性，而不需要手工修改底层 C 代码。

## 问题背景

这篇论文首先指出，文件系统真正难的地方并不只是“第一次把它写出来”，而是后续漫长且持续的演化过程。作者统计了 Linux `2.6.19` 到 `6.15` 期间 `Ext4` 的 `3,157` 个提交，发现真正新增特性的提交只占 `5.1%`，而 `82.4%` 都是 bug 修复或维护工作。`fast commit` 的案例尤其典型：初始特性只用了 `9` 个提交，但之后又引出了大约 `80` 个提交去修稳定性、边角语义和跨模块问题。

恰恰在这个阶段，朴素的 LLM 代码生成最容易失效。自然语言提示很难精确写出文件系统所依赖的关键约束，例如某个 helper 暴露什么保证、共享数据结构改动后哪些模块会受影响、某条路径上必须持有什么锁。整体系一次性生成会超出模型的上下文和集成能力；按模块逐个生成又会引入接口不匹配和跨模块破坏。更麻烦的是，LLM 输出本身带有非确定性，因此系统软件框架不能把第一版生成结果默认当成可信实现。

## 核心洞察

论文最重要的主张是：生成式文件系统之所以可行，不是因为 prompt engineering 终于足够强，而是因为开发者把“模糊提示”升级成了一份轻量但结构化的形式化设计。`SysSpec` 并不追求传统意义上的完全证明，但它强制把最关键的语义外显出来：每个模块做什么、依赖什么、并发应该如何工作。

一旦这种结构存在，代码生成就变成了代码再生成。开发者修改的是规格，而不是直接补 C 补丁；工具链则可以根据规格变化，重新合成所有受影响模块，同时保持声明好的接口和不变量。换句话说，这篇论文把 specification 视为长期维护的核心资产，把生成出来的代码视为其可替换的投影。

## 设计

`SysSpec` 由三层规格组成。功能规格层为每个模块提供 Hoare 风格的前置条件、后置条件、不变量，以及在必要时给出 system algorithm 或高层 intent。这样开发者既能说明函数必须完成什么状态转换，也能告诉模型应采用什么性能相关的实现策略。模块化规格层把文件系统切分成足够小、能够完整装入模型上下文的模块，并用 `Rely`/`Guarantee` 合同描述模块之间的依赖，使接口成为显式对象，而不是散落在 prompt 里的隐式背景。

并发规格层是这篇论文最关键的工程设计。作者没有把功能逻辑和锁逻辑混在一个提示里，而是将两者分离：`SpecCompiler` 先生成顺序版本，再根据专门的并发规格做第二遍插桩，补上锁与并发行为。`atomfs_ins` 的例子说明了这样做的价值：模型不仅要知道调用哪些 helper，还要知道这些 helper 对锁拥有关系的前置和后置要求。

演化则通过 DAG 结构的 spec patch 完成。叶子节点描述自包含的新逻辑，中间节点基于下游节点新提供的保证继续构建，高层根节点则重新提供与旧实现语义等价的外部保证，从而让新实现可以干净地替换旧实现。论文中的 extent 示例就是按照这个依赖顺序更新数据结构、底层文件操作和 inode 管理。围绕这些规格，工具链提供三个 agent：负责生成的 `SpecCompiler`、负责规格检查和回归测试的 `SpecValidator`，以及帮助开发者润色草稿规格的 `SpecAssistant`。其中一个关键机制是 retry-with-feedback：审阅模型先指出候选实现违反规格的具体位置，再把这些可操作反馈回灌给生成模型。

## 实验评估

原型 `SpecFS` 是一个基于 `FUSE` 的并发内存文件系统，由 `SysSpec` 自动生成，整体设计参照 `AtomFS`。它包含 `45` 个模块和大约 `4,300` 行生成的 C 代码。在 `xfstests` 上，它只在 `754` 个用例里失败了 `64` 个，而论文将这些失败归因于尚未实现的功能，而不是已支持操作的错误实现。

更核心的证据来自代码合成准确率。针对 `AtomFS` 的 `45` 个模块，`SysSpec` 在 `Gemini-2.5-Pro` 和 `DeepSeek-V3.1 Reasoning` 上都达到 `100%` 准确率；相比之下，最强的 oracle baseline 即便把依赖模块代码也放进上下文里，最高也只有 `81.8%`。在演化场景下，系统又实现了十个受 `Ext4` 启发的特性，共涉及 `64` 个功能模块，论文报告其准确率更高，因为很多 patch 是在已有规格上增量修改，而不是从零构造整块逻辑。消融实验也支持作者的设计判断：功能规格加模块化规格足以解决无并发模块，但线程安全模块必须再加显式并发规格和自验证，才能从 `0/5` 提升到 `5/5`。

论文还证明“易演化”不是纸面说法。与研究生手工实现相比，`SpecFS` 在 extent 特性上的开发效率提升了 `3.0x`，在并发更复杂的 rename 路径上提升了 `5.4x`。而且这些 patch 不只是让代码更好写：delayed allocation 在 `xv6` 编译工作负载上最多把数据写次数降到原来的 `0.1%`，也就是最多减少 `99.9%`；extent、inline data、pre-allocation 和基于红黑树的块池管理也都在各自目标指标上带来了预期改进。

## 创新性与影响

相对 `AtomFS`、`FSCQ` 这类已验证文件系统，论文的创新点不在于给出更强的证明，而在于重新定义 specification 的角色：它不再只是验证人工实现的依据，而是直接成为人与 LLM 工具链之间的接口。相对一般的 repo-level 代码代理，论文的判断也很明确：对文件系统来说，问题不在于 prompt 还不够花哨，而在于语义、组合关系和锁规则必须被提升为一等设计对象。

因此，这项工作同时会吸引文件系统开发者和偏 PL 的系统研究者。如果这条路线未来能从 `FUSE` 原型扩展到更接近工业实现的系统，它暗示了一种新的维护模式：修改规格、重新生成受影响模块、再验证，而不是在 C 代码里手动追踪跨模块连锁反应。

## 局限性

论文对当前原型的边界说得比较清楚。`SpecFS` 仍然是用户态 `FUSE` 文件系统，没有原生存储栈、没有直接磁盘访问，也没有 crash consistency 故事，因此它的性能结果只能证明机制本身有效，不能与内核文件系统做严格的 apples-to-apples 比较。它的正确性论证也属于务实路线：结合测试、agent 审查和部分人工检查，而不是机械化证明。

另外，工作量并没有消失，而是发生了转移。`SysSpec` 能节省手写实现成本，前提是开发者能写出高质量规格；而对于 `Ext4`、`EROFS` 这类带有历史包袱、文档不完整、角落语义很多的工业系统，这种规格编写和维护成本到底有多高，论文还没有真正解决。

## 相关工作

- _Zou et al. (SOSP '19)_ — `AtomFS` 是最直接的技术前身；`SysSpec` 继承了“精确设计契约”的思路，但把目标从证明导向实现转成了面向 LLM 的生成与演化。
- _Chen et al. (USENIX ATC '16)_ — `FSCQ` 为手工实现的文件系统证明了 crash safety，而 `SysSpec` 则用较弱的保证换取更广义的合成与迭代演化能力。
- _Zou et al. (OSDI '24)_ — `RefFS` 延续了 verified file system 的路线，强调更强的形式化推理；`SysSpec` 关注的则是把 specification 直接变成生成输入，而不只是验证依据。
- _Guo et al. (ICSE '25)_ — `Intention Is All You Need` 说明了自然语言 intent 对代码修改有帮助，但 `SysSpec` 认为文件系统仍然需要显式的模块合同和并发合同。

## 我的笔记

<!-- empty; left for the human reader -->
