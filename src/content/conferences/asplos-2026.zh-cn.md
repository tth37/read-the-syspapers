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
    description: "LLM 服务化、解码、KV-cache 管理、prefill/decode 解耦、推测解码,以及面向 LLM 的专用加速器。"
  - id: llm-training
    title: "LLM 与基础模型训练"
    description: "LLM 与基础模型训练系统:流水/张量/MoE 并行、混合精度、RL rollout、超级芯片 offload、以及训练监控。"
  - id: ml-systems-beyond-llm
    title: "非 LLM 的 ML 系统"
    description: "3D Gaussian Splatting、扩散模型服务、图 ML、神经符号、移动端与具身智能——主工作负载不是 LLM 的 ML 系统工作。"
  - id: memory-and-disaggregation
    title: "内存与解耦"
    description: "CXL 编程模型、pod 级分配器、页迁移、分层内存、解耦式事务,以及面向解耦存储的数据库下推。"
  - id: privacy-and-security
    title: "隐私与安全"
    description: "FHE 算法与加速器、可信执行环境、机密 Serverless、zkVM,以及隐私保护的模型监控。"
  - id: quantum
    title: "量子计算"
    description: "容错架构、QEC 电路编译与调度、模拟量子模拟、分布式量子算法。"
  - id: compilers-languages-verification
    title: "编译器、语言与验证"
    description: "张量编译器、硬件描述语言、二进制翻译、程序分析、形式化验证、模糊测试、以及 LLM 辅助编译。"
  - id: hardware-and-infrastructure
    title: "硬件与基础设施"
    description: "加速器、PIM、微体系结构、DRAM 保护、SmartNIC I/O、用户态网络、存储栈、GPU 集群,以及数据中心基础设施。"
---

ASPLOS 2026 单轨共录用 **152 篇论文**——这个规模既让本届议程显得庞杂,
也让它成为一张 systems / architecture / PL 三个社区当前投资方向的实景地图。
分布几乎压倒性地偏向 AI:约三分之一的论文在做大模型服务或训练,其下游的
编译器与硬件工作也多半是被 AI 负载塑造。与此同时,ASPLOS 仍然保留了经典
的广度——CXL 时代的内存、量子计算、机密计算和验证都有成规模的投入。

## 主题

**LLM 服务走向工业化。** 152 篇中有 25 篇做 LLM 推理系统。重心已经从"如何有效地 paged-batch"(已解决)转移到三个更难的问题上:如何协同调度 prefill 与 decode([QoServe](../papers/asplos-2026/qoserve-breaking-the-silos-of-llm-inference-serving.md)、[MuxWise](../papers/asplos-2026/towards-high-goodput-llm-serving-with-prefill-decode-multiplexing.md)、[Shift Parallelism](../papers/asplos-2026/shift-parallelism-low-latency-high-throughput-llm-inference-for-dynamic-workloads.md)、[TPLA](../papers/asplos-2026/tpla-tensor-parallel-latent-attention-for-efficient-disaggregated-prefill-and-decode-inference.md)、[SwiftSpec](../papers/asplos-2026/swiftspec-disaggregated-speculative-decoding-and-fused-kernels-for-low-latency-llm-inference.md)、[Bullet](../papers/asplos-2026/bullet-boosting-gpu-utilization-for-llm-serving-via-dynamic-spatial-temporal-orchestration.md)、[PAT](../papers/asplos-2026/pat-accelerating-llm-decoding-via-prefix-aware-attention-with-resource-efficient-multi-tile-kernel.md));如何在 GPU / CPU / CXL / PIM 之间构建 KV-cache 分层([SpeContext](../papers/asplos-2026/specontext-enabling-efficient-long-context-reasoning-with-speculative-context-sparsity-in-llms.md)、[MoE-APEX](../papers/asplos-2026/moe-apex-an-efficient-moe-inference-system-with-adaptive-precision-expert-offloading.md)、[STARC](../papers/asplos-2026/starc-selective-token-access-with-remapping-and-clustering-for-efficient-llm-decoding-on-pim-systems.md)、[REPA](../papers/asplos-2026/repa-reconfigurable-pim-for-the-joint-acceleration-of-kv-cache-offloading-and-processing.md));以及定制硅片能走多远([Hardwired-Neuron LPU](../papers/asplos-2026/hardwired-neuron-language-processing-units-as-general-purpose-cognitive-substrates.md)、[Ouroboros](../papers/asplos-2026/ouroboros-wafer-scale-sram-cim-with-token-grained-pipelining-for-large-language-model-inference.md) 晶圆级 CIM、[DFVG](../papers/asplos-2026/dfvg-a-heterogeneous-architecture-for-speculative-decoding-with-draft-on-fpga-and-verify-on-gpu.md) 的 FPGA 起草 + GPU 验证异构架构)。量化与精度是贯穿整条线的子主题([M2XFP](../papers/asplos-2026/m2xfp-a-metadata-augmented-microscaling-data-format-for-efficient-low-bit-quantization.md)、[ZipServ](../papers/asplos-2026/zipserv-fast-and-memory-efficient-llm-inference-with-hardware-aware-lossless-compression.md)、[oFFN](../papers/asplos-2026/offn-outlier-and-neuron-aware-structured-ffn-for-fast-yet-accurate-llm-inference.md)、[Mugi](../papers/asplos-2026/mugi-value-level-parallelism-for-efficient-llms.md)、[Tilus](../papers/asplos-2026/tilus-a-tile-level-gpgpu-programming-language-for-low-precision-computation.md))——低比特推理现在是一类一等目标,不再是事后优化。

**训练在补课。** llm-training 下只有 8 篇,但覆盖了每一条主线:多模态流水([DIP](../papers/asplos-2026/dip-efficient-large-multimodal-model-training-with-dynamic-interleaved-pipeline.md))、MoE 再平衡([LAER-MoE](../papers/asplos-2026/laer-moe-load-adaptive-expert-re-layout-for-efficient-mixture-of-experts-training.md))、RL rollout([RhymeRL](../papers/asplos-2026/history-doesnt-repeat-itself-but-rollouts-rhyme-accelerating-reinforcement-learning-with-rhymerl.md)、[Taming the Long-Tail](../papers/asplos-2026/taming-the-long-tail-efficient-reasoning-rl-training-with-adaptive-drafter.md))、亚字节精度([SNIP](../papers/asplos-2026/snip-an-adaptive-mixed-precision-framework-for-subbyte-large-language-model-training.md))、超级芯片 offload([SuperOffload](../papers/asplos-2026/superoffload-unleashing-the-power-of-large-scale-llm-training-on-superchips.md)),以及 [SmartNIC 上的非侵入式监控](../papers/asplos-2026/fine-grained-and-non-intrusive-llm-training-monitoring-via-microsecond-level-traffic-measurement.md)。相比 2024,社区已经明显越过了"能不能把大模型训起来"这一步,进入"训练栈的下一个瓶颈在哪里"的阶段。

**CXL 不再只是论文里的概念。** 10+ 篇论文把 CXL 与解耦内存当作可上线的基础设施:形式化的编程模型([CXL0](../papers/asplos-2026/a-programming-model-for-disaggregated-memory-over-cxl.md))、模型检查工具([CXLMC](../papers/asplos-2026/cxlmc-model-checking-cxl-shared-memory-programs.md)、[vCXLGen](../papers/asplos-2026/vcxlgen-automated-synthesis-and-verification-of-cxl-bridges-for-heterogeneous-architectures.md))、pod 级分配器([Cxlalloc](../papers/asplos-2026/cxlalloc-safe-and-efficient-memory-allocation-for-a-cxl-pod.md))、页粒度迁移([PIPM](../papers/asplos-2026/pipm-partial-and-incremental-page-migration-for-multi-host-cxl-disaggregated-shared-memory.md))、关键度优先的分层([PACT](../papers/asplos-2026/pact-a-criticality-first-design-for-tiered-memory.md))、解耦事务([CREST](../papers/asplos-2026/crest-high-performance-contention-resolution-for-disaggregated-transactions.md)、[CPU-Oblivious](../papers/asplos-2026/cpu-oblivious-offloading-of-failure-atomic-transactions-for-disaggregated-memory.md))、跨 coherence domain 的性能预测([Camp](../papers/asplos-2026/performance-predictability-in-heterogeneous-memory.md))。话题已经从"CXL 能带来什么"转向"当真实负载跨越 coherence 边界时会坏在哪里"。

**量子计算成为独立轨道。** 11 篇覆盖 QEC 电路调度([AlphaSyndrome](../papers/asplos-2026/alphasyndrome-tackling-the-syndrome-measurement-circuit-scheduling-problem-for-qec-codes.md)、[PropHunt](../papers/asplos-2026/prophunt-automated-optimization-of-quantum-syndrome-measurement-circuits.md)、[iSwitch](../papers/asplos-2026/iswitch-qec-on-demand-via-in-situ-encoding-of-bare-qubits-for-ion-trap-architectures.md))、脏 qubit 推理([QBorrow](../papers/asplos-2026/borrowing-dirty-qubits-in-quantum-programs.md))、T-gate 最小化([Reducing T Gates](../papers/asplos-2026/reducing-t-gates-with-unitary-synthesis.md)、[ACQC](../papers/asplos-2026/accelerating-computation-in-quantum-ldpc-code.md) 针对 qLDPC)、离子阱架构([Architecting Scalable Trapped Ion](../papers/asplos-2026/architecting-scalable-trapped-ion-quantum-computers-using-surface-codes.md))、分布式 QSWAP([COMPAS](../papers/asplos-2026/compas-a-distributed-multi-party-swap-test-for-parallel-quantum-algorithms.md))、模拟编译([QTurbo](../papers/asplos-2026/qturbo-a-robust-and-efficient-compiler-for-analog-quantum-simulation.md))。这组工作成熟到足以让我们在本次整理中新增专用的 `quantum` 标签。

**编译器与 PL 是贯通全场的结缔组织。** 34 篇——最大类别——都落在编译器/PL/验证上。张量编译器继续推进([Trinity](../papers/asplos-2026/trinity-three-dimensional-tensor-program-optimization-via-tile-level-equality-saturation.md)、[RedFuser](../papers/asplos-2026/redfuser-an-automatic-operator-fusion-framework-for-cascaded-reductions-on-ai-accelerators.md)、[Linear Layouts](../papers/asplos-2026/linear-layouts-robust-code-generation-of-efficient-tensor-computation-using-f2.md)、[Insum](../papers/asplos-2026/insum-sparse-gpu-kernels-simplified-and-optimized-with-indirect-einsums.md)、[FuseFlow](../papers/asplos-2026/fuseflow-a-fusion-centric-compilation-framework-for-sparse-deep-learning-on-streaming-dataflow.md)、[Tilus](../papers/asplos-2026/tilus-a-tile-level-gpgpu-programming-language-for-low-precision-computation.md)、[STeP](../papers/asplos-2026/streaming-tensor-programs-a-streaming-abstraction-for-dynamic-parallelism.md));硬件 DSL 不断进化([Anvil](../papers/asplos-2026/anvil-a-general-purpose-timing-safe-hardware-description-language.md) 的时序契约、[Lilac](../papers/asplos-2026/parameterized-hardware-design-with-latency-abstract-interfaces.md) 的延迟抽象接口、[PDL](../papers/asplos-2026/sequential-specifications-for-precise-hardware-exceptions.md) 的精确异常);验证延伸到了乱序 dataflow([Graphiti](../papers/asplos-2026/graphiti-formally-verified-out-of-order-execution-in-dataflow-circuits.md))和分布式 ML([It Takes Two](../papers/asplos-2026/it-takes-two-to-entangle.md));LLM 辅助编译出现了五种不同路线([LPO](../papers/asplos-2026/lpo-discovering-missed-peephole-optimizations-with-large-language-models.md) 做 peephole、[LOOPRAG](../papers/asplos-2026/looprag-enhancing-loop-transformation-optimization-with-retrieval-augmented-large-language-models.md) 做循环、[PF-LLM](../papers/asplos-2026/pf-llm-large-luanguage-muodel-hinted-hardware-purefuetching.md) 做预取、[Once4All](../papers/asplos-2026/once4all-skeleton-guided-smt-solver-fuzzing-with-llm-synthesized-generators.md) 做 SMT 模糊、[CacheMind](../papers/asplos-2026/cachemind-from-miss-rates-to-why-natural-language-trace-grounded-reasoning-for-cache-replacement.md) 做缓存解释)。

**可靠性无处不在。** DRAM 保护([RowArmor](../papers/asplos-2026/rowarmor-efficient-and-comprehensive-protection-against-dram-disturbance-attacks.md)、[APT](../papers/asplos-2026/apt-securing-against-dram-read-disturbance-via-adaptive-probabilistic-in-dram-trackers.md))、超大规模的向量 SDC([SEVI](../papers/asplos-2026/sevi-silent-data-corruption-of-vector-instructions-in-hyper-scale-datacenters.md))、辐射([Radshield](../papers/asplos-2026/radshield-software-radiation-protection-for-commodity-hardware-in-space.md))、FHE 加速器的韧性([ReliaFHE](../papers/asplos-2026/reliafhe-resilient-design-for-fully-homomorphic-encryption-accelerators.md))、具身 AI 的降压([CREATE](../papers/asplos-2026/create-cross-layer-resilience-characterization-and-optimization-for-efficient-yet-reliable-embodied-ai-systems.md))、故障注入([PrioriFI](../papers/asplos-2026/priorifi-more-informed-fault-injection-for-edge-neural-networks.md))、[训练集群监控](../papers/asplos-2026/fine-grained-and-non-intrusive-llm-training-monitoring-via-microsecond-level-traffic-measurement.md)——可靠性叙事贯穿各个 track 而非集中在某一处。

**FHE 与 TEE 在向生产靠拢。** 6 篇 FHE 加速器论文([Cheddar](../papers/asplos-2026/cheddar-a-swift-fully-homomorphic-encryption-library-designed-for-gpu-architectures.md)、[Falcon](../papers/asplos-2026/falcon-algorithm-hardware-co-design-for-efficient-fully-homomorphic-encryption-accelerator.md)、[Maverick](../papers/asplos-2026/maverick-rethinking-tfhe-bootstrapping-on-gpus-via-algorithm-hardware-co-design.md)、[ReliaFHE](../papers/asplos-2026/reliafhe-resilient-design-for-fully-homomorphic-encryption-accelerators.md)、[CHEHAB RL](../papers/asplos-2026/chehab-rl-learning-to-optimize-fully-homomorphic-encryption-computations.md)、面向 [GPU 的 FHE 框架](../papers/asplos-2026/a-framework-for-developing-and-optimizing-fully-homomorphic-encryption-programs-on-gpus.md))表明社区相信 FHE 很快会跨过吞吐与延迟门槛。TEE 一侧:[TeeM3](../papers/asplos-2026/teem3-core-independent-and-cooperating-trusted-execution-environments.md) 把隔离从 CPU mode 下沉到 tile 控制器;[Trust-V](../papers/asplos-2026/trust-v-toward-secure-and-reliable-storage-for-trusted-execution-environments.md) 硬化 TEE 的存储通路;[WorksetEnclave](../papers/asplos-2026/worksetenclave-towards-optimizing-cold-starts-in-confidential-serverless-with-workset-based-enclave-restore.md) 攻击机密 Serverless 的冷启动;还有一项[验证工作](../papers/asplos-2026/detecting-inconsistencies-in-arm-ccas-formally-verified-specification.md)在 Arm CCA 规范中发现了 35 处已确认的不一致。

## 值得关注的趋势

- **解耦遍地开花。** GPU 显存 offload、CXL pod、prefill/decode 解耦、起草/验证跨 FPGA+GPU 解耦、SmartNIC I/O 解耦——本届的年度关键词是"拆开它"。
- **处处推测。** 解码([SwiftSpec](../papers/asplos-2026/swiftspec-disaggregated-speculative-decoding-and-fused-kernels-for-low-latency-llm-inference.md)、[DFVG](../papers/asplos-2026/dfvg-a-heterogeneous-architecture-for-speculative-decoding-with-draft-on-fpga-and-verify-on-gpu.md))、预取([EARTH](../papers/asplos-2026/earth-an-efficient-moe-accelerator-with-entropy-aware-speculative-prefetch-and-result-reuse.md))、Protobuf 解析([SpecProto](../papers/asplos-2026/specproto-a-parallelizing-compiler-for-speculative-decoding-of-large-protocol-buffers-data.md))、分支扩展([FastTTS](../papers/asplos-2026/fasttts-accelerating-test-time-scaling-for-edge-llm-reasoning.md))。"speculate and recover" 成为默认模式。
- **稀疏性是一等公民。** 比特级([BitRed](../papers/asplos-2026/bitred-taming-non-uniform-bit-level-sparsity-with-a-programmable-risc-v-isa-for-dnn-acceleration.md))、动态稀疏([DiT Dynamic Sparsity](../papers/asplos-2026/dynamic-sparsity-in-large-scale-video-dit-training.md))、流式([FuseFlow](../papers/asplos-2026/fuseflow-a-fusion-centric-compilation-framework-for-sparse-deep-learning-on-streaming-dataflow.md))、编译器挖掘([Insum](../papers/asplos-2026/insum-sparse-gpu-kernels-simplified-and-optimized-with-indirect-einsums.md) 间接 einsum)、稀疏 SpMM([Slaws](../papers/asplos-2026/slaws-spatial-locality-analysis-and-workload-orchestration-for-sparse-matrix-multiplication.md))。不再是边角情况。
- **能耗成为设计轴。** 20 篇打了 `energy` 标签。功耗/碳/寿命已经与吞吐、延迟并列成为设计维度——不只边缘论文([FlexiFlow](../papers/asplos-2026/lifetime-aware-design-for-item-level-intelligence-at-the-extreme-edge.md)、[TierX](../papers/asplos-2026/tierx-a-simulation-framework-for-multi-tier-bci-system-design-evaluation-and-exploration.md)),数据中心加速器同样在意。

## 必读推荐

- **[Shift Parallelism](../papers/asplos-2026/shift-parallelism-low-latency-high-throughput-llm-inference-for-dynamic-workloads.md)**:保留 KV-cache 布局,让 LLM 服务在运行时翻转序列与张量并行策略;少见的"越简单越好"式结果。
- **[A Programming Model for Disaggregated Memory over CXL](../papers/asplos-2026/a-programming-model-for-disaggregated-memory-over-cxl.md)**:CXL0 为多主机 CXL 给出了精确的、propagation-aware 语义,是后续 CXL 研究的基础参考。
- **[Streaming Tensor Programs (STeP)](../papers/asplos-2026/streaming-tensor-programs-a-streaming-abstraction-for-dynamic-parallelism.md)**:为 spatial dataflow 硬件上的动态形状与控制流给出清晰抽象,无需手工调优即可做动态切片与专家时分复用。
- **[Compositional AI Beyond LLMs](../papers/asplos-2026/compositional-ai-beyond-llms-system-implications-of-neuro-symbolic-probabilistic-architectures.md)**:从系统侧分析神经-符号-概率负载,点名现今 AI-systems 栈没有为之优化的部分。
- **[SuperOffload](../papers/asplos-2026/superoffload-unleashing-the-power-of-large-scale-llm-training-on-superchips.md)**:首个在超级芯片上利用 CPU↔GPU 一致内存、而不是与 PCIe 对抗的可信 LLM 训练 offload 设计。

## 数据

- 已总结论文:**152 / 152**
- 类别数:**8**
- 最大类别:compilers-languages-verification 与 hardware-and-infrastructure(各 34 篇)
- 最小类别:llm-training(8 篇)
- 使用的标签数:33(本轮新增 `quantum`)
