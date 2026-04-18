---
title: "Fork in the Road: Reflections and Optimizations for Cold Start Latency in Production Serverless Systems"
oneline: "AFaaS replaces OCI's long cold-start path with a FaaS-specific interface, resource pooling, and hierarchical forkable seeds to cut production cold starts to milliseconds."
authors:
  - "Xiaohu Chai"
  - "Tianyu Zhou"
  - "Keyang Hu"
  - "Jianfeng Tan"
  - "Tiwei Bie"
  - "Anqi Shen"
  - "Dawei Shen"
  - "Qi Xing"
  - "Shun Song"
  - "Tongkai Yang"
  - "Le Gao"
  - "Feng Yu"
  - "Zhengyu He"
  - "Dong Du"
  - "Yubin Xia"
  - "Kang Chen"
  - "Yu Chen"
affiliations:
  - "Tsinghua University"
  - "Ant Group"
  - "Shanghai Jiao Tong University"
  - "Quan Cheng Laboratory"
conference: osdi-2025
code_url: "https://github.com/antgroup/AFaaS"
tags:
  - serverless
  - virtualization
  - datacenter
category: networking-and-virtualization
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

AFaaS argues that production serverless cold starts are no longer dominated only by sandbox creation. It replaces OCI's long intra-node control path with a serverless-specific runtime interface, pools and shares contended kernel resources, and forks from hierarchical user-code seeds. On Ant Group's platform, that cuts end-to-end latency by 1.80x-8.14x over a Catalyzer-based baseline and keeps cold-start latency between 6.97 ms and 14.55 ms at 24x concurrency.

## Problem

The paper starts from an uncomfortable production fact: cold starts are still common even on a large commercial FaaS platform that already uses secure containers and fork-based startup. Ant Group reports more than 50,000 unique functions and around 100 million function calls per day, but the invocation distribution is highly skewed. More than 50% of functions have a cold-start probability above 0.75, and more than 35% always cold start, because keeping instances warm for infrequent functions is too memory-expensive. For workloads whose useful execution often lasts only 50-100 ms, a one-second startup penalty is still a first-order latency problem.

The authors argue that prior work usually optimizes one slice of the cold-start path and then stops there. Fork-based systems such as Catalyzer make sandbox creation extremely fast; caching and checkpoint/restore reduce some initialization work; lightweight runtimes remove some container overhead. But an end-to-end production trace shows that these wins do not automatically translate into low user-visible latency. In their Node.js example, the control path alone costs 18-25 ms, and user-code initialization costs 275.53 ms, including 238.73 ms spent loading dependencies. Under concurrency, the situation gets worse: tail latency spreads out and throughput decays over time as the host kernel contends on namespace, mount, and seccomp-related paths.

That framing is the real contribution of the problem section. The paper is not saying "fork is too slow"; it is saying that production cold start is a pipeline, and the slow stages move once one stage is optimized. The three gaps it identifies are control-path latency between containerd and the low-level runtime, resource contention during concurrent startup, and user-code initialization that dominates once sandbox boot is cheap.

## Key Insight

The core claim is that most of the remaining cold-start cost comes from repeatedly reconstructing state that could instead be inherited, pooled, or bypassed. If the common serverless path is specialized rather than forced through the generic OCI stack, high-frequency operations can become direct calls instead of binary loads and multi-hop RPCs. If the resources that suffer the worst concurrency contention are prepared ahead of time or shared safely with a seed, startup stops fighting the kernel on the hot path. If user-code state is organized at multiple granularities, the platform can fork from the nearest prepared ancestor instead of choosing between a fully warm function and a full cold start.

This works because AFaaS is built on secure containers with Copy-on-Write sharing and per-instance guest execution. Much of the state that matters for startup speed, such as runtime initialization, compiled seccomp rules, and preloaded user code, can be inherited without turning the instance into a hot cache of another user's mutable execution. The system therefore treats cold start as a state-placement problem across the entire stack, not as a single VM fork primitive.

## Design

AFaaS keeps the basic two-level runtime architecture, with `containerd` as the high-level runtime and a Catalyzer-derived low-level runtime for secure containers, but replaces OCI-style interaction with FRI, the Function Runtime Interface. FRI exposes `create()`, `fork()`, and `activate()` through a `containerd-faas-package` plugin. The key move is that only the root seed needs the expensive `create()` path that loads the low-level runtime binary. After that, `fork()` and `activate()` are invoked directly from the high-level runtime, removing the 18-25 ms binary-load-heavy shim path that still existed in Catalyzer.

To address contention, AFaaS splits resources into those worth pooling and those worth sharing. It pre-allocates veth pairs and recycles cgroups from pools, so instance creation does not constantly allocate and tear down these kernel objects under load. It shares network and IPC namespaces with the seed, pre-compiles seccomp rules during seed preparation, and divides the network stack into shareable state and per-instance bindings. The shareable pieces, such as protocol handlers and other largely invariant structures, are inherited from the seed; the instance-specific pieces, such as addresses and device bindings, are set up after fork.

For user-code initialization, AFaaS organizes seeds as a tree. A level-0 root seed contains the guest OS state, level-1 seeds add a language runtime such as Node.js or Python, and level-2 seeds add function-specific code, libraries, and framework initialization. When a request arrives, the runtime walks this tree and forks from the closest available ancestor. That gives a best-effort spectrum between a full user-code seed and a plain language seed, while Copy-on-Write lets related seeds share memory. The implementation also adds container early destroy and EPT prefill to reduce teardown cost and page-table miss overhead for short-lived functions.

## Evaluation

The evaluation uses a 24-core Xeon server with 512 GB of RAM and compares AFaaS against Kata, gVisor, and three intermediate configurations: `CataOnly`, `CataOPT1`, and `CataOPT2`. This decomposition is useful because it shows that the system's gains come from all three gaps, not just one optimization hidden inside a monolithic implementation.

The main sequential results support the paper's claim. For functions with short initialization and short execution, AFaaS improves average end-to-end latency by 3.76x-6.68x and P99 latency by 6.31x-11.74x over `CataOnly`. For functions where user-code initialization dominates, the gains are larger: 4.09x-31.48x on average and 6.19x-34.51x at P99, because the seed hierarchy can bypass framework and dependency loading entirely. For long-running functions, gains shrink to about 1.05x-1.14x, which is exactly what one would expect if startup is no longer the dominant component.

The concurrency results are even more important because the paper's second gap is about instability, not just median speed. On the JS benchmark, AFaaS keeps end-to-end latency in the range 16.34-39.56 ms from 1x to 24x concurrency, whereas `CataOnly` ranges from 51.32 ms to 117.92 ms. The cold-start portion alone stays within 6.97-14.55 ms for AFaaS versus 38.39-74.05 ms for `CataOnly`. Under sustained 24x concurrency, `CataOnly`'s throughput degrades as namespace and kernel-lock paths fall off the fast path, while AFaaS remains much more stable. The paper also shows that tree-structured seeds save 28.11%-84.91% memory relative to per-function seeds in `CataOnly`, and a one-day production study across eight Node.js functions shows 1.80x-8.14x end-to-end speedups with startup times between 5.45 ms and 9.41 ms. Overall, the evaluation does support the central claim, though most of the real-world evidence comes from Ant Group's own stack and workload mix.

## Novelty & Impact

Relative to _Du et al. (ASPLOS '20)_, AFaaS treats Catalyzer's sub-millisecond fork as the start of the real production problem rather than the finish line, and shows that OCI control-path overhead, kernel contention, and user-code initialization can erase much of the theoretical benefit if left alone. Relative to _Li et al. (ATC '22)_, the paper is less about inventing a lighter secure container runtime and more about specializing the interface and resource lifecycle around FaaS semantics. Relative to _Yu et al. (ASPLOS '24)_ and the broader caching/checkpoint line, AFaaS avoids depending on long-lived warm instances or restore-heavy snapshots by using hierarchical, best-effort forkable seeds.

That makes the paper important for practitioners. Its novelty is not a brand-new primitive so much as a production-quality synthesis of where the remaining milliseconds actually come from after fork-based startup is already fast. Serverless platform builders, especially those operating secure-container stacks, will likely cite it as a map of which layers still matter once "cold start optimization" moves past sandbox creation.

## Limitations

AFaaS wins partly by abandoning generality. FRI is explicitly specialized for serverless and tightly coupled to `containerd` plus the AFaaS low-level runtime, so the design is not a drop-in improvement for arbitrary OCI-compliant stacks. The security argument also follows the secure-container threat model used by prior work rather than proving that pooled or shared resources are universally safe; the paper explains why network namespaces, IPC namespaces, and pooled kernel objects remain acceptable in its setting, but that reasoning is still deployment-specific.

The user-code seeding story is also conditional. The biggest wins come from functions that are invoked often enough to justify maintaining seeds, yet not often enough to live happily as hot instances. Too many user-specific seeds increase memory pressure and can trigger swapping, which the paper explicitly warns about. At ultra-high concurrency, a seed can itself become a serialization point because only one clone can be produced from it at a time, and co-located workloads can still reintroduce cgroup-lock jitter. Finally, the evaluation is strongest on Ant Group's production functions and Node-heavy examples; the paper does not show how portable the same gains would be on very different serverless stacks or workloads dominated by long application execution.

## Related Work

- _Du et al. (ASPLOS '20)_ - Catalyzer showed that secure-container startup can be reduced to sub-millisecond fork time, while AFaaS shows why that is not sufficient for end-to-end production cold starts.
- _Li et al. (ATC '22)_ - RunD targets high-density, high-concurrency secure containers, whereas AFaaS focuses on serverless-specific control-path specialization and seed-based reuse on top of a secure-container substrate.
- _Wei et al. (OSDI '23)_ - MITOSIS uses remote fork and RDMA to remove provisioned concurrency across nodes, while AFaaS targets single-node production bottlenecks without specialized hardware.
- _Yu et al. (ASPLOS '24)_ - RainbowCake mitigates serverless cold starts with layer-wise caching and sharing, whereas AFaaS relies on hierarchical seeds and best-effort multi-level fork instead of warm cache retention.

## My Notes

<!-- empty; left for the human reader -->
