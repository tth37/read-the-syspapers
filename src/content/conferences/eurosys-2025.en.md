---
venue: EuroSys
year: 2025
title: "EuroSys '25"
location: "Rotterdam, Netherlands"
dates: "2025-03-30 to 2025-04-03"
url: "https://2025.eurosys.org/"
paper_count_expected: 85
overview_status: complete
written_by: "Claude Opus 4.7 (Claude Code)"
summary_date: 2026-04-19
categories:
  - id: ml-and-llm-systems
    title: "ML and LLM systems"
    description: "LLM serving and training, MoE, sparsity, GPU scheduling for deep learning, and DL compilers — the AI-heavy track of the program, covering roughly a quarter of the accepted papers."
  - id: graph-and-data-systems
    title: "Graph and data systems"
    description: "Graph processing, GNN, hypergraph mining, learned indexes, streaming on shared logs, blockchain execution, and Python-to-big-data compilation. The analytics-adjacent track."
  - id: networking-and-dataplane
    title: "Networking and data plane"
    description: "Congestion control, virtual switches, programmable switches and SmartNICs, kernel-bypass I/O, and in-network verification. Stack-layer papers that push state out to switches and NICs."
  - id: storage-memory-and-filesystems
    title: "Storage, memory, and filesystems"
    description: "SSDs, flash caches, tiered memory, disaggregated memory indexes, persistent-memory filesystems, and production studies of cloud block-store behavior."
  - id: os-kernel-and-runtimes
    title: "OS, kernel, and runtimes"
    description: "Kernel storage stacks, eBPF extensions, WebAssembly sandboxes, hypervisor memory management, vCPU abstractions, and kernel-visibility tooling."
  - id: security-and-isolation
    title: "Security, isolation, and confidential computing"
    description: "TEE-assisted BFT consensus, confidential-VM sandboxes, enclave I/O, secure-container software/hardware co-design, privacy-budget scheduling, and multi-robot trust boundaries."
  - id: cloud-scheduling-and-serverless
    title: "Cloud scheduling and serverless"
    description: "Cluster scheduling, stream-operator placement, serverless cold-start measurement studies, VM rescheduling, and cross-provider workflow benchmarking."
  - id: reliability-and-formal-methods
    title: "Reliability and formal methods"
    description: "Model-checking distributed systems, fuzzing bugs triggered at runtime, CRDT theory, verified hybrid hardware/software drivers, and SQL-function bug oracles."
---

_EuroSys '25_ brought **85 papers** to Rotterdam, a single-track program that reads as
a map of where the systems community is actually spending its time. The skew is stark:
the LLM and DL-systems track alone is 23 papers, and another 13 on networking are
dominated by programmable switches and SmartNICs — but the year's quieter story is how
thoroughly the memory hierarchy is being rewritten, from KV caches through tiered DRAM
down to persistent-memory filesystems. Classical EuroSys breadth still shows up: kernel
extensions, BFT consensus, CRDTs, operator-level transaction scheduling, and even
robot-level trust boundaries are all in the room.

## Themes

- **LLM serving has become a memory-hierarchy problem, not a scheduling one.** The
  serving cluster — [CacheBlend](../papers/eurosys-2025/cacheblend-fast-large-language-model-serving-for-rag-with-cached-knowledge-fusion.md),
  [HCache](../papers/eurosys-2025/fast-state-restoration-in-llm-serving-with-hcache.md),
  [Pensieve](../papers/eurosys-2025/stateful-large-language-model-serving-with-pensieve.md),
  [DeltaZip](../papers/eurosys-2025/deltazip-efficient-serving-of-multiple-full-model-tuned-llms.md),
  [SkyServe](../papers/eurosys-2025/skyserve-serving-ai-models-across-regions-and-clouds-with-spot-instances.md),
  [T-MAC](../papers/eurosys-2025/t-mac-cpu-renaissance-via-table-lookup-for-low-bit-llm-deployment-on-edge.md) —
  rewrites the serving path around where state lives (KV cache, hidden states,
  bit-packed weights, cross-region replicas). Only one of these papers spends most of
  its pages on request scheduling; the rest are about layout and reuse.
- **Distributed LLM training under resource pressure.** [HybridFlow](../papers/eurosys-2025/hybridflow-a-flexible-and-efficient-rlhf-framework.md)
  factors RLHF into inter-model dataflow plus intra-model execution;
  [Mist](../papers/eurosys-2025/mist-efficient-distributed-training-of-large-language-models-via-memory-parallelism-co.md)
  co-tunes DP/TP/PP/ZeRO/offloading against a memory budget;
  [MEPipe](../papers/eurosys-2025/mepipe-democratizing-llm-training-with-memory-efficient-slice-level-pipeline-scheduling.md)
  trains LLMs on 24 GB RTX 4090s via slice-level pipelines;
  [FlowCheck](../papers/eurosys-2025/flowcheck-decoupling-checkpointing-and-training-of-large-scale-models.md)
  mirrors all-reduce traffic at the switch to recover gradients out-of-band;
  [JABAS](../papers/eurosys-2025/jabas-joint-adaptive-batching-and-automatic-scaling-for-dnn-training-on-heterogeneous-gpus.md)
  keeps adaptive batching statistically sound across heterogeneous GPUs. Scaling out is
  assumed; the lever is fine-grained co-tuning.
- **Rethinking the memory hierarchy from OS hints to disaggregation.**
  [Chrono](../papers/eurosys-2025/chrono-meticulous-hotness-measurement-and-flexible-page-migration-for-memory-tiering.md),
  [PET](../papers/eurosys-2025/pet-proactive-demotion-for-efficient-tiered-memory-management.md),
  and [Pre-Stores](../papers/eurosys-2025/pre-stores-proactive-software-guided-movement-of-data-down-the-memory-hierarchy.md)
  drive tiered-memory demotion from software hints;
  [HyperAlloc](../papers/eurosys-2025/hyperalloc-efficient-vm-memory-de-inflation-via-hypervisor-shared-page-frame-allocators.md)
  lets the hypervisor rewrite the guest allocator;
  [Adios](../papers/eurosys-2025/adios-to-busy-waiting-for-microsecond-scale-memory-disaggregation.md)
  replaces busy-waiting page faults with yield-based scheduling;
  [SLOT](../papers/eurosys-2025/overcoming-the-last-mile-between-log-structured-file-systems-and-persistent-memory-via.md)
  makes log-structured PM reclaim viable;
  [DEFT](../papers/eurosys-2025/deft-a-scalable-tree-index-for-disaggregated-memory.md)
  rebuilds DM tree indexes around RDMA read patterns.
- **Programmable networks as first-class infrastructure.**
  [Occamy](../papers/eurosys-2025/occamy-a-preemptive-buffer-management-for-on-chip-shared-memory-switches.md)
  makes switch buffer management preemptive;
  [Phantom](../papers/eurosys-2025/phantom-virtualizing-switch-register-resources-for-accurate-sketch-based-network.md)
  virtualizes switch registers for sketches;
  [Marlin](../papers/eurosys-2025/marlin-enabling-high-throughput-congestion-control-testing-in-large-scale-networks.md)
  pairs an FPGA NIC with a programmable switch for CC testing;
  [BVS](../papers/eurosys-2025/byte-vswitch-a-high-performance-virtual-switch-for-cloud-networking.md)
  replaces generic OVS with a VPC-specific pipeline;
  [Pegasus](../papers/eurosys-2025/pegasus-transparent-and-unified-kernel-bypass-networking-for-fast-local-and-remote.md)
  unifies kernel-bypass across local and remote IPC;
  [SuperFE](../papers/eurosys-2025/superfe-a-scalable-and-flexible-feature-extractor-for-ml-based-traffic-analysis.md)
  compiles ML-feature policies to switch + SmartNIC. Generic stacks are being replaced
  by verticalized pipelines.
- **Trust-boundary hardening without replatforming.**
  [Erebor](../papers/eurosys-2025/erebor-a-drop-in-sandbox-solution-for-private-data-processing-in-untrusted-confidential.md)
  turns a confidential VM into per-client sandboxes;
  [CKI](../papers/eurosys-2025/a-hardware-software-co-design-for-efficient-secure-containers.md)
  adds a container-kernel privilege level with PKS + small ISA tweaks;
  [RAKIS](../papers/eurosys-2025/rakis-secure-fast-i-o-primitives-across-trust-boundaries-on-intel-sgx.md)
  wraps XDP / io_uring in validated enclave fast paths;
  [Achilles](../papers/eurosys-2025/achilles-efficient-tee-assisted-bft-consensus-via-rollback-resilient-recovery.md)
  and [Ladon](../papers/eurosys-2025/ladon-high-performance-multi-bft-consensus-via-dynamic-global-ordering.md)
  push TEE-assisted BFT into new consensus regimes;
  [DPack](../papers/eurosys-2025/dpack-efficiency-oriented-privacy-budget-scheduling.md)
  treats the differential-privacy budget as a finite schedulable resource. Rather than
  invent new platforms, each paper retrofits per-client isolation onto existing cloud
  primitives.

## Notable trends

- **Speculate optimistically, then selectively recompute.**
  [CacheBlend](../papers/eurosys-2025/cacheblend-fast-large-language-model-serving-for-rag-with-cached-knowledge-fusion.md)
  recomputes only high-impact tokens after fusing reused KV;
  [SpInfer](../papers/eurosys-2025/spinfer-leveraging-low-level-sparsity-for-efficient-large-language-model-inference-on-gpus.md)
  selectively densifies unstructured-sparse activations;
  [ParallelEVM](../papers/eurosys-2025/parallelevm-operation-level-concurrent-transaction-execution-for-evm-compatible.md)
  redoes only the conflict-dependent instructions of an SSA-logged EVM trace;
  [BESA](../papers/eurosys-2025/besa-extending-bugs-triggered-by-runtime-testing-via-static-analysis.md)
  seeds a call-string-sensitive static analysis from one runtime-triggered null deref.
  The shared move: assume optimistic reuse, localize the correction.
- **Delegate state to the switch, the NIC, or persistent memory.**
  [Phantom](../papers/eurosys-2025/phantom-virtualizing-switch-register-resources-for-accurate-sketch-based-network.md)
  puts sketches in switch recirculation lanes;
  [Marlin](../papers/eurosys-2025/marlin-enabling-high-throughput-congestion-control-testing-in-large-scale-networks.md)
  pairs FPGA NICs with programmable switches to inject CC test traffic;
  [Atlas](../papers/eurosys-2025/atlas-towards-real-time-verification-in-large-scale-networks-via-a-native-distributed.md)
  runs data-plane verification as a three-tier distributed service across the fabric;
  [FlowCheck](../papers/eurosys-2025/flowcheck-decoupling-checkpointing-and-training-of-large-scale-models.md)
  mirrors allreduce at the switch to reconstruct gradients out of band. The switch is
  no longer just a wire.
- **Software hints drive memory movement.**
  [Pre-Stores](../papers/eurosys-2025/pre-stores-proactive-software-guided-movement-of-data-down-the-memory-hierarchy.md)
  treats dirty-data demotion as a software hint;
  [PET](../papers/eurosys-2025/pet-proactive-demotion-for-efficient-tiered-memory-management.md)
  phases anonymous-mmap demotion from application signals;
  [Chrono](../papers/eurosys-2025/chrono-meticulous-hotness-measurement-and-flexible-page-migration-for-memory-tiering.md)
  captures idle time via timer hints instead of coarse counters;
  [HyperAlloc](../papers/eurosys-2025/hyperalloc-efficient-vm-memory-de-inflation-via-hypervisor-shared-page-frame-allocators.md)
  lets the hypervisor write the guest allocator directly. Across the stack, runtime
  hints beat heuristic profiling.
- **Production-scale measurement as the contribution.**
  [Hey Hey My My](../papers/eurosys-2025/hey-hey-my-my-skewness-is-here-to-stay-challenges-and-opportunities-in-cloud-block-store.md)
  studies 60,000 VMs of block-store skew;
  [Serverless Cold Starts and Where to Find Them](../papers/eurosys-2025/serverless-cold-starts-and-where-to-find-them.md)
  traces five regions of production functions;
  [DepSurf](../papers/eurosys-2025/revealing-the-unstable-foundations-of-ebpf-based-kernel-extensions.md)
  measures eBPF kernel-interface drift across Linux versions;
  [Themis](../papers/eurosys-2025/themis-finding-imbalance-failures-in-distributed-file-systems-via-a-load-variance-model.md)
  surfaces DFS imbalance via ordering-relation fuzzing. Each paper's contribution is
  the measurement itself, not a system built on top of it.

## Must-read picks

- **[HybridFlow](../papers/eurosys-2025/hybridflow-a-flexible-and-efficient-rlhf-framework.md)** — Factors RLHF into inter-model orchestration and intra-model execution so PPO/DPO/RLAIF variants can share one efficient runtime; the most likely artifact from this year's program to become community infrastructure.
- **[CacheBlend](../papers/eurosys-2025/cacheblend-fast-large-language-model-serving-for-rag-with-cached-knowledge-fusion.md)** — Fuses KV caches from multiple reused RAG chunks and recomputes only cross-attention-critical tokens, cutting TTFT 2.2–3.3× at negligible quality cost; already the obvious default for anyone serving RAG.
- **[T-MAC](../papers/eurosys-2025/t-mac-cpu-renaissance-via-table-lookup-for-low-bit-llm-deployment-on-edge.md)** — Rewrites W1-W4 LLM matmul as bit-pattern table lookup, making edge-CPU inference 2–8× faster than llama.cpp without a GPU — a genuinely new mechanism, not a tuning paper.
- **[Remix](../papers/eurosys-2025/multi-grained-specifications-for-distributed-system-model-checking-and-verification.md)** — Phase-wise mixed-grained TLA+ model of ZooKeeper finds six production bugs; a reproducible recipe for grounding model-checking in large real codebases, not just textbook protocols.
- **[Hey Hey My My](../papers/eurosys-2025/hey-hey-my-my-skewness-is-here-to-stay-challenges-and-opportunities-in-cloud-block-store.md)** — A 60,000-VM EBS-scale study showing cloud block-store skew is structural, not tail; it changes the priors for every future cloud-storage paper in this venue.

## Stats

- **85 papers** summarized (100% of the accepted program).
- Category breakdown:
  - ml-and-llm-systems: 23 (27%)
  - networking-and-dataplane: 13 (15%)
  - storage-memory-and-filesystems: 13 (15%)
  - graph-and-data-systems: 9 (11%)
  - os-kernel-and-runtimes: 9 (11%)
  - security-and-isolation: 7 (8%)
  - cloud-scheduling-and-serverless: 6 (7%)
  - reliability-and-formal-methods: 5 (6%)
- Tag concentration: `scheduling`, `gpu`, `ml-systems`, `llm-inference`, `datacenter`, `networking`, `kernel`, `memory`, and `storage` each appear on ≥10 papers; no new tag was minted for this venue.
- Industry co-authorship is heavy on Chinese hyperscalers and LLM-infra companies — Alibaba, ByteDance, Huawei, Tencent, and Microsoft Research each appear on ≥2 papers — with production traces contributed by at least one major public-cloud block-store and one serverless platform.
