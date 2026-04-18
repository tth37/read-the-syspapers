---
title: "On Temporal Verification of Stateful P4 Programs"
oneline: "p4tv treats a P4 switch as an infinite packet loop, specifies packet-sequence properties in P4LTL, and checks them with a Büchi transaction that preserves register history."
authors:
  - "Delong Zhang"
  - "Chong Ye"
  - "Fei He"
affiliations:
  - "School of Software, BNRist, Tsinghua University, Beijing 100084, China"
  - "Key Laboratory for Information System Security, MoE, China"
conference: nsdi-2025
project_url: "https://thufv.github.io/research/p4tv"
tags:
  - networking
  - smartnic
  - verification
  - formal-methods
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

`p4tv` verifies temporal properties of stateful P4 programs at packet-processing granularity. It preserves registers across packets, expresses packet-sequence properties in `P4LTL`, and checks the negated property with a Büchi transaction whose temporal automaton advances only when one packet finishes. On 9 benchmarks and 19 tasks, it verifies 14 and reports the rest as violations.

## Problem

Stateful P4 programs use registers and local data-plane state to implement failover, queue control, NDN-style matching, and protocol logic. Existing P4 verifiers mostly reason about one packet at a time and reset registers to nondeterministic values before each packet. That is good enough for some single-packet assertions, but it loses exactly the history that makes a program stateful.

The P4NIS example shows the gap. A verifier that may start with an arbitrary register value can claim that forwarding ports leave the valid range, even though the intended initialization and update logic keep the register bounded forever. Liveness properties are even harder: a statement such as "if some packets keep arriving, each legal output port is used infinitely often" cannot be reduced cleanly to a one-packet check. So the real problem is to model an unconstrained packet environment, persistent register state, and optional control-plane assumptions in one verification framework.

## Key Insight

The key claim is that the right time step is "one packet completed," not "one statement executed." Once time is defined at packet boundaries, temporal operators talk about the values that matter to network behavior, and register persistence becomes part of the semantics instead of an implementation detail.

That leads to two design choices. First, the switch should be modeled as an infinite loop that repeatedly receives a nondeterministic packet and preserves registers across iterations. Second, the verifier should not use a standard Büchi program product, because that advances the temporal automaton at every statement and creates traces that are irrelevant to packet-level properties. The paper's Büchi transaction advances the temporal automaton only when a packet-processing transaction returns.

## Design

`p4tv` starts with an environment model. Registers are declared outside an infinite loop, each iteration initializes packet fields nondeterministically, metadata follows P4-16 initialization, and tables are modeled as nondeterministic action choices unless the user supplies a control-plane interface (CPI). CPI lets users constrain symbolic relationships among table hits, keys, and actions when a property is only meaningful under certain rule sets.

The specification language `P4LTL` extends LTL with P4-aware terms and predicates. Terms can mention headers, metadata, registers, table keys, action parameters, and `old(...)` values captured at the start of ingress. Predicates describe forwarding, drop, table hits, and action applications. Because the semantics live at packet boundaries, operators such as `next`, `eventually`, `always`, and `until` naturally describe packet sequences rather than statement traces.

Implementation-wise, the tool translates P4 to Boogie, instruments ghost variables for the `P4LTL` observations, negates the target property, converts the negation to a Büchi automaton, and builds the Büchi transaction with the P4 control-flow automaton. It then searches for a fair feasible trace using Ultimate Automizer. A fair feasible trace is a real counterexample; if none exists, the property is verified.

## Evaluation

The authors collect 9 stateful P4 benchmarks, including failover schemes, CoDel, NDN, P4NIS, and P4xos acceptor/learner variants, and formulate 19 temporal verification tasks. `p4tv` verifies 14 of them and returns counterexamples for 5. The counterexamples are meaningful: the tool finds a missing register-initialization assumption in P4NIS, a broken heartbeat-related update in P4sp, and injected bugs in both CPI and code.

The costs are nontrivial but plausible for model checking: about 10 seconds to 21 minutes, with 51 seconds median, 181 seconds average, and roughly 201 MB to 6.1 GB memory. The assertion-checking comparison with bf4 and p4v is also useful. `p4tv` is slower on stateless assertions because it keeps the multi-packet model, but it is more precise on stateful assertions, where prior tools can report spurious counterexamples by forgetting the intended register configuration. The scalability experiments are honest: verification time grows quickly with both program and specification complexity.

## Novelty & Impact

The paper contributes a packet-sequence execution model, a P4-specific temporal logic, and a model-checking construction whose step semantics match packet processing. That makes it the first tool in this space to verify stateful P4 behavior across packets rather than only within one packet.

This matters for programmable-switch logic whose correctness depends on history, such as failover, content-centric forwarding, or Paxos-like control paths. `p4tv` lets those designs be checked against their temporal contracts instead of weakened single-packet approximations.

## Limitations

The prototype fully supports V1Model but only limited TNA and PSA support. `P4LTL` only observes states at packet boundaries, so transient mid-pipeline violations are out of scope. The method also still faces ordinary model-checking explosion; the paper's own curves show steep growth as the program or formula gets bigger. Finally, some properties only hold under particular table rules, so users may need CPI assumptions instead of a fully unconstrained control plane.

## Related Work

- _Liu et al. (SIGCOMM '18)_ - `p4v` verifies realistic P4 semantics with SMT solving, but it resets register state per packet and therefore cannot prove packet-sequence temporal properties.
- _Stoenescu et al. (SIGCOMM '18)_ - Vera adds symbolic execution and NetCTL-style reasoning for P4, whereas `p4tv` shifts the time model to multi-packet traces with persistent state.
- _Tian et al. (SIGCOMM '21)_ - Aquila scales verification toward production P4 deployments, but it still lives in the per-packet verification world rather than temporal state evolution across packets.
- _Kang et al. (ASPLOS '21)_ - P4wn also models repeated executions of stateful P4 programs, yet it is a probabilistic testing tool for adversarial profiling rather than a temporal model checker.

## My Notes

<!-- empty; left for the human reader -->
