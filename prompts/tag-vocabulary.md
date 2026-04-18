# Tag vocabulary

This is the canonical list of tags. Use 3–6 per paper. Tags are **always English
kebab-case** and are identical in a paper's `.en.md` and `.zh-cn.md` frontmatter — do not
translate them. Tag pages (`/<lang>/tags/<tag>`) group papers across venues and languages,
so a translated tag would silently split the group in two.

If no tag fits a genuinely-new topic, flag it in the paper's `My Notes` section instead of
inventing one silently.

Each tag's one-line scope rule is normative — when two tags could plausibly fit, pick the
one whose scope rule fits more tightly.

## Core systems

- **`scheduling`** — CPU/task scheduling, load balancing, kernel-level or userspace.
- **`kernel`** — OS kernel internals, syscall path, in-kernel subsystems. Kernel-bypass
  work is tagged by the bypass mechanism (`rdma`, `ebpf`, `networking`).
- **`virtualization`** — hypervisors, VMs, microVMs, nested virtualization.
- **`isolation`** — software-level sandboxing (containers, namespaces, seccomp, WASM
  sandboxes). Hardware-rooted isolation goes in `confidential-computing`.
- **`memory`** — volatile memory management: paging, swap, NUMA, tiering, far memory.
  NVM/PM goes in `persistent-memory`; CXL memory pools go in `disaggregation`.
- **`datacenter`** — cluster-level resource management, microservices infra, orchestration.
- **`serverless`** — FaaS platforms, cold-start, function scheduling.
- **`ebpf`** — eBPF-based systems work: in-kernel tracing fast paths, network dataplane,
  policy enforcement via eBPF programs.
- **`disaggregation`** — resource disaggregation: CXL memory pools, disaggregated compute
  or storage, far-memory architectures that cross the node boundary.

## Storage & data

- **`storage`** — block/object storage, durability, replication below DB layer.
- **`filesystems`** — local or distributed file systems.
- **`persistent-memory`** — NVM/PM and CXL-persistent-tier data structures, durable
  logging, crash-consistent PM; distinct from volatile `memory`.
- **`caching`** — CDN/web caches, DB buffer pools, hierarchical caching, KV-cache
  eviction policies (including LLM KV-cache); focuses on the caching policy/mechanism
  rather than the workload on top.
- **`crash-consistency`** — filesystem and PM crash safety, recovery protocols operating
  below the `transactions` layer.
- **`databases`** — DBMS internals, OLTP/OLAP engines, query processing.
- **`transactions`** — concurrency control, isolation levels, distributed transactions.
- **`graph-processing`** — graph engines, graph-aware storage and schedulers, GNN
  systems from the graph side (GNN training/serving also takes `ml-systems`).

## Networking & distributed

- **`networking`** — transport protocols, congestion control, topology, switching.
- **`rdma`** — RDMA verbs and one-sided primitives. SmartNIC offload goes in `smartnic`.
- **`smartnic`** — SmartNICs, DPUs, IPUs, programmable switches (P4), in-network compute,
  NIC-side offload.
- **`consensus`** — Paxos/Raft variants, BFT, atomic broadcast.
- **`fault-tolerance`** — replication, recovery, checkpointing beyond consensus itself.
- **`observability`** — distributed tracing, always-on profiling, anomaly detection
  infrastructure for production systems.

## AI systems

- **`llm-inference`** — LLM serving systems: KV-cache management, continuous/paged
  batching, disaggregated prefill/decode, speculative decoding infra, request routing.
- **`llm-training`** — LLM and foundation-model training: 3D parallelism, optimizer
  sharding, pipeline/tensor parallel schedulers, checkpoint/restart at scale.
- **`ml-systems`** — non-LLM ML systems: recommender serving, general training infra,
  feature stores, DLRM-style systems. LLM-specific work uses `llm-inference` or
  `llm-training`.
- **`gpu`** — GPU scheduling, memory management, collective comms, GPU kernels.

## Hardware & compilers

- **`hardware`** — custom silicon, FPGAs, ASICs, accelerators other than GPUs. NICs go in
  `smartnic`; GPU-specific work goes in `gpu`. Quantum hardware goes in `quantum`.
- **`compilers`** — compiler-driven systems work, auto-tuning, tensor compilers, JITs.
- **`quantum`** — quantum computing: quantum architectures, QEC/fault-tolerant circuits,
  quantum compilation and scheduling, analog-quantum simulation. Use in addition to (not
  instead of) `hardware`/`compilers` when those also apply.

## Security & correctness

- **`security`** — attacks, defenses, side channels, supply-chain security at the software
  or protocol layer. Hardware-rooted isolation goes in `confidential-computing`.
- **`confidential-computing`** — TEEs (SGX, SEV-SNP, TDX, ARM CCA), attestation, encrypted
  memory, confidential VMs/containers, TEE-based protocols.
- **`verification`** — proofs of system correctness (Coq, Isabelle, refinement proofs).
- **`formal-methods`** — lighter-weight formal techniques: TLA+, model checking, bounded
  analysis, systematic testing harnesses.
- **`fuzzing`** — coverage-guided and differential testing of kernels, filesystems,
  hypervisors, and protocol implementations.

## Programming systems

- **`pl-systems`** — systems results that lean on PL techniques (type systems, effects,
  linear/ownership types, DSLs for systems).

## Cross-cutting

- **`energy`** — energy-efficient systems, carbon-aware scheduling, power-capping,
  sustainability-driven system design.

## Process note

If you feel pressure to add a new tag:

1. Finish the summary using the closest existing tag(s).
2. In `My Notes`, write: `proposed tag: <kebab-case-name> — <one-line rationale>`.
3. The user batch-reviews proposals before promoting any to this vocabulary.
