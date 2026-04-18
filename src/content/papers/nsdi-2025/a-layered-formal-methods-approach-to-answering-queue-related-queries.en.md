---
title: "A Layered Formal Methods Approach to Answering Queue-related Queries"
oneline: "QUASI answers queue-related queries from coarse per-port counts by pruning with a sound abstraction layer and invoking SMT only for the hard residual cases."
authors:
  - "Divya Raghunathan"
  - "Maria Apostolaki"
  - "Aarti Gupta"
affiliations:
  - "Princeton University"
conference: nsdi-2025
tags:
  - networking
  - formal-methods
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

QUASI treats a queue question as an existence problem: does any packet trace consistent with observed per-port input, output, and drop counts make the queried queue property true? It first uses a sound over-approximate layer that can conclusively rule out impossible scenarios, then invokes an exact SMT model only when the coarse layer cannot decide. That combination lets it answer queue-length, burst, and buffer-occupancy questions from SNMP-style counters instead of fine-grained queue telemetry.

## Problem

Operators often need queue-aware answers for debugging, capacity planning, and SLO checking, but production networks usually retain only coarse packet counters per port. Fine-grained queue measurements are expensive to collect continuously, may need specialized hardware, and are unlikely to be available retroactively for the interval an operator cares about. The paper argues that this leaves a practical gap: the useful question is often not "what was the exact queue-length time series?" but rather "could this burst, queue buildup, or latency-inducing backlog have happened at all?"

That question is harder than it first looks. Queue length is correlated with packet counts, but it also depends on latent information that the counters omit: packet arrival order, when departures happened, which input packet went to which output queue, and whether drops occurred after prior buildup. In the paper's formulation, the analyst is really searching over all packet traces consistent with the measurements and asking whether at least one of them satisfies the query. Existing telemetry-inference systems can generate plausible fine-grained signals, but they do not provide the proof-style guarantees needed to rule scenarios out. Generic formal performance analyzers also do not fit the measured-input setting well and become unscalable quickly.

## Key Insight

The paper's central claim is that, for the supported query language, the exact identity of the input port attached to each packet is irrelevant; what matters is the enqueue-rate into each output queue over time. Once the problem is rewritten in terms of enqueue counts per queue and per time step, QUASI can reason about whole families of concrete packet traces at once without losing precision for the queries it supports.

The second insight is to use that abstraction asymmetrically. QUASI's first layer over-approximates the feasible traces and is designed so that a negative answer is definitive: if its representative abstract traces cannot be made consistent with the input counts, then no concrete trace can satisfy the query either. Only positive answers need refinement. That gives the system a practical abstraction-refinement structure with one-sided safety: no false negatives in the fast layer, and no false positives once the exact layer runs.

## Design

QUASI supports queries over three metrics: instantaneous enqueue rate `enq`, cumulative enqueue rate `cenq`, and queue length `qlen`, with bounded quantification over time and queues. The first layer, `QUASI-1`, has three steps. First, the cover-set generator derives necessary conditions from the query and from per-port output and drop counts. For queue-length questions, it uses packet conservation to turn a condition like "queue `q` reaches at least `K` packets" into lower bounds on cumulative enqueues after accounting for possible initial occupancy, minimum dequeues, and drops. The result is a finite disjunction of constraint sets, each describing a family of abstract traces that might satisfy both the query and the measured outputs.

Second, the most-uniform abstract-trace constructor picks one representative abstract trace for each cover-set component. "Most-uniform" is the crucial structural notion: among all traces satisfying the component's lower and upper bounds, QUASI places packets into the lowest-height columns possible, producing the least bursty representative that still satisfies the constraints. The paper proves that if even this representative cannot be labeled so as to respect the observed input counts, then no more uneven trace in the same component can work either. That theorem is the reason the first layer can discard entire regions of the search space without enumerating traces.

Third, the matrix-based consistency checker reduces the labeling problem to pure combinatorics. After summing each time step's total enqueue count, QUASI asks whether there exists an `N x T` binary matrix whose row sums match per-input-port counts and whose column sums match the representative trace. By invoking the Gale-Ryser theorem, it answers that question efficiently instead of searching over all possible packet-to-input assignments.

`QUASI-2` is the exact fallback. It encodes switch dynamics and the query into SMT and asks Z3 for satisfiability. The important engineering win is that QUASI keeps the enqueue-rate abstraction here as well, so the exact layer needs `O(NqT)` variables instead of `O(NNqT)` variables for a full packet-trace encoding. Because the query language never distinguishes packets in a queue by their source input port, the paper argues that this abstraction is lossless for its setting.

## Evaluation

The evaluation uses ns-3 with a star topology around an 8-port switch, per-output-port queue capacity of 250 packets, total buffer size of 2000 packets, and 25 monitoring intervals of 100 time steps each. The authors also test a much larger SLO-checking scenario with 8 Gbps links, 1 KB packets, and 5-minute intervals corresponding to 300 million time steps.

The most practically compelling result is the SLO case study. To check whether queueing latency could have violated a 289 microsecond objective, the authors ask whether any port could have reached 290 queued packets. QUASI proves compliance on every 5-minute interval and does so in 0.03 seconds total, while the heuristic baseline reports violations everywhere. That result directly supports the paper's pitch: coarse counters can still certify that a bad queueing event did not happen.

For burst queries, QUASI's first layer alone is already strong. On 25 intervals where the tested burst could not have occurred, `QUASI-1` rejects all cases in under a second each, while the heuristic baseline produces 14 false positives. For quantitative questions, the system runs a binary search over Boolean queries. `QUASI-1` finds upper bounds on maximum queue length and maximum buffer occupancy within about a second per interval, with average relative error 0.25 versus the exact answer, and the bounds are up to 58% tighter than the heuristic's. `QUASI-2` then finds exact maxima within 25 minutes for queue length and 15 minutes for buffer occupancy.

Against FPerf, the comparison is stark even after shrinking the interval to 10 time steps so FPerf sometimes finishes. QUASI computes maximum queue length about `10^6` times faster in the paper's headline result: FPerf averages 8.5 hours where QUASI takes under a second, and FPerf does not support the burst query at all. On maximum buffer occupancy, FPerf still fails to complete all needed subqueries within a day and can return an upper bound roughly 9x larger than the exact value.

## Novelty & Impact

The novelty is not merely that the paper uses SMT on a networking problem. The interesting move is the full pipeline around the solver: a lossless enqueue-rate abstraction for the supported queries, a cover-set formulation that exposes necessary conditions, a proof that most-uniform representatives are enough for negative reasoning, and a matrix-theoretic check that avoids explicit label search. That combination turns cheap counters into a formal reasoning substrate rather than just a rough signal for estimation.

I expect the paper's main impact to be on network operations and telemetry systems that cannot justify always-on fine-grained queue instrumentation. QUASI does not replace direct measurement when such measurement exists, but it shows that even coarse measurements can support meaningful proofs of possibility or impossibility. It also broadens the scope of formal methods in networking from control-plane correctness toward measured performance diagnosis.

## Limitations

The paper's guarantees are tied to its model and query language. QUASI focuses on single-switch queries and only supports properties expressible through `enq`, `cenq`, and `qlen`; for multi-switch paths, the paper only sketches decompositions such as summing per-switch latency bounds. If an operator needs richer packet semantics or cross-device causal properties, the current abstraction is too narrow.

Scalability is also uneven across query classes. Queue-length checks can stay almost constant-time because the first layer often prunes early, but burst queries scale much worse: the paper reports about 75 minutes for `BurstOccurrence` at 60,000 time steps. More broadly, the evaluation is entirely simulation-based and centered on randomized UDP traffic over a single-switch topology. That is enough to demonstrate feasibility and the asymptotic behavior of the reasoning stack, but not enough to show robustness on messy production traces or on hardware with queueing behavior that deviates from the assumed model.

## Related Work

- _Arashloo et al. (NSDI '23)_ - `FPerf` performs formal network performance analysis by synthesizing workloads, while `QUASI` answers trace-existence questions under observed per-port counts and adds a sound fast path before invoking exact solving.
- _Gong et al. (SIGCOMM '24)_ - `Zoom2Net` imputes fine-grained telemetry from coarse measurements, whereas `QUASI` gives formal yes/no and bound answers without claiming to reconstruct the exact hidden queue trace.
- _Geng et al. (NSDI '19)_ - `SIMON` infers queueing delay from measurements, while `QUASI` reasons over the entire space of count-consistent traces and can certify that some queue scenarios never happened.
- _Lei et al. (SIGCOMM '22)_ - `PrintQueue` measures queue behavior directly in the dataplane, whereas `QUASI` is useful specifically when fine-grained queue instrumentation is unavailable and only SNMP-style counters remain.

## My Notes

<!-- empty; left for the human reader -->
