# Tag vocabulary

This is the canonical list of tags. Use 3–6 per paper. If no tag fits a genuinely-new
topic, flag it in the paper's `My Notes` section instead of inventing one silently.

Each tag's one-line scope rule is normative — when two tags could plausibly fit, pick the
one whose scope rule fits more tightly.

## Core systems

- **`scheduling`** — CPU/task scheduling, load balancing, kernel-level or userspace.
- **`kernel`** — OS kernel internals, syscall path, kernel bypass is tagged separately.
- **`virtualization`** — hypervisors, VMs, microVMs, lightweight isolation primitives.
- **`isolation`** — sandboxing, containers, namespaces, policy enforcement at process/VM boundary.
- **`memory`** — memory management, paging, swap, disaggregated memory, CXL, NUMA.
- **`datacenter`** — cluster-level resource management, microservices infra, orchestration.
- **`serverless`** — FaaS platforms, cold-start, function scheduling.

## Storage & data

- **`storage`** — block/object storage, durability, replication below DB layer.
- **`filesystems`** — local or distributed file systems.
- **`databases`** — DBMS internals, OLTP/OLAP engines.
- **`transactions`** — concurrency control, isolation levels, distributed txns.

## Networking & distributed

- **`networking`** — transport protocols, congestion control, topology, switching.
- **`rdma`** — RDMA-specific techniques and primitives.
- **`consensus`** — Paxos/Raft variants, BFT, atomic broadcast.
- **`fault-tolerance`** — replication, recovery, checkpointing beyond consensus itself.

## ML / acceleration

- **`ml-systems`** — training/inference systems, serving infra, LLM systems.
- **`gpu`** — GPU scheduling, memory, collective comms, kernels.
- **`hardware`** — specialized hardware / accelerators / FPGAs / custom silicon.
- **`compilers`** — compiler-driven systems work, auto-tuning, tensor compilers.

## Security & correctness

- **`security`** — attacks, defenses, side channels, supply chain.
- **`verification`** — program or system verification, proofs of correctness.
- **`formal-methods`** — model checking, TLA+, lightweight formal methods.

## Programming systems

- **`pl-systems`** — systems results that lean on PL techniques (type systems, effects).

## Process note

If you feel pressure to add a new tag:

1. Finish the summary using the closest existing tag(s).
2. In `My Notes`, write: `proposed tag: <kebab-case-name> — <one-line rationale>`.
3. The user batch-reviews proposals before promoting any to this vocabulary.
