---
title: "Rajomon: Decentralized and Coordinated Overload Control for Latency-Sensitive Microservices"
oneline: "Rajomon carries tokens and per-interface prices through a microservice graph so clients rate-limit early and services shed the same doomed work consistently."
authors:
  - "Jiali Xing"
  - "Akis Giannoukos"
  - "Paul Loh"
  - "Shuyue Wang"
  - "Justin Qiu"
  - "Henri Maxime Demoulin"
  - "Konstantinos Kallas"
  - "Benjamin C. Lee"
affiliations:
  - "University of Pennsylvania, USA"
  - "DBOS, Inc, USA"
  - "University of California, Los Angeles, USA"
conference: nsdi-2025
category: memory-serverless-and-storage
code_url: "https://github.com/pennsail/rajomon"
tags:
  - datacenter
  - scheduling
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Rajomon turns overload control into a distributed market over a microservice graph. Tokens travel with requests, per-interface prices travel back, and overloaded paths become expensive before more work is launched. That lets the system throttle at clients and drop consistently across branches.

## Problem

The paper studies overload in latency-sensitive microservice graphs, where overload can start deep in a dependency chain and then propagate backward as queues grow. Shared services also multiplex many APIs, so one expensive interface can block unrelated cheap ones. Alibaba traces in the paper show that wide fan-out and multiplexing are common, which makes single-node overload control too blunt.

Prior systems each miss one of the three properties the authors want. Dagor is decentralized but coordinates only pairwise, so work can travel several hops before being dropped. Breakwater limits clients only at a front-end boundary, leaving downstream hotspots invisible until too late. TopFull reasons at API granularity but is centralized and slow. The result is poor recovery during traffic spikes.

## Key Insight

Rajomon's key claim is that end-to-end microservice overload control does not require a central coordinator if each request carries a portable budget and each interface advertises a portable congestion signal. Tokens are the budget, prices are the signal.

Tokens let all branches derived from one request agree on that request's priority, so overloaded fan-out paths can drop the same low-token work instead of wasting effort on inconsistent subsets. Prices let interfaces expose scarcity and push that information upstream, so callers slow down before work enters long downstream chains. With those two metadata fields, Rajomon gets decentralization, graph-wide coordination, and interface granularity in one mechanism.

## Design

Each node runs a local controller with client-side and server-side roles. The client side generates tokens, checks whether a request has enough tokens for the destination interface's current price, and drops locally when it does not. If it does, the request is sent with attached tokens. Rajomon uses Poisson replenishment to avoid synchronized bursts and spends a uniformly random number of tokens so rising prices thin admissions gradually rather than in one step.

The server side compares attached tokens against the requested interface's price, drops insufficient requests, and forwards admitted requests with the same tokens into downstream RPCs. Local prices track queuing delay: above threshold, they rise in proportion to overload severity; below half the threshold, they fall slowly. Prices are maintained per interface, which gives multiplexed services a virtual multi-queue behavior instead of one shared admission level.

Coordination comes from backward price propagation. A service combines local and downstream prices and piggybacks updates on responses. To cap overhead, Rajomon sends price metadata lazily, for example on 20% of responses. For fan-out, total price is local price plus the maximum relevant downstream price, not the sum. That keeps the hottest bottleneck dominant and avoids splitting token budgets across branches. The prototype is about 948 lines of Go implemented as gRPC interceptors.

## Evaluation

The evaluation uses CloudLab and Kubernetes with Social Network, Hotel Reservation, and synthetic services generated from three Alibaba traces. Rajomon is compared against Dagor, Breakwater, Breakwaterd, and TopFull. The baselines are reimplemented as Go gRPC libraries and tuned with Bayesian optimization.

On single-interface tests, Rajomon keeps Search Hotel tail latency below about 200 ms and sustains roughly 3k goodput; above 12k RPS, the baselines deliver less than half its goodput and about 5x its tail latency. For Compose Post, Rajomon stays above 2k goodput while the baselines collapse toward roughly 500 RPS. By the paper's recovery metric, Rajomon is the only method that consistently achieves sub-second recovery, although one timeline still shows about 2 seconds for the full transition from server-side drops to client-side rate limiting.

The multi-interface results are the strongest evidence for the paper's thesis. Rajomon keeps different APIs near their own sustainable operating points instead of forcing them into one overloaded queue. In concurrent Social Network traffic, it keeps all interfaces within their SLOs, holds Compose Post and Read Home Timeline near 2.5k RPS, and lets Read User Timeline rise to 5k RPS. The paper reports 117% to 266% better goodput and 33% to 46% lower latency than prior work, plus 45% to 245% goodput gains and 78% to 94% latency reductions for mixed-interface cases. The evaluation supports the claim, but it is still short-duration lab testing rather than production evidence.

## Novelty & Impact

Rajomon's contribution is a compact mechanism that combines decentralization, coordination, and interface awareness in one metadata path. It is a plausible design point for service meshes and RPC middleware seeking sub-second overload handling without global telemetry.

## Limitations

Rajomon assumes trusted clients, so forged or strategic token behavior would need extra server-side validation that the paper leaves to future work. The experiments also assume mostly deterministic call paths, and the discussion only sketches an expected-value extension for dynamic paths.

Using the maximum downstream price is simple and fast, but it is not obviously optimal for every fan-out pattern, and the paper gives no formal stability proof for the full token-price loop. Most workloads are academic benchmarks or trace replays, so behavior under partial deployment remains open.

## Related Work

- _Zhou et al. (SoCC '18)_ - Dagor is decentralized and uses admission levels to drop load near hotspots, but it coordinates only pairwise and does not push throttling all the way back to clients.
- _Cho et al. (OSDI '20)_ - Breakwater introduces client-visible credits for fast RPC overload control, while Rajomon extends the idea to whole microservice graphs with per-interface state and downstream feedback.
- _Park et al. (SIGCOMM '24)_ - TopFull also reasons at API granularity, but it uses centralized reinforcement learning over global telemetry, whereas Rajomon relies on local controllers and piggybacked metadata.

## My Notes

<!-- empty; left for the human reader -->
