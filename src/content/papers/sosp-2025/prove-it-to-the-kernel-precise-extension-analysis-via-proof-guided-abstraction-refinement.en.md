---
title: "Prove It to the Kernel: Precise Extension Analysis via Proof-Guided Abstraction Refinement"
oneline: "BCF keeps the eBPF verifier simple by offloading hard refinement proofs to user space, then checking them in linear time to recover 403 wrongly rejected programs."
authors:
  - "Hao Sun"
  - "Zhendong Su"
affiliations:
  - "ETH Zurich"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764796"
code_url: "https://github.com/SunHao-0/BCF/tree/artifact-evaluation"
tags:
  - ebpf
  - kernel
  - verification
  - formal-methods
  - security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

BCF adds a proof-guided slow path to the Linux eBPF verifier: when the verifier would reject a program because its abstract state is too coarse, it asks user space to prove that a tighter abstraction is sound and then checks that proof in linear time inside the kernel. This lets the kernel keep its cheap interval- and bit-level analysis for the common case while recovering much of the precision of symbolic reasoning. On a dataset of 512 safe but previously rejected eBPF objects, the approach accepts 403 of them.

## Problem

The Linux eBPF verifier sits in an awkward spot. It must reject any extension that could violate memory safety, termination, or the kernel’s calling discipline, yet it runs inside the kernel, where complexity, latency, and attack surface matter. For that reason the verifier relies on inexpensive abstract domains, mainly intervals and tristate bit information. Those domains are fast, but they lose exactly the facts real eBPF programs often need: arithmetic identities, dependencies between registers, and path-specific relationships.

The result is a steady stream of false rejections. Safe programs are rejected because the verifier over-approximates a pointer range, forgets that two values are related, or reasons about an unreachable path as if it were feasible. Developers then work around the verifier instead of writing the clean program they intended, for example by doubling buffer sizes, inserting redundant checks, or even dropping to inline assembly. Prior work tries to improve precision by strengthening the in-kernel analysis itself, but richer abstract domains raise kernel-side cost and complexity. The paper asks a sharper question: can the verifier remain simple in kernel space while still gaining precision close to symbolic execution?

## Key Insight

The paper’s central claim is that a verifier stall should be treated as a refinement opportunity, not as an immediate rejection. When the existing abstraction becomes too coarse to prove safety, the kernel does not need to perform hard reasoning itself. It only needs to reconstruct the exact symbolic state relevant to the failing check, formulate the condition under which a tighter abstraction would be sound, and verify a proof of that condition once user space produces it.

That separation matters because proof search and proof checking have very different costs. Deriving whether a bit-vector condition holds for all assignments may require solver-level reasoning and search, but checking a concrete proof is a simple sequence of local rule applications. BCF therefore keeps the kernel responsible only for deterministic bookkeeping and linear-time checking, while outsourcing expensive search to user space without introducing hidden trust.

## Design

BCF starts from the existing verifier rather than replacing it. The normal verifier runs unchanged until it reaches a rejection point such as an out-of-bounds access implied by an overly wide range. At that point, BCF first performs a backward analysis over the current path to find the smallest suffix that defines the target register and the registers it transitively depends on. This keeps the later symbolic reasoning local: in the paper’s measurements, the tracked suffix averages 102 instructions rather than the whole program.

From that start point, BCF symbolically replays the suffix along the same branch history the verifier already explored. Instead of storing only intervals, it builds exact bit-vector expressions for the relevant registers and records path constraints. It also reuses information from the original verifier to simplify the expressions, such as shrinking symbolic variables to 32 bits when the verifier already knows the value stays in the `u32` range and skipping computations over constants. Once this precise symbolic state exists, BCF derives the refined abstraction demanded by the failed safety check. For a memory access, for example, the verifier needs the pointer offset to fit a safe interval; BCF turns that into a refinement condition asserting that the symbolic offset expression is contained in the tighter range.

That condition is serialized into a compact binary format and handed to user space through a shared buffer and a resumed `bpf()` load flow, not a new syscall. The loader translates it into cvc5’s bit-vector logic, asks the solver either for a counterexample or for a proof, and sends the resulting proof back to the kernel. The proof checker, implemented in kernel space, supports 45 primitive rules over Boolean, equality, and bit-vector reasoning. It scans the proof sequentially, recomputes each step’s conclusion, and finally checks that the proved statement matches the stored refinement condition. If the proof is valid, the verifier resumes at the same instruction with the tighter abstraction; if not, the program is rejected.

## Evaluation

The evaluation is unusually concrete because the authors build a dataset instead of relying on toy examples. They start from 106 real-world eBPF source programs from projects such as Cilium, Calico, BCC, and xdp-project, compile them across Clang 13 through 21 and optimization levels `-O1` through `-O3`, deduplicate the resulting bytecode, and add nine manually collected rejection cases. The final dataset contains 512 distinct objects that are known to be safe because some compiler configuration loads successfully, yet Linux 6.13.4 rejects the particular variant under test.

On that dataset, BCF accepts 403 of 512 objects, or 78.7%, and fully clears 75 of the 106 source programs across all compiled variants. PREVAIL, used as a comparison point, loads fewer than 1% of the programs because of compatibility issues with its Windows-oriented design. The paper also gives useful failure accounting for the remaining 109 cases: 4 never triggered a refinement because BCF had not yet been wired into that rejection site, 82 produced failed refinement conditions due to current implementation limits such as incomplete stack tracking, and 23 hit the verifier’s one-million-instruction limit, mostly in loop-heavy cases that BCF allowed to continue further than baseline Linux would.

The overhead numbers support the core systems claim that kernel-side cost stays low. Average proof size is 541 bytes, 99.4% of proofs are under 4 KiB, and average proof-check time is 48.5 microseconds. Total analysis time averages 9.0 seconds per program, with kernel-side analysis accounting for 79.3% of the time and user-space reasoning 20.7%. Although BCF is invoked often in some programs, refinement still looks like a rare slow path in aggregate: fewer than 0.1% of processed instructions trigger it on average.

## Novelty & Impact

BCF is novel because it changes where precision lives. Instead of baking a stronger abstract domain into the verifier, it turns the verifier into a cheap front-end that requests proof-backed precision only when needed. That is different from PREVAIL-style verifier redesigns, and it is also different from proof-carrying-code approaches that ask the code producer to prove the whole extension. Here, proofs justify only exceptional refinement steps, so the common path remains the familiar Linux verifier and the proofs stay small.

That design should matter to several communities. eBPF practitioners get a path toward fewer verifier-induced contortions. Kernel researchers get a way to increase extensibility without moving heavyweight theorem proving into kernel space. Formal-methods work on systems verification gets a concrete example of proof search in user space paired with a tiny in-kernel checker. This is best understood as a new mechanism and a new systems framing, not just a better benchmark result.

## Limitations

The biggest limitation is implementation coverage. BCF’s symbolic tracking fully handles ALU and branch operations, but stack-state tracking is still incomplete, especially for spills smaller than a full register. In those cases the generated condition can be too weak to prove, so a safe program still gets rejected. The integration is also not yet universal across verifier failure sites, which explains a small number of misses.

The load-time cost is acceptable for research evaluation but not free. If a program needs nontrivial user-space reasoning, it will load more slowly than today’s verifier-only path. The authors argue that proof caching could reduce this substantially because the verifier is deterministic and repeated loads would request the same conditions, but the paper does not implement or evaluate such a cache. Finally, loop-heavy programs can still run into the one-million-instruction cap, and BCF does not yet solve that broader verifier-termination problem.

## Related Work

- _Vishwanathan et al. (CGO '22)_ - Improves the verifier’s existing tristate reasoning inside the kernel, whereas BCF leaves the common-case domains simple and adds proof-backed refinement only when they stall.
- _Gershuni et al. (PLDI '19)_ - PREVAIL gains precision through the Zone abstract domain; BCF instead escapes the fixed power of any one in-kernel domain by proving tighter abstractions on demand.
- _Dwivedi et al. (SOSP '24)_ - KFlex separates kernel-interface compliance from extension correctness and still depends on the verifier for the former; BCF strengthens exactly that verifier-side check.
- _Necula and Lee (OSDI '96)_ - Safe kernel extensions via proof-carrying code require proofs for whole programs, while BCF uses proofs only to justify local abstraction refinements and therefore keeps proof size and producer burden far smaller.

## My Notes

<!-- empty; left for the human reader -->
