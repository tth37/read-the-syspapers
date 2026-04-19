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
    description: "LLM 与基础模型训练系统:流水/张量/MoE 并行、混合精度、RL rollout、超级芯片 offload,以及训练监控。"
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
    description: "张量编译器、硬件描述语言、二进制翻译、程序分析、形式化验证、模糊测试,以及 LLM 辅助编译。"
  - id: hardware-and-infrastructure
    title: "硬件与基础设施"
    description: "加速器、PIM、微体系结构、DRAM 保护、SmartNIC I/O、用户态网络、存储栈、GPU 集群,以及数据中心基础设施。"
---

ASPLOS 2026 单轨录用了 **152 篇论文**,规模大到像一幅摊开的地图——看一眼就知道 systems、architecture 和 PL 这三个社区这一年把力气砸在了哪里。整份程序被 AI 染得极重,差不多三分之一都在做大模型的服务或训练,往下游的编译器、硬件工作也大半是沿着 AI 负载的形状长出来的。话虽如此,ASPLOS 传统的广度并没有被挤掉:CXL 时代的内存、量子计算、机密计算、形式化验证,每一块都还有相当的体量。

## 主题

**LLM 服务已经工业化了。** 152 篇里有 25 篇做 LLM 推理系统。重心早就不在「paged batching 要怎么做对」——这一题算是翻篇了——而是换成了三组更硬的问题。第一组是 prefill 与 decode 到底怎么协同调度([QoServe](../papers/asplos-2026/qoserve-breaking-the-silos-of-llm-inference-serving.md)、[MuxWise](../papers/asplos-2026/towards-high-goodput-llm-serving-with-prefill-decode-multiplexing.md)、[Shift Parallelism](../papers/asplos-2026/shift-parallelism-low-latency-high-throughput-llm-inference-for-dynamic-workloads.md)、[TPLA](../papers/asplos-2026/tpla-tensor-parallel-latent-attention-for-efficient-disaggregated-prefill-and-decode-inference.md)、[SwiftSpec](../papers/asplos-2026/swiftspec-disaggregated-speculative-decoding-and-fused-kernels-for-low-latency-llm-inference.md)、[Bullet](../papers/asplos-2026/bullet-boosting-gpu-utilization-for-llm-serving-via-dynamic-spatial-temporal-orchestration.md)、[PAT](../papers/asplos-2026/pat-accelerating-llm-decoding-via-prefix-aware-attention-with-resource-efficient-multi-tile-kernel.md));第二组是 KV-cache 怎么在 GPU / CPU / CXL / PIM 之间搭出层级([SpeContext](../papers/asplos-2026/specontext-enabling-efficient-long-context-reasoning-with-speculative-context-sparsity-in-llms.md)、[MoE-APEX](../papers/asplos-2026/moe-apex-an-efficient-moe-inference-system-with-adaptive-precision-expert-offloading.md)、[STARC](../papers/asplos-2026/starc-selective-token-access-with-remapping-and-clustering-for-efficient-llm-decoding-on-pim-systems.md)、[REPA](../papers/asplos-2026/repa-reconfigurable-pim-for-the-joint-acceleration-of-kv-cache-offloading-and-processing.md));第三组则是定制硅还能走到哪一步([Hardwired-Neuron LPU](../papers/asplos-2026/hardwired-neuron-language-processing-units-as-general-purpose-cognitive-substrates.md)、[Ouroboros](../papers/asplos-2026/ouroboros-wafer-scale-sram-cim-with-token-grained-pipelining-for-large-language-model-inference.md) 的晶圆级 CIM、[DFVG](../papers/asplos-2026/dfvg-a-heterogeneous-architecture-for-speculative-decoding-with-draft-on-fpga-and-verify-on-gpu.md) 的 FPGA 起草配 GPU 验证)。量化和精度则是贯穿始终的副线([M2XFP](../papers/asplos-2026/m2xfp-a-metadata-augmented-microscaling-data-format-for-efficient-low-bit-quantization.md)、[ZipServ](../papers/asplos-2026/zipserv-fast-and-memory-efficient-llm-inference-with-hardware-aware-lossless-compression.md)、[oFFN](../papers/asplos-2026/offn-outlier-and-neuron-aware-structured-ffn-for-fast-yet-accurate-llm-inference.md)、[Mugi](../papers/asplos-2026/mugi-value-level-parallelism-for-efficient-llms.md)、[Tilus](../papers/asplos-2026/tilus-a-tile-level-gpgpu-programming-language-for-low-precision-computation.md))——低比特推理如今是一等公民的设计目标,不再是事后打补丁。

**训练这一路也开始追上来。** llm-training 只有 8 篇,但每条主轴都踩到了:多模态流水线([DIP](../papers/asplos-2026/dip-efficient-large-multimodal-model-training-with-dynamic-interleaved-pipeline.md))、MoE 再平衡([LAER-MoE](../papers/asplos-2026/laer-moe-load-adaptive-expert-re-layout-for-efficient-mixture-of-experts-training.md))、RL rollout([RhymeRL](../papers/asplos-2026/history-doesnt-repeat-itself-but-rollouts-rhyme-accelerating-reinforcement-learning-with-rhymerl.md)、[Taming the Long-Tail](../papers/asplos-2026/taming-the-long-tail-efficient-reasoning-rl-training-with-adaptive-drafter.md))、亚字节精度([SNIP](../papers/asplos-2026/snip-an-adaptive-mixed-precision-framework-for-subbyte-large-language-model-training.md))、超级芯片 offload([SuperOffload](../papers/asplos-2026/superoffload-unleashing-the-power-of-large-scale-llm-training-on-superchips.md)),再加上基于 SmartNIC 的[非侵入式训练监控](../papers/asplos-2026/fine-grained-and-non-intrusive-llm-training-monitoring-via-microsecond-level-traffic-measurement.md)。对比 2024 年,这一届社区明显已经跨过了「大模型到底能不能训」这一关,真正在乎的是——训练栈下一个瓶颈会卡在哪。

**CXL 不再只是嘴上谈兵。** 10 篇以上直接把 CXL 与解耦内存当成已经在发货的基础设施来对待:有做正式编程模型的([CXL0](../papers/asplos-2026/a-programming-model-for-disaggregated-memory-over-cxl.md)),有做模型检查工具的([CXLMC](../papers/asplos-2026/cxlmc-model-checking-cxl-shared-memory-programs.md)、[vCXLGen](../papers/asplos-2026/vcxlgen-automated-synthesis-and-verification-of-cxl-bridges-for-heterogeneous-architectures.md)),有做 pod 级分配器的([Cxlalloc](../papers/asplos-2026/cxlalloc-safe-and-efficient-memory-allocation-for-a-cxl-pod.md)),有做页粒度迁移的([PIPM](../papers/asplos-2026/pipm-partial-and-incremental-page-migration-for-multi-host-cxl-disaggregated-shared-memory.md)),有做关键度优先分层的([PACT](../papers/asplos-2026/pact-a-criticality-first-design-for-tiered-memory.md)),有做解耦事务的([CREST](../papers/asplos-2026/crest-high-performance-contention-resolution-for-disaggregated-transactions.md)、[CPU-Oblivious](../papers/asplos-2026/cpu-oblivious-offloading-of-failure-atomic-transactions-for-disaggregated-memory.md)),也有做跨 coherence 域性能预测的([Camp](../papers/asplos-2026/performance-predictability-in-heterogeneous-memory.md))。话头已经从「CXL 以后能干嘛」变成了「真实负载跨过一致性边界时到底哪里会先崩」。

**量子计算这次独立成轨。** 11 篇论文铺开了 QEC 电路调度([AlphaSyndrome](../papers/asplos-2026/alphasyndrome-tackling-the-syndrome-measurement-circuit-scheduling-problem-for-qec-codes.md)、[PropHunt](../papers/asplos-2026/prophunt-automated-optimization-of-quantum-syndrome-measurement-circuits.md)、[iSwitch](../papers/asplos-2026/iswitch-qec-on-demand-via-in-situ-encoding-of-bare-qubits-for-ion-trap-architectures.md))、dirty qubit 的重用推理([QBorrow](../papers/asplos-2026/borrowing-dirty-qubits-in-quantum-programs.md))、T-gate 最小化([Reducing T Gates](../papers/asplos-2026/reducing-t-gates-with-unitary-synthesis.md),以及面向 qLDPC 的 [ACQC](../papers/asplos-2026/accelerating-computation-in-quantum-ldpc-code.md))、离子阱架构([Architecting Scalable Trapped Ion](../papers/asplos-2026/architecting-scalable-trapped-ion-quantum-computers-using-surface-codes.md))、分布式 QSWAP([COMPAS](../papers/asplos-2026/compas-a-distributed-multi-party-swap-test-for-parallel-quantum-algorithms.md)),以及模拟量子编译([QTurbo](../papers/asplos-2026/qturbo-a-robust-and-efficient-compiler-for-analog-quantum-simulation.md))。整组工作已经成熟到值得我们这轮专门加一个 `quantum` 标签。

**编译器和 PL 是把整届会议缝起来的线。** 34 篇——也是最大的一类——全落在编译器 / PL / 验证上。张量编译器仍在稳步推进([Trinity](../papers/asplos-2026/trinity-three-dimensional-tensor-program-optimization-via-tile-level-equality-saturation.md)、[RedFuser](../papers/asplos-2026/redfuser-an-automatic-operator-fusion-framework-for-cascaded-reductions-on-ai-accelerators.md)、[Linear Layouts](../papers/asplos-2026/linear-layouts-robust-code-generation-of-efficient-tensor-computation-using-f2.md)、[Insum](../papers/asplos-2026/insum-sparse-gpu-kernels-simplified-and-optimized-with-indirect-einsums.md)、[FuseFlow](../papers/asplos-2026/fuseflow-a-fusion-centric-compilation-framework-for-sparse-deep-learning-on-streaming-dataflow.md)、[Tilus](../papers/asplos-2026/tilus-a-tile-level-gpgpu-programming-language-for-low-precision-computation.md)、[STeP](../papers/asplos-2026/streaming-tensor-programs-a-streaming-abstraction-for-dynamic-parallelism.md));硬件 DSL 也在各自的方向上继续打磨——[Anvil](../papers/asplos-2026/anvil-a-general-purpose-timing-safe-hardware-description-language.md) 的时序契约、[Lilac](../papers/asplos-2026/parameterized-hardware-design-with-latency-abstract-interfaces.md) 的延迟抽象接口、[PDL](../papers/asplos-2026/sequential-specifications-for-precise-hardware-exceptions.md) 的精确异常;验证也第一次伸到了乱序 dataflow([Graphiti](../papers/asplos-2026/graphiti-formally-verified-out-of-order-execution-in-dataflow-circuits.md))与分布式 ML 训练([It Takes Two](../papers/asplos-2026/it-takes-two-to-entangle.md))的地盘;而 LLM 辅助编译则一口气冒出了五种玩法——[LPO](../papers/asplos-2026/lpo-discovering-missed-peephole-optimizations-with-large-language-models.md) 做 peephole、[LOOPRAG](../papers/asplos-2026/looprag-enhancing-loop-transformation-optimization-with-retrieval-augmented-large-language-models.md) 做循环、[PF-LLM](../papers/asplos-2026/pf-llm-large-luanguage-muodel-hinted-hardware-purefuetching.md) 做预取、[Once4All](../papers/asplos-2026/once4all-skeleton-guided-smt-solver-fuzzing-with-llm-synthesized-generators.md) 做 SMT 模糊测试,[CacheMind](../papers/asplos-2026/cachemind-from-miss-rates-to-why-natural-language-trace-grounded-reasoning-for-cache-replacement.md) 则把缓存行为讲成自然语言解释。

**可靠性成了一条横贯主线。** DRAM 防护([RowArmor](../papers/asplos-2026/rowarmor-efficient-and-comprehensive-protection-against-dram-disturbance-attacks.md)、[APT](../papers/asplos-2026/apt-securing-against-dram-read-disturbance-via-adaptive-probabilistic-in-dram-trackers.md))、超大规模下的向量 SDC([SEVI](../papers/asplos-2026/sevi-silent-data-corruption-of-vector-instructions-in-hyper-scale-datacenters.md))、太空辐射([Radshield](../papers/asplos-2026/radshield-software-radiation-protection-for-commodity-hardware-in-space.md))、FHE 加速器的容错([ReliaFHE](../papers/asplos-2026/reliafhe-resilient-design-for-fully-homomorphic-encryption-accelerators.md))、具身 AI 的欠压([CREATE](../papers/asplos-2026/create-cross-layer-resilience-characterization-and-optimization-for-efficient-yet-reliable-embodied-ai-systems.md))、故障注入([PrioriFI](../papers/asplos-2026/priorifi-more-informed-fault-injection-for-edge-neural-networks.md)),再加上[训练集群监控](../papers/asplos-2026/fine-grained-and-non-intrusive-llm-training-monitoring-via-microsecond-level-traffic-measurement.md)——可靠性在这一届不再聚成一个赛道,而是散落在每一个赛道里。

**FHE 与 TEE 都在往生产线走。** 6 篇 FHE 加速器论文([Cheddar](../papers/asplos-2026/cheddar-a-swift-fully-homomorphic-encryption-library-designed-for-gpu-architectures.md)、[Falcon](../papers/asplos-2026/falcon-algorithm-hardware-co-design-for-efficient-fully-homomorphic-encryption-accelerator.md)、[Maverick](../papers/asplos-2026/maverick-rethinking-tfhe-bootstrapping-on-gpus-via-algorithm-hardware-co-design.md)、[ReliaFHE](../papers/asplos-2026/reliafhe-resilient-design-for-fully-homomorphic-encryption-accelerators.md)、[CHEHAB RL](../papers/asplos-2026/chehab-rl-learning-to-optimize-fully-homomorphic-encryption-computations.md),以及一个面向 [GPU 的 FHE 框架](../papers/asplos-2026/a-framework-for-developing-and-optimizing-fully-homomorphic-encryption-programs-on-gpus.md))摆在一起,传递的信号很清楚——社区相信 FHE 很快就能迈过吞吐与延迟的门槛。TEE 一侧同样热闹:[TeeM3](../papers/asplos-2026/teem3-core-independent-and-cooperating-trusted-execution-environments.md) 把隔离从 CPU mode 里抽出来,[Trust-V](../papers/asplos-2026/trust-v-toward-secure-and-reliable-storage-for-trusted-execution-environments.md) 把 TEE 的存储路径加固,[WorksetEnclave](../papers/asplos-2026/worksetenclave-towards-optimizing-cold-starts-in-confidential-serverless-with-workset-based-enclave-restore.md) 盯上了机密 Serverless 的冷启动;还有一项[验证工作](../papers/asplos-2026/detecting-inconsistencies-in-arm-ccas-formally-verified-specification.md)在 Arm CCA 的规范里挑出了 35 处已确认的不一致。

## 值得关注的趋势

- **到处在「拆」。** GPU 显存 offload、CXL pod、prefill 与 decode 分离、起草和验证跨 FPGA+GPU、SmartNIC 接管 I/O——这届的年度关键词大概就是「split it」。
- **推测无处不在。** 解码([SwiftSpec](../papers/asplos-2026/swiftspec-disaggregated-speculative-decoding-and-fused-kernels-for-low-latency-llm-inference.md)、[DFVG](../papers/asplos-2026/dfvg-a-heterogeneous-architecture-for-speculative-decoding-with-draft-on-fpga-and-verify-on-gpu.md))、预取([EARTH](../papers/asplos-2026/earth-an-efficient-moe-accelerator-with-entropy-aware-speculative-prefetch-and-result-reuse.md))、Protobuf 解析([SpecProto](../papers/asplos-2026/specproto-a-parallelizing-compiler-for-speculative-decoding-of-large-protocol-buffers-data.md))、分支扩展([FastTTS](../papers/asplos-2026/fasttts-accelerating-test-time-scaling-for-edge-llm-reasoning.md))——「speculate and recover」已经变成默认写法。
- **稀疏性正式进入一等公民行列。** 比特级([BitRed](../papers/asplos-2026/bitred-taming-non-uniform-bit-level-sparsity-with-a-programmable-risc-v-isa-for-dnn-acceleration.md))、动态([Dynamic Sparsity in DiT](../papers/asplos-2026/dynamic-sparsity-in-large-scale-video-dit-training.md))、流式([FuseFlow](../papers/asplos-2026/fuseflow-a-fusion-centric-compilation-framework-for-sparse-deep-learning-on-streaming-dataflow.md))、编译器自动发掘([Insum](../papers/asplos-2026/insum-sparse-gpu-kernels-simplified-and-optimized-with-indirect-einsums.md) 的 indirect einsum)、稀疏 SpMM([Slaws](../papers/asplos-2026/slaws-spatial-locality-analysis-and-workload-orchestration-for-sparse-matrix-multiplication.md))——稀疏早就不是边角料。
- **能耗也被挂到 20 篇论文上。** 功耗、碳排、寿命如今和吞吐、延迟并列,成了一根设计坐标轴;而且这件事不止发生在边缘端([FlexiFlow](../papers/asplos-2026/lifetime-aware-design-for-item-level-intelligence-at-the-extreme-edge.md)、[TierX](../papers/asplos-2026/tierx-a-simulation-framework-for-multi-tier-bci-system-design-evaluation-and-exploration.md)),数据中心加速器也在算同样的账。

## 必读推荐

- **[Shift Parallelism](../papers/asplos-2026/shift-parallelism-low-latency-high-throughput-llm-inference-for-dynamic-workloads.md)**——保住 KV-cache 布局,让 LLM 服务在运行时无缝地在序列并行和张量并行之间切换;少见的「越简单越对」式结论。
- **[A Programming Model for Disaggregated Memory over CXL](../papers/asplos-2026/a-programming-model-for-disaggregated-memory-over-cxl.md)**——CXL0 给多主机 CXL 立下了精确且 propagation-aware 的语义,后面的研究大概率都会拿它当基石。
- **[Streaming Tensor Programs (STeP)](../papers/asplos-2026/streaming-tensor-programs-a-streaming-abstraction-for-dynamic-parallelism.md)**——为 spatial dataflow 硬件上的动态形状和控制流给出了干净的抽象,动态切片和专家时分复用终于不必再靠手工调优。
- **[Compositional AI Beyond LLMs](../papers/asplos-2026/compositional-ai-beyond-llms-system-implications-of-neuro-symbolic-probabilistic-architectures.md)**——从系统视角拆解神经-符号-概率负载,把当下 AI 系统栈没有照顾到的地方一条条点了出来。
- **[SuperOffload](../papers/asplos-2026/superoffload-unleashing-the-power-of-large-scale-llm-training-on-superchips.md)**——第一个真正顺着超级芯片一致 CPU↔GPU 内存去做、而不是硬跟 PCIe 对着干的大模型训练 offload 方案。

## 数据

- 已总结论文:**152 / 152**
- 类别数:**8**
- 最大类别:compilers-languages-verification 与 hardware-and-infrastructure(各 34 篇)
- 最小类别:llm-training(8 篇)
- 使用标签数:33(本轮新增 `quantum`)
