---
title: "Anvil: A General-Purpose Timing-Safe Hardware Description Language"
oneline: "Anvil adds event-parameterized timing contracts and a static type system so RTL designers can express dynamic-latency hardware without timing hazards."
authors:
  - "Jason Zhijingcheng Yu"
  - "Aditya Ranjan Jha"
  - "Umang Mathur"
  - "Trevor E. Carlson"
  - "Prateek Saxena"
affiliations:
  - "Department of Computer Science, National University of Singapore, Singapore"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790125"
code_url: "https://github.com/kisp-nus/anvil"
tags:
  - hardware
  - compilers
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Anvil is an HDL that makes timing stability part of the type system instead of leaving it to simulation and designer discipline. Its key move is to describe values with event-parameterized lifetimes and to type-check register mutations, value uses, and message sends against those lifetimes. That lets it express dynamic-latency components such as caches and page-table walkers while still rejecting timing-hazard bugs at compile time.

## Problem

The paper targets a very ordinary but under-formalized RTL failure mode: a designer expects some signal to stay meaningful for multiple cycles, yet the registers feeding that signal are mutated too early or the consumer reads the value too soon. In SystemVerilog, VHDL, and similar HDLs, signals are functions of the current register state, so the language does not directly encode "this address must remain stable until the memory replies" or "this output is only valid after the request completes." The result is what the authors call timing hazards: stale reads, skipped requests, invalid outputs, and even TOCTOU-style vulnerabilities.

The paper's motivating memory example is deliberately simple: a client toggles `req`, increments an address, and expects memory data one cycle later. If the real memory takes two cycles, the client changes the address while the previous request is still in flight and also reads the output before it is ready. The point is not that designers cannot debug such bugs eventually, but that existing RTL languages make the timing contract implicit, scattered across modules, and easy to violate accidentally.

Verification-based fixes exist, but the authors argue that they solve the problem too late in the flow. Assertions and model checking can catch hazards after the design is written, yet they require extra specification work and still suffer from long feedback loops and state-explosion issues. The paper therefore asks for a language-level solution: can an HDL expose cycle-level control like RTL, still support dynamic latencies, and statically rule out timing hazards?

## Key Insight

The central claim is that timing safety can be enforced statically if the HDL tracks not just values, but when those values are guaranteed to remain unchanged. Anvil does this by representing time with abstract events instead of fixed cycle counts alone. Some events are static, like "one cycle later"; others are dynamic, like "when this channel message is acknowledged." Once those events are available, the compiler can assign each value a lifetime interval and each register a loan time, then check whether any use or mutation violates the implied contract.

This matters because dynamic timing is the paper's real differentiator. Filament-style timeline types handle fixed-delay pipelines well, but they cannot naturally capture components whose latency depends on runtime behavior, such as cache hits versus misses. Anvil's proposition is that the contract should be parameterized by events, not by fixed constants: "keep this address valid from `req` until the next `res`" is expressive enough for variable-latency hardware and still precise enough for static reasoning.

## Design

Anvil models modules as communicating processes connected by stateless bidirectional channels. Communication is blocking on both ends, so a send/receive pair defines a shared synchronization event. Channel definitions attach message contracts to each message: a type, an expiry event, and sync modes that describe whether the timing is dynamic, static, or dependent on another message. This is how the language elevates interface timing from an informal convention to something the compiler can actually inspect.

The programming model still looks like low-level RTL rather than HLS. Processes contain registers, channels, and concurrent threads. `loop` expresses repeated behavior, while `recursive` allows pipelined overlap between iterations. Terms such as `recv`, `send`, `cycle N`, `t1 >> t2`, and `t1; t2` give explicit control over when work happens and whether subcomputations run sequentially or in parallel. The paper emphasizes that this is not an attempt to hide registers and wires; the designer still chooses timing intentionally.

The type system is built around three abstractions. First, each value has a lifetime `[e_start, S_end)`, meaning the value is guaranteed stable from some starting event until some ending event pattern. Second, registers inherit loan times whenever values derived from them are promised to remain live; a loaned register may not be mutated during that interval. Third, all events and their timing constraints form an event graph, a DAG that records relationships like "exactly one cycle later" or "the next completion of message `enc_res` after event `e`." From this graph Anvil derives ordering relations such as `<=_G` and interval containment.

The actual safety checks are straightforward but powerful. A value use is valid only if the use interval lies within the value's lifetime. A register mutation is valid only if the write interval does not overlap any loan time. A message send is valid only if the sent value stays live for the whole contractually required interval and if repeated sends of the same message type do not create overlapping required lifetimes. Figure 5 in the paper is effective here: the unsafe memory client fails because it mutates the address before the previous request's contract expires, while the safe cache-aware version waits on the dynamic response event and type-checks.

Implementation-wise, the compiler is written in OCaml, type-checks Anvil, and lowers it to synthesizable SystemVerilog. The event graph doubles as the compiler IR. Optimization passes merge equivalent events and simplify joins before code generation. Lowering maps channels to standard `data`/`valid`/`ack`-style ports only when the sync mode requires them, so the safety machinery is compile-time only rather than extra runtime logic.

## Evaluation

The evaluation asks the right practical questions for a language paper: can designers express real hardware, does the language catch meaningful hazards, and what synthesis overhead does the generated RTL incur? The authors implement ten components, including Common Cells FIFOs, a passthrough stream FIFO, the CVA6 TLB and page-table walker, an OpenTitan AES cipher core, AXI-Lite mux/demux routers, and two pipelined designs compared against Filament baselines.

The expressiveness result is the strongest headline. Across the SystemVerilog baselines, Anvil preserves the original cycle latency in every reported design, including dynamic-latency components such as the CVA6 page-table walker and AES core. Table 1 reports average overhead versus handwritten SystemVerilog of `4.50%` in area and `3.75%` in power, with no extra cycle latency. The PTW shows `12%` area overhead and `4%` power overhead; the AXI-Lite routers show `11-12%` area overhead; the AES core has effectively zero area overhead but `22%` higher power, which the authors attribute to wider bundled switching activity. Against Filament baselines on pipelined designs, Anvil is actually smaller on average (`-11.0%` area, `6.5%` power overhead) while keeping the same latency.

The safety story is less numerically heavy but still convincing. During the case studies, the authors found that a Common Cells stream FIFO does not actually enforce the full write/read contract described by its documentation and instead relies on warning assertions plus designer care. Anvil forces those contracts into the type-checked interface itself, which is exactly the paper's point: safety should not depend on remembering informal timing conventions. The paper also notes additional real-world examples in the appendix, suggesting that the problem is not contrived.

Overall, the evaluation supports the paper's central claim well. The benchmarks are not toy arithmetic kernels; they include dynamic memory-management logic and protocol-heavy routers. The main thing the evaluation does not show is a full subsystem-scale adoption story, but for a first compiler prototype the breadth is already better than many PL-for-hardware papers.

## Novelty & Impact

Relative to _Nigam et al. (PLDI '23)_, Anvil's main novelty is not merely attaching timing contracts to interfaces, but making those contracts dynamic by parameterizing them over abstract events. Relative to HLS-style languages, its contribution is preserving explicit cycle control and the register/signal distinction instead of "solving" hazards by abstracting timing away. Relative to verification-centered workflows, its impact is shifting timing safety earlier, into the act of writing the RTL, with the contract language embedded in the HDL itself.

That makes the paper important for two communities. PL researchers get a nontrivial type-system result for concurrent hardware with dynamic timing. Hardware designers get a credible argument that static timing-safety checks need not force them into fixed-delay pipelines or software-like abstractions. If Anvil's ideas spread, I would expect them to influence future HDLs and perhaps interface specifications for reusable IP.

## Limitations

Anvil proves timing safety for a specific class of bugs, not full RTL correctness. It does not claim to eliminate protocol mismatches, deadlocks, combinational-loop issues, or functional mistakes unrelated to value lifetimes. Designers still need verification for those concerns. That is an important scope boundary, because the language could otherwise be mistaken for a general substitute for RTL verification.

The programming model also imposes structure. Communication is phrased as blocking message passing over channels, and designers must expose timing contracts explicitly enough for the type system to reason about them. That seems like a reasonable price for safety, but it may feel less natural in designs that rely heavily on ad hoc shared wires or on idiomatic SystemVerilog patterns the paper does not model directly.

The implementation evidence, while strong for a first paper, is still limited. The compiler is explicitly described as an early-stage prototype, the evaluation covers ten modules rather than whole SoCs, and some of the underlying event-order checks in the implementation use sound approximations. None of that breaks the contribution, but it means the current system should be read as a compelling research prototype rather than a drop-in replacement for mature industrial HDLs.

## Related Work

- _Nigam et al. (PLDI '23)_ — Filament is the closest antecedent: it offers timeline-typed timing safety, while Anvil extends the idea to dynamic, event-parameterized timing contracts.
- _Majumder and Bondhugula (ASPLOS '23)_ — HIR adds explicit time variables to an accelerator IR, but it abstracts away lifetimes and only supports static timing behaviors.
- _Han et al. (ASPLOS '23)_ — ShakeFlow prevents structural hazards with latency-insensitive interface combinators, whereas Anvil targets timing hazards on shared values in general-purpose RTL.
- _Zagieboylo et al. (PLDI '22)_ — PDL raises the abstraction level for pipelined processors, but Anvil aims at broader hardware modules and makes value lifetime safety the primary static property.

## My Notes

<!-- empty; left for the human reader -->
