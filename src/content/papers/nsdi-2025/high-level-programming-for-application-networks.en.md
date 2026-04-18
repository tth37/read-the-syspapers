---
title: "High-level Programming for Application Networks"
oneline: "AppNet expresses service-mesh functions as high-level match-action rules and compiles them into equivalent RPC-library/proxy placements that cut RPC overhead by up to 82%."
authors:
  - "Xiangfeng Zhu"
  - "Yuyao Wang"
  - "Banruo Liu"
  - "Yongtong Wu"
  - "Nikola Bojanic"
  - "Jingrong Chen"
  - "Gilbert Louis Bernstein"
  - "Arvind Krishnamurthy"
  - "Sam Kumar"
  - "Ratul Mahajan"
  - "Danyang Zhuo"
affiliations:
  - "University of Washington"
  - "Duke University"
  - "UCLA"
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - pl-systems
  - compilers
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AppNet treats a service mesh as a high-level program instead of a pile of platform-specific filters. Developers describe application network functions with match-action rules over RPC fields and shared state, and the compiler chooses where and how each function should run while checking semantic equivalence for arbitrary RPC streams. Across random chains and two microservice applications, this cuts processing overhead and end-to-end latency substantially.

## Problem

The paper starts from a gap between what service meshes promise and what they deliver. In principle, an application network only needs to support a known set of microservices and policies, so one might expect it to be both specialized and cheap. In practice, developers still write application network functions in low-level, platform-specific code, or they tunnel RPC semantics through generic HTTP modules. That makes simple application-specific policies, such as access control or routing based on RPC fields, hard to express, especially when the service code is third-party or cannot be modified.

The performance story is equally bad. Existing service meshes force operators to decide each function's execution order, placement, and platform by hand: in-process RPC libraries, sidecars, or remote proxies. Those choices interact with state sharing, replica counts, and whether earlier functions drop requests, so local intuition is often wrong. The paper cites prior evidence that application networks can raise RPC latency and CPU usage by 2-7x. The core problem is therefore not just "service meshes are slow"; it is that today's abstractions describe execution decisions directly instead of describing the desired semantics and letting a system optimize the implementation.

## Key Insight

The main claim is that application networks can be compiled the same way lower-layer networks are: programmers should specify semantics, while a compiler chooses an efficient realization. For this to work at layer 7, the language must expose RPC-field access, shared state, and auxiliary outputs such as logs, and the compiler must reason about stateful behavior across whole RPC streams rather than isolated packets.

AppNet's second key insight is that semantic equivalence can be checked without modeling every line of processing logic. The compiler abstracts each element into symbolic transfer functions that record what fields, state variables, drop decisions, reorder decisions, and output channels it can affect. Symbolic execution over a chain then reveals whether a reordered or relocated implementation is equivalent under strong or weak observation consistency. That abstraction is what lets AppNet optimize aggressively without silently changing behavior.

## Design

AppNet programs one communication edge between two microservices as a chain of elements. Users can place elements in four specification buckets: `client`, `server`, `any`, and `pair` for coupled functions such as compression/decompression. Each element has `state`, `init`, `req`, and `resp` sections. Processing is written as generalized match-action rules over RPC metadata, payload fields, built-in functions, and key-value state. Shared state is a first-class concept, and users can request strong consistency, weak consistency, or an aggregation method such as `sum`. Because the compiler also consumes the RPC schema, developers do not write serialization code or manually keep field names in sync with Protobuf definitions.

The optimizer first tags state by dependency, such as client-replica, server-replica, or global. It then searches over placements, platforms, and orderings using multi-start simulated annealing. The cost model prefers low-overhead platforms, chains that can collapse onto one platform so others can be bypassed, placements that align with state dependencies, co-location of elements that must synchronize shared state, and early placement of elements that may drop RPCs. For short chains, the compiler can brute-force the search; for longer ones it uses the annealing heuristic.

The semantic safety net is the paper's most interesting mechanism. AppNet symbolically abstracts each element into transfer functions and then symbolically executes whole chains to compute end-to-end functions for output RPCs, state updates, and auxiliary channels. Two chains are strongly equivalent if all of those functions match; under weak observation consistency, differences in auxiliary outputs such as logs are allowed while microservice-visible behavior must remain identical. The runtime controller integrates with Kubernetes and Istio, generates gRPC interceptor modules or Envoy C++/Wasm modules, uses Redis for strongly consistent shared state, synchronizes weak state in the background, and performs two-phase versioned updates so an RPC sees either the old configuration or the new one, never a mix.

## Evaluation

The paper evaluates AppNet at three levels. First, expressiveness: it implements 14 application network functions, including 12 common ones such as rate limiting, caching, logging, and admission control, plus ServiceRouter and Prequal-style routing/load balancing. The common functions take only 7-28 lines of AppNet code; ServiceRouter needs 62 lines and Prequal 88. Generated modules incur only a small abstraction tax relative to hand-written filters, with median latency and CPU overhead of 1-4%.

Second, on random RPC-processing chains over an Echo benchmark, AppNet meaningfully outperforms both an unoptimized baseline (`NoOpt`) and a locally sensible baseline (`LocalOpt`). For 30 random 5-element chains, AppNet with strong consistency reduces median service time by 47%, tail latency by 44%, and CPU usage by 42% relative to `NoOpt`; with weak consistency, the median reduction rises to 74-83%. The best cases reach the headline 82% latency reduction and 75% CPU reduction cited in the paper. The optimizer is also practical: the paper reports 1.4 seconds to find configurations for the 5-element chains used in the main experiments.

Third, the gains survive contact with applications. On Hotel Reservation, AppNet cuts median end-to-end service time, tail latency, and CPU by 35%, 29%, and 26% with strong consistency, and by 49%, 41%, and 42% with weak consistency. Appendix results on Online Boutique show smaller but still meaningful improvements. These results support the paper's thesis that service-mesh overhead is a first-order tax on microservice applications, not merely a microbenchmark artifact.

## Novelty & Impact

AppNet is novel because it combines three ideas that usually appear separately: a programmable language for application-network logic, a compiler that searches across multiple execution substrates, and a semantic checker that handles stateful chains with drops, reordering, and auxiliary outputs. Relative to production systems such as `ServiceRouter`, it is a general framework rather than a single purpose-built policy engine. Relative to packet-level languages such as `P4` or network-wide languages such as `NetKat`, it moves the abstraction boundary up to RPC semantics and shared service-mesh state.

The impact is twofold. Practically, AppNet suggests that service meshes need not force operators into a trade-off between expressiveness and overhead. Conceptually, it reframes application networking as a compilation problem, which opens the door to future back ends such as kernel or hardware offload and to safer configuration changes via compiler-managed updates.

## Limitations

The current system is still a research prototype with real deployment constraints. AppNet supports only three execution targets today: gRPC interceptors, EnvoyNative, and EnvoyWasm. The paper explicitly says kernel or eBPF execution is future work. It also assumes the chosen platform can see RPC headers and payloads in plaintext; if end-to-end mTLS must remain opaque to intermediaries, AppNet effectively narrows to gRPC interceptors.

Some costs are also pushed into the runtime rather than eliminated. Strongly consistent shared state goes through Redis on every access, so the performance story depends heavily on whether the compiler can align placement with state dependencies or weaken consistency safely. The cost model is heuristic rather than learned from deployment telemetry. Finally, much of the evaluation uses randomly generated chains and Go/gRPC application ports, which is enough to show broad promise but not enough to prove that AppNet's search space and abstractions already cover the messiest production service-mesh policies.

## Related Work

- _Saokar et al. (OSDI '23)_ - `ServiceRouter` hardens a specific production service-mesh design, while `AppNet` aims to express and optimize a wider class of application network functions with one language and compiler.
- _Wydrowski et al. (NSDI '24)_ - `Prequal` is a sophisticated latency-aware load balancer; `AppNet` treats it as one policy that can be encoded in the framework rather than the framework's fixed purpose.
- _Panda et al. (OSDI '16)_ - `NetBricks` improves performance by composing middlebox functions safely, but it operates on packet-processing NFs rather than RPC-level service-mesh logic with placement and state-consistency reasoning.
- _Bremler-Barr et al. (SIGCOMM '16)_ - `OpenBox` removes redundant packet-level NF logic, whereas `AppNet` reasons about semantic equivalence of stateful RPC-processing chains across multiple runtimes.

## My Notes

<!-- empty; left for the human reader -->
