---
venue: ASPLOS
year: 2026
title: "ASPLOS '26"
location: "Pittsburgh, USA"
dates: "March 22-26, 2026"
url: "https://www.asplos-conference.org/asplos2026/program/"
paper_count_expected: 152
overview_status: complete
written_by: "Claude Opus 4.7 (Claude Code)"
summary_date: 2026-04-18
categories:
  - id: llm-inference
    title: "LLM 推理"
    description: "LLM 服务化、解码、KV-cache 管理、prefill/decode 解耦、推测解码，以及面向 LLM 的专用加速器。"
  - id: llm-training
    title: "LLM 与基础模型训练"
    description: "LLM 与基础模型训练系统：流水/张量/MoE 并行、混合精度、RL rollout、超级芯片 offload、以及训练监控。"
  - id: ml-systems-beyond-llm
    title: "非 LLM 的 ML 系统"
    description: "3D Gaussian Splatting、扩散模型服务、图 ML、神经符号、移动端与具身智能——主工作负载不是 LLM 的 ML 系统工作。"
  - id: memory-and-disaggregation
    title: "内存与解耦"
    description: "CXL 编程模型、pod 级分配器、页迁移、分层内存、解耦式事务，以及面向解耦存储的数据库下推。"
  - id: privacy-and-security
    title: "隐私与安全"
    description: "FHE 算法与加速器、可信执行环境、机密 Serverless、zkVM，以及隐私保护的模型监控。"
  - id: quantum
    title: "量子计算"
    description: "容错架构、QEC 电路编译与调度、模拟量子模拟、分布式量子算法。"
  - id: compilers-languages-verification
    title: "编译器、语言与验证"
    description: "张量编译器、硬件描述语言、二进制翻译、程序分析、形式化验证、模糊测试、以及 LLM 辅助编译。"
  - id: hardware-and-infrastructure
    title: "硬件与基础设施"
    description: "加速器、PIM、微体系结构、DRAM 保护、SmartNIC I/O、用户态网络、存储栈、GPU 集群，以及数据中心基础设施。"
---

ASPLOS 2026 单轨共录用 **152 篇论文**——这个规模既让本届议程显得庞杂，
也让它成为一张 systems / architecture / PL 三个社区当前投资方向的实景地图。
分布几乎压倒性地偏向 AI：约三分之一的论文在做大模型服务或训练，其下游的
编译器与硬件工作也多半是被 AI 负载塑造。与此同时，ASPLOS 仍然保留了经典
的广度——CXL 时代的内存、量子计算、机密计算和验证都有成规模的投入。

## 主题

**LLM 服务走向工业化。** 152 篇中有 25 篇做 LLM 推理系统。重心已经从
"如何有效地 paged-batch"（已解决）转移到三个更难的问题上：如何协同调度
prefill 与 decode（QoServe、Towards High-Goodput MuxWise、Shift Parallelism、
TPLA、SwiftSpec、Bullet、PAT）；如何在 GPU / CPU / CXL / PIM 之间构建
KV-cache 分层（SpeContext、MoE-APEX、STARC、REPA）；以及定制硅片能走多远
（Hardwired-Neuron LPU、Ouroboros 晶圆级 CIM、DFVG 的 FPGA 起草 + GPU 验证
异构架构）。量化与精度是贯穿整条线的子主题（M2XFP、ZipServ、oFFN、Mugi、
Tilus）——低比特推理现在是一类一等目标，不再是事后优化。

**训练在补课。** llm-training 下只有 8 篇，但覆盖了每一条主线：多模态流水
（DIP）、MoE 再平衡（LAER-MoE）、RL rollout（RhymeRL、Taming the Long-Tail）、
亚字节精度（SNIP）、超级芯片 offload（SuperOffload），以及 SmartNIC 上的
非侵入式监控。相比 2024，社区已经明显越过了"能不能把大模型训起来"这一步，
进入"训练栈的下一个瓶颈在哪里"的阶段。

**CXL 不再只是论文里的概念。** 10+ 篇论文把 CXL 与解耦内存当作可上线的
基础设施：形式化的编程模型（CXL0）、模型检查工具（CXLMC、vCXLGen）、
pod 级分配器（Cxlalloc）、页粒度迁移（PIPM）、关键度优先的分层（PACT）、
解耦事务（CREST、CPU-Oblivious）、跨 coherence domain 的性能预测（Camp）。
话题已经从"CXL 能带来什么"转向"当真实负载跨越 coherence 边界时会坏在哪里"。

**量子计算成为独立轨道。** 11 篇覆盖 QEC 电路调度（AlphaSyndrome、PropHunt、
iSwitch）、脏 qubit 推理（QBorrow）、T-gate 最小化（Reducing T Gates、ACQC
针对 qLDPC）、离子阱架构（Architecting Scalable Trapped Ion）、分布式 QSWAP
（COMPAS）、模拟编译（QTurbo）。这组工作成熟到足以让我们在本次整理中新增
专用的 `quantum` 标签。

**编译器与 PL 是贯通全场的结缔组织。** 34 篇——最大类别——都落在
编译器/PL/验证上。张量编译器继续推进（Trinity、RedFuser、Linear Layouts、
Insum、FuseFlow、Tilus、STeP）；硬件 DSL 不断进化（Anvil 的时序契约、
Lilac 的延迟抽象接口、PDL 的精确异常）；验证延伸到了乱序 dataflow
（Graphiti）和分布式 ML（It Takes Two）；LLM 辅助编译出现了五种不同路线
（LPO 做 peephole、LOOPRAG 做循环、PF-LLM 做预取、Once4All 做 SMT 模糊、
CacheMind 做缓存解释）。

**可靠性无处不在。** DRAM 保护（RowArmor、APT）、超大规模的向量 SDC
（SEVI）、辐射（Radshield）、FHE 加速器的韧性（ReliaFHE）、具身 AI 的
降压（CREATE）、故障注入（PrioriFI）、训练集群监控——可靠性叙事贯穿各个
track 而非集中在某一处。

**FHE 与 TEE 在向生产靠拢。** 6 篇 FHE 加速器论文（Cheddar、Falcon、
Maverick、ReliaFHE、CHEHAB RL、面向 GPU 的 FHE 框架）表明社区相信 FHE 很快
会跨过吞吐与延迟门槛。TEE 一侧：TeeM3 把隔离从 CPU mode 下沉到 tile 控制器；
Trust-V 硬化 TEE 的存储通路；WorksetEnclave 攻击机密 Serverless 的冷启动；
还有一项验证工作在 Arm CCA 规范中发现了 35 处已确认的不一致。

## 值得关注的趋势

- **解耦遍地开花。** GPU 显存 offload、CXL pod、prefill/decode 解耦、
  起草/验证跨 FPGA+GPU 解耦、SmartNIC I/O 解耦——本届的年度关键词是"拆开它"。
- **处处推测。** 解码（SwiftSpec、DFVG）、预取（EARTH）、Protobuf 解析
  （SpecProto）、分支扩展（FastTTS）。"speculate and recover" 成为默认模式。
- **稀疏性是一等公民。** 比特级（BitRed）、动态稀疏（DiT Dynamic Sparsity）、
  流式（FuseFlow）、编译器挖掘（Insum 间接 einsum）、稀疏 SpMM（Slaws）。
  不再是边角情况。
- **能耗成为设计轴。** 20 篇打了 `energy` 标签。功耗/碳/寿命已经与吞吐、
  延迟并列成为设计维度——不只边缘论文（FlexiFlow、TierX），数据中心加速器
  同样在意。

## 必读推荐

- **[Shift Parallelism](/zh-cn/papers/asplos-2026/shift-parallelism-low-latency-high-throughput-llm-inference-for-dynamic-workloads)**：保留 KV-cache 布局，让 LLM 服务在运行时翻转序列与张量并行策略；少见的"越简单越好"式结果。
- **[A Programming Model for Disaggregated Memory over CXL](/zh-cn/papers/asplos-2026/a-programming-model-for-disaggregated-memory-over-cxl)**：CXL0 为多主机 CXL 给出了精确的、propagation-aware 语义，是后续 CXL 研究的基础参考。
- **[Streaming Tensor Programs (STeP)](/zh-cn/papers/asplos-2026/streaming-tensor-programs-a-streaming-abstraction-for-dynamic-parallelism)**：为 spatial dataflow 硬件上的动态形状与控制流给出清晰抽象，无需手工调优即可做动态切片与专家时分复用。
- **[Compositional AI Beyond LLMs](/zh-cn/papers/asplos-2026/compositional-ai-beyond-llms-system-implications-of-neuro-symbolic-probabilistic-architectures)**：从系统侧分析神经-符号-概率负载，点名现今 AI-systems 栈没有为之优化的部分。
- **[SuperOffload](/zh-cn/papers/asplos-2026/superoffload-unleashing-the-power-of-large-scale-llm-training-on-superchips)**：首个在超级芯片上利用 CPU↔GPU 一致内存、而不是与 PCIe 对抗的可信 LLM 训练 offload 设计。

## 数据

- 已总结论文：**152 / 152**
- 类别数：**8**
- 最大类别：compilers-languages-verification 与 hardware-and-infrastructure（各 34 篇）
- 最小类别：llm-training（8 篇）
- 使用的标签数：33（本轮新增 `quantum`）
