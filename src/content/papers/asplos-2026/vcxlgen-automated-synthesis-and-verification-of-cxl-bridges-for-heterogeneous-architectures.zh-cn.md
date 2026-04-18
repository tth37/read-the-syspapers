---
title: "vCXLGen: Automated Synthesis and Verification of CXL Bridges for Heterogeneous Architectures"
oneline: "vCXLGen 从一致性协议规格自动合成 CXL bridge，并用组合式验证证明桥接后仍保持各主机的内存语义与系统进展。"
authors:
  - "Anatole Lefort"
  - "Julian Pritzi"
  - "Nicolò Carpentieri"
  - "David Schall"
  - "Simon Dittrich"
  - "Soham Chakraborty"
  - "Nicolai Oswald"
  - "Pramod Bhatotia"
affiliations:
  - "Technical University of Munich, Munich, Germany"
  - "TU Delft, Delft, Netherlands"
  - "NVIDIA, Santa Clara, US"
conference: asplos-2026
category: memory-and-disaggregation
doi_url: "https://doi.org/10.1145/3779212.3790245"
code_url: "https://github.com/TUM-DSE/vCXLGen"
project_url: "https://doi.org/10.5281/zenodo.17939343"
tags:
  - disaggregation
  - hardware
  - verification
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

vCXLGen 解决的是 CXL 落地里一个一直缺失的环节：不同主机带着不同的一致性协议和内存模型，怎样接到同一个 coherent CXL fabric 上，而不是为每种主机手写一套桥接逻辑。它从协议规格自动合成 bridge，再用组合式模型检查证明安全性与进展性，把原本很快爆炸的整体验证规模压到可处理范围。

## 问题背景

CXL 3.0 让多主机共享一致性内存看起来触手可及，但论文指出规范实际上只定义了 fabric 这一侧。它没有告诉 CPU 或加速器厂商，怎样把 CXL.mem 和主机内部已有的 local cache coherence protocol 以及 memory consistency model 接起来。这个缺口在异构系统里尤其致命，因为 x86、Arm 和加速器协议虽然都谈“共享内存”，但内部对消息、竞争和顺序约束的理解并不相同。

给每种主机手工补一段 CXL 逻辑看起来直接，实际上很脆弱。哪怕两个协议表面上都像 MESI，边角语义也可能完全不同；CXL.mem 有 `BIConflict` 之类的握手，而 relaxed protocol 又可能把一致性动作绑定到 acquire/release 事件，而不只是普通 load/store。更糟的是，一个错误的 bridge 不只是会拖慢性能，还可能悄悄改变主机原本的内存模型。

已有自动化工作也没有真正覆盖这个接口。层次化或异构协议生成器通常假设更固定的 hierarchy，而整体验证一旦把多个 cluster、bridge 和 CXL 目录一起建模，状态空间很快失控。所以论文真正要解决的问题是：怎样自动生成一个既保留各主机本地语义、又能与 CXL.mem 正确互操作、还能够在系统规模上被验证的 bridge。

## 核心洞察

论文最重要的判断是：主机到 CXL 的互操作应该被表达为两个一致性域之间自动合成出来的 bridge，而不是把某个现有主机协议手工改造成“支持 CXL 的新协议”。这个 bridge 同时维护主机侧的 local directory state 和 CXL 侧的 global cache state，因此能判断某个本地事务何时必须升级成全局可见的动作，也能判断某个来自 CXL 的事件应当怎样翻译回主机域。

之所以这件事能自动化，是因为作者把跨域传播约束成三条规则：delegation、nesting atomicity 和 selective stalling。需要跨域传播的动作，必须用远端协议原生的事务流来实现；本地流程只有在远端流程完成后才能宣告完成；而 bridge 只阻塞那些真的会破坏顺序的请求，同时允许必要的 CXL snoop 继续前进以避免死锁。

这样一来，compound memory model 就不再只是抽象原则，而变成了可执行的合成方法。bridge 不需要手工理解每一对协议的完整语义，只需要识别哪些局部或全局事务本质上对应必须传播的访问，再在另一侧重放等价访问即可。

## 设计

vCXLGen 的输入是用 ProtoGen DSL 写成的协议规格：一个本地协议 `LP`，一个全局协议 `GP`，例如 CXL.mem。它先把协议解析成有限状态机图，再通过 static flow analysis 构造 translation table：从稳定状态加第一条转移标签，推断出背后的请求者访问类型，例如 `S + GetM -> store`。它也会识别哪些来自全局域的 forwarded request 代表权限降级，因此必须翻译回主机域。

接下来，bridge 的状态空间由“本地目录稳定状态”和“全局 cache 稳定状态”的笛卡尔积组成。凡是不需要传播的事务流，直接复制到 bridge；一旦某个事务需要传播，系统就在远端协议里搜索以等价访问类型开头的子树，并把它嵌套进发起域的事务流内部。如果两个协议的访问词汇表不同，则通过 ArMOR 风格的映射来对齐。

最难的是并发。vCXLGen 会自动合成 transient bridge state，让传播中的事务能够阻塞来自发起域的冲突请求；但当嵌套的是全局 CXL 一侧时，决定目录串行化顺序的 snoop 仍必须允许交错执行，否则 bridge 可能会把完成当前请求所必需的事件自己卡住。最终，同一份 bridge IR 既能输出 gem5 的 SLICC 控制器，也能输出 Murphi 和 Rumur 模型。论文还给出 `SC-vCXLGen-RC` 的公理化模型，用来解释为什么桥接后各主机仍能保留本地内存语义。

## 实验评估

这篇论文的评估维度比很多 synthesis 论文更完整。首先看通用性，作者成功合成了 MSI、MESI、MOESI、CXL、RCC、RCC-O 等多种组合，其中 CXL 充当全局协议，本地协议既可以是 SWMR，也可以是 relaxed consistency。可扩展性方面，输入规格规模也很可信：CXL.mem 大约 650 行 ProtoGen DSL，MSI 家族大约 350 行，RC 协议大约 200 行。

正确性验证分成两层。安全性方面，作者针对 SC/RC 组合生成了 216 个 litmus test 模型，结果全部与目标 compound memory model 一致。进展性方面，他们检查 deadlock freedom 和 extended liveness。这里最重要的不只是“验证通过”，而是组合式方法把验证从不可做变成可做：相对于整体验证，内存占用在中等规模模型上下降 92%，在更大模型上下降超过 98%，把一个双 cluster、每 cluster 三个 cache 的系统压到 60 GB 以内；完整模型即使在 1.8 TB 内存服务器上也会 OOM。

性能方面，作者在 gem5 上评估了 35 个来自 PARSEC、Phoenix 和 SPLASH 的程序，以及一个跑 YCSB 的分布式内存 KVS。自动生成的同构桥版本 `MESI-Br` 对 gem5 里的同构 `MOESI` 基线几乎没有额外成本，多数 workload 维持在大约正负 2% 以内，最差报告为 10%。`CXL-Br` 在多数应用里也接近基线，但有七个应用的平均开销最高到 20.3%，论文将其归因于 CXL.mem 自身的握手和 blocking transient states，而不是 bridge 生成质量。在 KVS 上，`CXL-Br` 吞吐与基线只差 1%，`MESI-Br` 则高出 6-8.8%。

## 创新性与影响

和 _Oswald et al. (HPCA '22)_ 相比，这篇论文的新意在于它专门面向 CXL 的 local/global 分层接口，而不是抽象地做一次异构协议融合。和 _Goens et al. (PLDI '23)_ 相比，它把 compound memory model 推进到可执行层面：既有具体协议合成，也有 litmus test 验证和 gem5 执行路径。和 _Olson et al. (ASPLOS '17)_ 这类手工设计的 host-accelerator adapter 相比，它把一次性的 glue logic 提升成了可复用的 generator 加验证流水线。

因此，这篇论文同时会吸引两类读者：一类是要把未来主机或加速器接到 CXL.mem 上的体系结构设计者，另一类是需要为真实异构一致性系统做可扩展进展性证明的形式化验证研究者。

## 局限性

论文的覆盖面很广，但也有明确边界。首先，它假设全局协议不能比被桥接的本地协议更弱，所以现实里最合适的仍是像 CXL.mem 这样维持 SWMR 的全局协议。其次，这套方法依赖机器可读的协议规格，而且规格必须暴露足够的访问与消息结构，才能恢复出可靠的语义映射。

验证方面，成本并没有完全消失。生成出的 Rumur 模型编译本身就是显著的资源消耗来源；对更大的系统，整体验证依旧不可行，只能依赖组合式分解。性能方面，证据主要来自 gem5，而非真实硅片；论文诊断了 CXL.mem 握手带来的额外成本，但没有真正消除它们。最后，作者明确选择同步的嵌套传播，而不是更激进的非原子设计，这对通用性和正确性更安全，但也保守了一些潜在的延迟优化空间。

## 相关工作

- _Oswald et al. (HPCA '22)_ — HeteroGen 合成的是一般意义上的异构一致性协议，而 vCXLGen 专门处理 CXL 多主机场景里 local/global 分层以及 bridge 语义。
- _Goens et al. (PLDI '23)_ — Compound Memory Models 给出了异构线程仍可保留本地内存模型视图的理论基础，vCXLGen 则把这个思想落成了可生成、可验证的 bridge。
- _Tan et al. (ASPLOS '25)_ — Formalising CXL Cache Coherence 关注 CXL 协议本身的形式语义，vCXLGen 关注的是如何把现有主机协议接到 CXL.mem 上，并证明整个系统既正确又能前进。

## 我的笔记

<!-- empty; left for the human reader -->
