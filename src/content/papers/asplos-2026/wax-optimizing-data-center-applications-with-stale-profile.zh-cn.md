---
title: "Wax: Optimizing Data Center Applications With Stale Profile"
oneline: "Wax 用源码与调试信息把旧版本 profile 映射到新二进制，恢复 stale profile 在代码布局优化里的大部分价值。"
authors:
  - "Tawhid Bhuiyan"
  - "Sumya Hoque"
  - "Angélica Aparecida Moreira"
  - "Tanvir Ahmed Khan"
affiliations:
  - "Columbia University, New York, NY, USA"
  - "Microsoft Research, Redmond, WA, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790248"
code_url: "https://github.com/ice-rlab/wax"
tags:
  - compilers
  - datacenter
  - caching
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Wax 解决的是一个很现实的 PGO 落地问题：生产团队往往只能用上一个版本采到的 profile 去优化即将发布的新二进制，但这份 profile 里大部分样本其实已经 stale。论文认为，单靠二进制级相似性去对齐新旧版本，对 C++ 数据中心应用来说过于脆弱，因为函数名、内联决策和 basic block 内容都会在发布间隔中快速漂移。Wax 因而把源码和调试信息当成更稳定的锚点，再据此把 stale profile 的函数与 basic block 映射到 fresh binary 上，从而回收大部分 fresh profile 本应带来的收益。

## 问题背景

论文的出发点是数据中心 CPU 前端效率损失。大型服务的代码 footprint 很大，I-cache、iTLB 和 BTB 很容易被打爆，所以业界已经广泛依赖 AutoFDO、BOLT、Propeller 这类 profile-guided code layout 工具来把热路径重新排布到一起。问题在于，真正有代表性的 profile 只能从线上真实流量里采，而不是在发布前离线伪造出来；这就意味着，团队在优化今天的二进制时，手里拿到的往往只能是上一版甚至更老版本的 profile。

在论文面向的发布节奏里，源码每一到两周就会变化一次，而先前工作报告说，在这样的时间尺度上，`70-92%` 的 profile 样本都可能已经 stale。对 layout optimizer 来说，这不是“小误差”，因为优化器需要知道 stale binary 里哪些 hot function 和 hot basic block 对应 fresh binary 中的哪里。论文首先量化了这个损失：在 `gcc`、`clang`、`mysql`、`postgresql` 和 `mongodb` 上，fresh profile 可以带来 `7.64%-38.45%` 的速度提升，而当时最好的 stale-profile 映射方法只能拿到 `3.9%-18.6%`。作者的判断是，问题不在于 stale profile 完全失去信息，而在于映射层先坏掉了，导致后面的 BOLT 根本看不到正确的热点。

论文把根因拆成两个。第一，函数映射若只看 mangled name 的 edit distance，一旦 namespace、basename、参数列表或者 LTO suffix 变化，就会出现 name ambiguity；作者报告这会让先前方法丢掉 `2%-33.9%` 的函数样本。第二，basic block 若只靠二进制 hash 去匹配，哪怕只是很小的源码改动、单条指令 opcode 变化、或不同版本编译器做出了不同的 inlining 决策，也足以让 block content 和 CFG 邻接关系变化，最终让 `9.5%-39.3%` 的 basic-block 样本失配。于是，真正的系统问题变成了：怎样在不要求每次发版都重新做 fresh online profiling 的前提下，让 stale profile 重新可用。

## 核心洞察

Wax 的核心判断是，profile staleness 不应该被建模成“纯二进制相似性”问题。现代 PGO pipeline 里本来就存在 source tree 和 debug metadata，它们把机器码重新连回文件与行号，而这种锚点跨版本变化时往往比 mangled name 或整块 basic block hash 更平滑。只要先借助 source location 把 stale 和 fresh binary 对齐，很多会让 binary-only 方法失效的变化，其实并不会真正破坏 profile 的可迁移性。

这个判断带来两个直接后果。其一，函数身份不应被当作一个整体字符串来比较，而应把 namespace、basename、parameters、suffix 拆开逐步比，因为论文的 characterization 已经表明这些组件的漂移频率并不相同。其二，basic block 也不该只按 whole-block hash 去认亲，而应该通过其中指令所对应的 source location 来比较，因为函数内联和小规模源码修改经常会改变 block 边界，但未必会摧毁底层的源码对应关系。换句话说，Wax 把 debug information 当成 stale profile 与 fresh generated code 之间的桥。

## 设计

Wax 有三个模块：Function Mapping、Source Mapping 和 Basic-block Mapping。Function Mapping 先拿“最容易”的部分开局：凡是 mangled name 完全相同的函数，直接配成 1 对 1。对剩余那些仍然携带 profile 样本的 stale function，Wax 先通过路径名、父目录和必要时的 Levenshtein similarity 去映射 source file；然后在匹配好的文件对内部，把函数名 demangle 后分别比较 namespace、basename、parameters 和 suffix。每得到一批新的唯一匹配，流程就从头再跑一遍。这个设计和“一次性比较整串名字”的最大差别在于，它显式利用了不同名字组件稳定性不同这一经验事实。

Source Mapping 进一步把桥梁细化到行级别。Wax 先映射 source file，再读取文件内容，优先锁定完全相同的行。已有的精确行匹配会把搜索空间切成多个局部区间，于是剩余行只需在更可信的局部范围内做 sequential matching 和 fuzzy matching。论文特别区分了 source line 和 source location：前者只是 `(file, line)`，后者则是 `(mapped function, file, line)`。这个区别很关键，因为同一行源码在内联之后可能出现在多个函数中，所以 basic-block mapping 不能只看文本行号，还必须带上函数上下文。

Basic-block Mapping 是最技术性的部分。Wax 利用 debug information 先把 stale 和 fresh 指令按 mapped source location 划分到同一分区里，然后在每个分区内部按 opcode 与 operand 相似度去匹配指令，优先考虑 opcode，再用顺序关系打破平分。接着，它把这些 instruction mapping 向上汇总为 basic-block similarity：对每个 stale/fresh block 对，累加其中已映射指令的相似度。若仍有歧义，就先看已经映射好的 control-flow neighbors 是否支持某个 block 对，再不行才用函数内部的顺序关系做最后 tie-break。这样做的核心价值在于避免 whole-block hashing，而这恰恰是论文在问题分析里证明最脆弱的那一层。

实现上，Wax 并没有重写一个新的 optimizer。它是一个 Python 工具，借助 LLVM 工具链读取 symbol 和 debug info，再额外加少量 LLVM 代码导出 CFG/basic-block 数据，最后把映射后的 stale profile 喂给 BOLT 或 Propeller。也就是说，论文真正贡献的是一个 profile-translation layer，而不是另起炉灶的代码布局优化器。

## 实验评估

实验使用五个具有大代码 footprint 的开源应用作为生产数据中心二进制的代理：`gcc`、`clang`、`mysql`、`postgresql` 和 `mongodb`。硬件平台是一台 Intel Platinum 8380 服务器，profile 由 LBR 采集。整个实验流程尽量贴近先前工作：先分别构建 stale 与 fresh binary，采集 stale 与 fresh profile，再用 BOLT 去优化 fresh binary。这样的设置比较合理，因为它把变量集中在“stale profile 映射得是否更准”，而不是靠换一个 optimizer 来拿结果。

headline result 很强。Wax 在五个应用上带来 `5.76%-26.46%` 的加速，平均 `14.32%`；论文把它换算为 fresh profile 平均 `18.56%` 收益的 `77.14%`。和 Ayupov et al. 相比，Wax 的绝对 speedup 还能再多出 `1.20%-7.86%`。而且这不是只看端到端速度的单点结果，论文还给出了更底层的映射证据：例如在 `gcc` 上，Wax 能映射 `166,669 / 166,943` 个 stale function samples，而先前方法只有 `110,127`；在 basic-block samples 上，Wax 是 `2,977,511 / 3,598,300`，先前方法只有 `1,562,178`。其他应用也呈现类似趋势。

我觉得这篇论文的加分项在于，它没有把实验停在“平均速度更高”这一层。Wax 在不同 `mysql` query mix 下都优于先前方法，在 `mysql` 和 `gcc` 的 minor / major version gap 上也都保持优势；随着 profile staleness 加深，Wax 相对 prior work 的收益还会进一步扩大。作者还测试了带有 inlining、`LTO` 和 `AutoFDO` 的 baseline binary，结果仍然成立。微结构层面的指标也和论文叙事一致：Wax 比 prior work 降低了更多的 L1I、L2I、iTLB 和 BTB miss。成本方面，完整的 source+debug pipeline 最高需要 `3.25` 分钟和 `48.4 GB` 内存，这不算轻，但对离线发版优化流程来说仍在可接受范围内。

## 创新性与影响

相对 _Ayupov et al. (CC '24)_ 和更早的 _Wang et al. (JILP '00)_ 这类 binary-matching 工作，Wax 最重要的新意不是“匹配算法又强了一点”，而是重新定义了问题边界：既然现代 PGO toolchain 里本来就有 source/debug information，就不该把 stale-profile 恢复强行压缩成纯二进制相似性任务。相对 _Panchenko et al. (CGO '19)_，Wax 与 BOLT 的关系是互补而不是替代，它改善的是 profile 交接质量，而不是 layout optimizer 本身。相对 _Zhang et al. (MICRO '22)_ 这类 online 优化系统，Wax 则说明：只要映射层足够强，一个 offline stale-profile pipeline 也可能跑赢依赖 fresh profile 的 online 方法。

因此，这篇论文会同时影响两个方向的人。一类是做 compiler / binary optimization 的研究者，他们会把 Wax 看成跨版本 profile propagation 的新范式。另一类是做数据中心性能工程的实践者，他们更可能把它当成一个 release engineering 工具：如果 fresh profiling 的操作链路太慢、太贵或太晚，Wax 提供了一条把旧 profile 继续榨出价值的现实路径。

## 局限性

Wax 的前提条件也限定了它的适用范围。它依赖 stale 和 fresh build 都能拿到源码以及质量尚可的 debug information，因此对 stripped third-party binary 或 debug fidelity 很差的流水线并不友好。论文也明确承认，激进优化会劣化 debug 信息质量，只是其评估显示这种劣化尚不足以阻止 Wax 映射大多数 identical function 和 basic block。

另外，实验叙事比动机叙事更窄。五个开源应用是合理代理，但毕竟不是引言里提到的 warehouse-scale 私有服务；主实验也大多是一跳 stale-to-fresh 的版本关系，更长跨度主要放到 sensitivity analysis 里展示。最后，原型的内存消耗能到几十 GB，这对离线流程还算可以，但在资源更紧张的构建环境里可能是实际部署门槛。

## 相关工作

- _Ayupov et al. (CC '24)_ — 最直接的对比基线；它只用二进制相似性传播 stale profile，而 Wax 额外利用 source/debug-aware mapping 恢复了更多 stale 样本。
- _Panchenko et al. (CGO '19)_ — BOLT 是 Wax 最终喂入的 post-link optimizer；Wax 不替代 BOLT，而是提升 BOLT 所接收 profile 的质量。
- _Shen et al. (ASPLOS '23)_ — Propeller 做的是 profile-guided relinking，而论文展示了 Wax 的映射同样能帮助 Propeller 用 stale profile 优化 `clang`。
- _Zhang et al. (MICRO '22)_ — OCOLOS 通过在线优化规避 staleness；Wax 则表明，若离线映射足够强，stale-profile pipeline 也能在论文的 `mysql` 实验里胜过这类 online 方法。

## 我的笔记

<!-- 留空；由人工补充 -->
