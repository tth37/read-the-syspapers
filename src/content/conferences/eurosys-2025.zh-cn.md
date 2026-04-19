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
    title: "ML 与 LLM 系统"
    description: "LLM 推理与训练、MoE、稀疏化、深度学习 GPU 调度以及 DL 编译器——program 里 AI 占比最大的一条主线,覆盖了近四分之一的录用论文。"
  - id: graph-and-data-systems
    title: "图与数据系统"
    description: "图处理、GNN、超图模式挖掘、学习索引、基于共享日志的流处理、区块链交易执行,以及把 Python 数据科学脚本编译到大数据引擎的工作。"
  - id: networking-and-dataplane
    title: "网络与数据平面"
    description: "拥塞控制、虚拟交换机、可编程交换机与 SmartNIC、内核旁路 I/O,以及网络内验证。把状态从主机下沉到交换机/NIC 的那一层论文。"
  - id: storage-memory-and-filesystems
    title: "存储、内存与文件系统"
    description: "SSD、Flash 缓存、分层内存、分离式内存索引、持久化内存文件系统,以及针对云块存储行为的生产环境实测研究。"
  - id: os-kernel-and-runtimes
    title: "操作系统、内核与运行时"
    description: "内核存储栈、eBPF 扩展、WebAssembly 沙箱、Hypervisor 内存管理、vCPU 抽象,以及内核可视化/可观测性工具。"
  - id: security-and-isolation
    title: "安全、隔离与机密计算"
    description: "TEE 辅助的 BFT 共识、机密虚机沙箱、Enclave I/O、安全容器软硬件协同、隐私预算调度,以及多机器人信任边界。"
  - id: cloud-scheduling-and-serverless
    title: "云调度与 Serverless"
    description: "集群调度、流算子放置、Serverless 冷启动实测、虚机再调度,以及跨供应商的工作流基准测试。"
  - id: reliability-and-formal-methods
    title: "可靠性与形式化方法"
    description: "分布式系统模型检查、由运行时 bug 触发的静态分析扩展、CRDT 理论、可验证的软硬件驱动合成,以及 SQL 函数 bug 的元态 Oracle。"
---

_EuroSys '25_ 在鹿特丹一共收了 **85 篇论文**,单轨 program 读起来就是一张「系统圈今年真正在投入精力的地图」。倾斜相当明显:光 LLM/DL 系统一条赛道就占了 23 篇,网络另外 13 篇则被可编程交换机与 SmartNIC 主导。不过今年更安静的一条主线其实在 memory hierarchy——从 KV cache、分层 DRAM 到持久化内存文件系统,几乎被系统性地改写了一遍。与此同时,经典的 EuroSys 广度依旧在场:内核扩展、BFT 共识、CRDT、操作级交易调度,甚至多机器人信任边界都还在房间里。

## 主题

- **LLM 推理已经变成 memory hierarchy 问题,不再是调度问题。**
  [CacheBlend](../papers/eurosys-2025/cacheblend-fast-large-language-model-serving-for-rag-with-cached-knowledge-fusion.md)、
  [HCache](../papers/eurosys-2025/fast-state-restoration-in-llm-serving-with-hcache.md)、
  [Pensieve](../papers/eurosys-2025/stateful-large-language-model-serving-with-pensieve.md)、
  [DeltaZip](../papers/eurosys-2025/deltazip-efficient-serving-of-multiple-full-model-tuned-llms.md)、
  [SkyServe](../papers/eurosys-2025/skyserve-serving-ai-models-across-regions-and-clouds-with-spot-instances.md)、
  [T-MAC](../papers/eurosys-2025/t-mac-cpu-renaissance-via-table-lookup-for-low-bit-llm-deployment-on-edge.md)
  都在围绕「状态放在哪里」重写 serving 路径——KV cache、隐藏状态、按位打包的权重、跨区副本,无一例外。其中真正把主要篇幅花在请求调度上的,只有一篇;其余讲的都是布局与复用。
- **资源受限下的分布式 LLM 训练。**
  [HybridFlow](../papers/eurosys-2025/hybridflow-a-flexible-and-efficient-rlhf-framework.md)
  把 RLHF 拆成「模型间数据流」与「模型内执行」两层;
  [Mist](../papers/eurosys-2025/mist-efficient-distributed-training-of-large-language-models-via-memory-parallelism-co.md)
  在显存预算下协同调 DP/TP/PP/ZeRO/Offload;
  [MEPipe](../papers/eurosys-2025/mepipe-democratizing-llm-training-with-memory-efficient-slice-level-pipeline-scheduling.md)
  用切片级流水线让 24 GB 的 RTX 4090 也能训 LLM;
  [FlowCheck](../papers/eurosys-2025/flowcheck-decoupling-checkpointing-and-training-of-large-scale-models.md)
  在交换机上镜像 allreduce 流量以带外重建梯度;
  [JABAS](../papers/eurosys-2025/jabas-joint-adaptive-batching-and-automatic-scaling-for-dnn-training-on-heterogeneous-gpus.md)
  则保证异构 GPU 上的自适应 batching 在统计意义下仍然正确。大家都默认「扩不动更多机器」,真正的杠杆是细粒度协同调优。
- **从 OS 提示到分离式内存,整条 memory hierarchy 被重新思考。**
  [Chrono](../papers/eurosys-2025/chrono-meticulous-hotness-measurement-and-flexible-page-migration-for-memory-tiering.md)、
  [PET](../papers/eurosys-2025/pet-proactive-demotion-for-efficient-tiered-memory-management.md)
  与
  [Pre-Stores](../papers/eurosys-2025/pre-stores-proactive-software-guided-movement-of-data-down-the-memory-hierarchy.md)
  用软件提示驱动分层内存的降级;
  [HyperAlloc](../papers/eurosys-2025/hyperalloc-efficient-vm-memory-de-inflation-via-hypervisor-shared-page-frame-allocators.md)
  干脆让 hypervisor 直接改写 guest allocator;
  [Adios](../papers/eurosys-2025/adios-to-busy-waiting-for-microsecond-scale-memory-disaggregation.md)
  用让出式调度取代忙等的 page fault;
  [SLOT](../papers/eurosys-2025/overcoming-the-last-mile-between-log-structured-file-systems-and-persistent-memory-via.md)
  让 log-structured PM 的回收终于跑得动;
  [DEFT](../papers/eurosys-2025/deft-a-scalable-tree-index-for-disaggregated-memory.md)
  则围绕 RDMA 读模式重做 DM 树索引。
- **可编程网络被当成一等基础设施。**
  [Occamy](../papers/eurosys-2025/occamy-a-preemptive-buffer-management-for-on-chip-shared-memory-switches.md)
  把交换机的 buffer 管理做成可抢占;
  [Phantom](../papers/eurosys-2025/phantom-virtualizing-switch-register-resources-for-accurate-sketch-based-network.md)
  在交换机寄存器上虚拟化 sketch;
  [Marlin](../papers/eurosys-2025/marlin-enabling-high-throughput-congestion-control-testing-in-large-scale-networks.md)
  把 FPGA NIC 与可编程交换机配对,用于 CC 测试;
  [BVS](../papers/eurosys-2025/byte-vswitch-a-high-performance-virtual-switch-for-cloud-networking.md)
  用 VPC 专用流水线替换通用 OVS;
  [Pegasus](../papers/eurosys-2025/pegasus-transparent-and-unified-kernel-bypass-networking-for-fast-local-and-remote.md)
  把本地与远程 IPC 的内核旁路统一掉;
  [SuperFE](../papers/eurosys-2025/superfe-a-scalable-and-flexible-feature-extractor-for-ml-based-traffic-analysis.md)
  则把 ML 特征策略编译到交换机+SmartNIC 协同执行。其实共同点很清楚——通用栈正在被垂直化流水线替代。
- **信任边界在原有平台上加固,而不是另起炉灶。**
  [Erebor](../papers/eurosys-2025/erebor-a-drop-in-sandbox-solution-for-private-data-processing-in-untrusted-confidential.md)
  把机密虚机切成按客户隔离的沙箱;
  [CKI](../papers/eurosys-2025/a-hardware-software-co-design-for-efficient-secure-containers.md)
  用 PKS + 少量 ISA 调整造出「容器内核特权级」;
  [RAKIS](../papers/eurosys-2025/rakis-secure-fast-i-o-primitives-across-trust-boundaries-on-intel-sgx.md)
  把 XDP / io_uring 封装成 enclave 内的验证后快路径;
  [Achilles](../papers/eurosys-2025/achilles-efficient-tee-assisted-bft-consensus-via-rollback-resilient-recovery.md)
  与
  [Ladon](../papers/eurosys-2025/ladon-high-performance-multi-bft-consensus-via-dynamic-global-ordering.md)
  把 TEE 辅助 BFT 推进到新的共识形态;
  [DPack](../papers/eurosys-2025/dpack-efficiency-oriented-privacy-budget-scheduling.md)
  则把差分隐私预算当成有限可调度资源。换句话说,没人试图从零造新平台——每篇都是在现有云原语之上加装每客户/每租户的隔离。

## 值得关注的趋势

- **先乐观推测,再局部重算。**
  [CacheBlend](../papers/eurosys-2025/cacheblend-fast-large-language-model-serving-for-rag-with-cached-knowledge-fusion.md)
  复用 KV 之后只重算高影响 token;
  [SpInfer](../papers/eurosys-2025/spinfer-leveraging-low-level-sparsity-for-efficient-large-language-model-inference-on-gpus.md)
  对非结构化稀疏激活做选择性稠密化;
  [ParallelEVM](../papers/eurosys-2025/parallelevm-operation-level-concurrent-transaction-execution-for-evm-compatible.md)
  以 SSA 形式记录 EVM 执行,只重放冲突相关指令;
  [BESA](../papers/eurosys-2025/besa-extending-bugs-triggered-by-runtime-testing-via-static-analysis.md)
  则从单个运行时触发的空指针出发,反哺调用串敏感的静态分析。其实是同一种套路——先默认可复用,再把修正动作局部化。
- **把状态下沉到交换机、NIC 或持久化内存。**
  [Phantom](../papers/eurosys-2025/phantom-virtualizing-switch-register-resources-for-accurate-sketch-based-network.md)
  把 sketch 塞进交换机的回环通道;
  [Marlin](../papers/eurosys-2025/marlin-enabling-high-throughput-congestion-control-testing-in-large-scale-networks.md)
  用 FPGA NIC + 可编程交换机注入 CC 测试流量;
  [Atlas](../papers/eurosys-2025/atlas-towards-real-time-verification-in-large-scale-networks-via-a-native-distributed.md)
  把数据平面验证做成三层分布式服务,跑在网络本身上;
  [FlowCheck](../papers/eurosys-2025/flowcheck-decoupling-checkpointing-and-training-of-large-scale-models.md)
  在交换机镜像 allreduce 以带外重建梯度。交换机早就不只是一段线了。
- **软件提示驱动内存迁移。**
  [Pre-Stores](../papers/eurosys-2025/pre-stores-proactive-software-guided-movement-of-data-down-the-memory-hierarchy.md)
  把脏数据下移当成软件 hint;
  [PET](../papers/eurosys-2025/pet-proactive-demotion-for-efficient-tiered-memory-management.md)
  从应用信号出发分阶段降级匿名 mmap 区域;
  [Chrono](../papers/eurosys-2025/chrono-meticulous-hotness-measurement-and-flexible-page-migration-for-memory-tiering.md)
  用 timer 捕获空闲时间而非粗糙计数器;
  [HyperAlloc](../papers/eurosys-2025/hyperalloc-efficient-vm-memory-de-inflation-via-hypervisor-shared-page-frame-allocators.md)
  则让 hypervisor 直接改写 guest allocator。整条栈上,运行时 hint 在持续压过启发式 profiling。
- **把生产环境测量本身作为贡献。**
  [Hey Hey My My](../papers/eurosys-2025/hey-hey-my-my-skewness-is-here-to-stay-challenges-and-opportunities-in-cloud-block-store.md)
  调研了 6 万台 VM 的块存储倾斜;
  [Serverless Cold Starts and Where to Find Them](../papers/eurosys-2025/serverless-cold-starts-and-where-to-find-them.md)
  跨 5 个生产区域跟踪 Serverless 函数冷启动;
  [DepSurf](../papers/eurosys-2025/revealing-the-unstable-foundations-of-ebpf-based-kernel-extensions.md)
  度量 eBPF 内核接口在不同 Linux 版本间的漂移;
  [Themis](../papers/eurosys-2025/themis-finding-imbalance-failures-in-distributed-file-systems-via-a-load-variance-model.md)
  则用序关系模糊测试暴露 DFS 的失衡失败。不是用测量当 motivation,而是把测量本身作为最终贡献。

## 必读推荐

- **[HybridFlow](../papers/eurosys-2025/hybridflow-a-flexible-and-efficient-rlhf-framework.md)** —— 把 RLHF 拆成「模型间编排」与「模型内执行」两层,让 PPO/DPO/RLAIF 等变体共享同一个高效运行时;今年 program 里最可能成为社区基础设施的那一篇。
- **[CacheBlend](../papers/eurosys-2025/cacheblend-fast-large-language-model-serving-for-rag-with-cached-knowledge-fusion.md)** —— 把多段 RAG 复用的 KV cache 融合起来,只对跨注意力关键的 token 做重算,TTFT 2.2–3.3× 加速,而质量几乎不掉;做 RAG serving 的人会直接把它当默认方案。
- **[T-MAC](../papers/eurosys-2025/t-mac-cpu-renaissance-via-table-lookup-for-low-bit-llm-deployment-on-edge.md)** —— 把 W1-W4 的 LLM matmul 重写成按位模式的查表,让不带 GPU 的 CPU 推理比 llama.cpp 快 2–8×;不是调参,是新机制。
- **[Remix](../papers/eurosys-2025/multi-grained-specifications-for-distributed-system-model-checking-and-verification.md)** —— 用阶段化混合粒度 TLA+ 给 ZooKeeper 建模,真查出 6 个生产 bug;为把模型检查落地到大规模真实代码库给出了一条可复现的配方——不再只是教科书协议。
- **[Hey Hey My My](../papers/eurosys-2025/hey-hey-my-my-skewness-is-here-to-stay-challenges-and-opportunities-in-cloud-block-store.md)** —— 一项 6 万台 VM 规模的云块存储倾斜研究,结论是「倾斜是结构性的,不是长尾问题」;它会改变本场地之后每一篇云存储论文的先验。

## 数据概览

- 共总结 **85 篇论文**(覆盖 100% 录用 program)。
- 分类分布:
  - ml-and-llm-systems: 23 篇 (27%)
  - networking-and-dataplane: 13 篇 (15%)
  - storage-memory-and-filesystems: 13 篇 (15%)
  - graph-and-data-systems: 9 篇 (11%)
  - os-kernel-and-runtimes: 9 篇 (11%)
  - security-and-isolation: 7 篇 (8%)
  - cloud-scheduling-and-serverless: 6 篇 (7%)
  - reliability-and-formal-methods: 5 篇 (6%)
- 标签集中度:`scheduling`、`gpu`、`ml-systems`、`llm-inference`、`datacenter`、`networking`、`kernel`、`memory`、`storage` 每个都出现在 10 篇以上;本场没有新增标签。
- 工业界合作者高度集中在中国云厂商与 LLM 基础设施公司——Alibaba、ByteDance、Huawei、Tencent、Microsoft Research 每家至少 ≥2 篇,且至少有一家头部公有云块存储与一家 Serverless 平台贡献了生产环境 trace。
