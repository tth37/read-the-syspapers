---
title: "Introspective Congestion Control for Consistent High Performance"
oneline: "ICC shapes delay oscillations into a detectable profile, then trusts base-RTT and bandwidth inferences only when FFT-based introspection says the path is stable."
authors:
  - "Wanchun Jiang"
  - "Haoyang Li"
  - "Jia Wu"
  - "Kai Wang"
  - "Fengyuan Ren"
  - "Jianxin Wang"
affiliations:
  - "Central South University"
  - "Tsinghua University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696084"
code_url: "https://github.com/Wanchun-Jiang/ICC-Introspective-Congestion-Control-for-Consistent-High-Performance"
tags:
  - networking
  - datacenter
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ICC starts from a simple complaint about modern congestion control: probing for base RTT or bandwidth is useful only if the sender knows those probes are being run in a stable regime where the path is not already changing underneath it. The paper's answer is to sculpt a symmetric delay-oscillation profile, detect that profile with FFT over recent standing-RTT samples, and trust path-condition inferences only when the profile remains stable. Across emulation, Internet testbeds, and an Alipay QUIC deployment, that discipline preserves high throughput while lowering queuing delay.

## Problem

The paper argues that wrong path-condition inference, not just slow reaction, is the main reason one congestion controller rarely performs well everywhere. Classic schemes increasingly rely on proactive inference: BBR tries to learn bottleneck bandwidth and base RTT through `ProbeBW` and `ProbeRTT`, while Copa periodically sculpts the queue so it can infer the base RTT from drains. Those mechanisms work when the probing actions have the intended effect and the path stays stable long enough for the inference to remain valid. They fail when bandwidth, flow count, or loss is already changing, or when the probing action itself perturbs the measurement. In those cases, the inferred quantity becomes stale or simply wrong, and the subsequent rate adjustment is misled.

That problem matters because the target environments vary wildly. The same controller may face microsecond-scale datacenter RTTs, second-scale satellite RTTs, wireless random loss, and mixes of short and long flows. Learning-based controllers try to smooth over that variability, but they bring training cost, opaque behavior, and risk on unseen scenarios. The paper therefore wants a hand-designed controller that still behaves consistently across regimes.

## Key Insight

The core idea is to make inference conditional on self-observation. ICC deliberately shapes its rate-adjustment rules so that, under unchanged path conditions, the bottleneck queue oscillates symmetrically and periodically around a low equilibrium point. That oscillation leaves a recognizable projection in the frequency domain: a stable dominant component in the recent delay time series. If the sender sees the same dominant frequency and roughly the same average RTT across consecutive FFT windows, it has evidence that the controller, rather than exogenous path changes, is dominating the signal.

Once that projection is present, ICC can probe safely for `RTTbase` and for `C/N`, the bottleneck capacity divided by the number of competing flows. If the projection disappears, ICC stops trusting fresh inferences and falls back to fast congestion response using the last credible values. In other words, the paper turns path inference from an always-on guess into a gated operation backed by an internal consistency check.

## Design

ICC is built around standing RTT samples. It defines queuing delay as `Qd = RTTstanding - RTTbase` and chooses a target sending rate through a logarithmic function of `Qd`, with two tunable parameters: `Bd`, which bounds the desired queueing regime, and `Rc`, which sets the rate scale. The actual update rule is symmetric: if the current rate is below the target, increase it; if above, decrease it by the same shaped amount. That symmetry is what produces the paper's desired low-amplitude periodic queue oscillation in stable conditions.

The controller has four interacting modules. First, the profile-sculpting module is just that symmetric rate law. Its stated purpose is not only good steady-state behavior, but also creating a detectable signature. Second, the projection monitor runs FFT on recent `RTTstanding` samples. ICC initially uses a long window, then shortens it based on the dominant frequency once a stable oscillation appears. A projection is considered credible when consecutive FFT windows show similar dominant frequency and similar average RTT, which means both the oscillation shape and the equilibrium point are holding.

Third, the proactive-probe module regulates the step size `lambda` with an AIMD rule. When the path is stable, ICC gradually enlarges the queue oscillation until it reaches the current `RTTmin` estimate; if the path reveals an even smaller RTT, that estimate is updated. The same process makes the final `lambda` reflect `C/N`, because the oscillation amplitude converges to the equilibrium point. Once the probe succeeds, ICC halves the amplitude to return to a lower-delay operating region while recording the useful step size for later. Fourth, the fast-response module regulates `theta`: if the sender has been increasing for more than two RTTs, `theta` doubles each RTT to grab available bandwidth quickly; otherwise it resets to one. When the projection is absent, ICC freezes `RTTmin` and the recorded `lambda` from the last credible stable period, so it still reacts quickly without trusting new bad inferences.

The paper also adds a competition mode for coexistence with buffer-filling schemes such as Cubic. ICC compares the spectral and temporal behavior of RTT and `cwnd`; if the two diverge sharply, or the queuing delay exceeds the controller's own bound, ICC infers that another flow is inflating the queue. It then raises its equilibrium point and adopts a Cubic-like multiplicative decrease on loss so that it can share bandwidth more fairly.

## Evaluation

The evaluation is broader than most congestion-control papers and it mostly exercises the paper's claimed advantage: changing conditions. ICC is implemented in NS3, in Linux userspace, and in QUIC for a production platform. On real Internet links using Pantheon across Amsterdam, Frankfurt, Toronto, and Seoul, ICC delivers higher throughput than BBR by 20.4%, Copa by 27.4%, Cubic by 31.1%, Indigo by 10.1%, Remy by 24.1%, Vegas by 48.1%, and PCC-Vivace by 15.3%, while also keeping low average queuing delay and relatively small tail latency.

The more diagnostic results explain why. In heterogeneous-RTT emulation, ICC infers `RTTbase` correctly while Copa updates its minimum RTT incorrectly after the path changes. Across a wide range of BDPs, ICC shows the best throughput-delay tradeoff among the hand-designed baselines the paper emphasizes. Under 1%-10% random loss, ICC, BBR, and Copa maintain nearly full utilization, while Cubic, Orca, and Vivace lose substantial throughput because they overreact to non-congestion loss. In flow-arrival experiments, ICC also converges faster and more smoothly to fairness than Cubic, BBR, and Copa.

The paper's strongest application numbers come from the edge regimes. In the datacenter-style web-search workload, ICC reduces flow completion time by about 9.9x for flows shorter than 64 KB compared with DCTCP, essentially matching Copa's low-latency behavior while adapting its step size to available bandwidth. On the Alipay QUIC deployment, ICC keeps throughput similar to BBR and above Cubic, but pushes 80% of observed queuing delays below 152 ms, which is 22.8% lower than BBR and 40.6% lower than Cubic; at the 90th percentile cutoff, the reductions are 13.1% and 26.5%. Those are strong results for the paper's main claim, though some scenarios, such as satellite links, show ICC winning mainly on delay rather than on absolute best throughput.

## Novelty & Impact

The novel move is methodological. BBR and Copa already use proactive actions to infer hidden path variables, and learning-based work already tries to generalize across networks. ICC's contribution is to make the controller shape its own signal first, then use that shaped signal to decide whether inference is trustworthy. That is a more interpretable design than training a model to internalize the same judgment, and a more disciplined design than always trusting probe outcomes.

That makes ICC interesting even beyond this specific algorithm. The paper is really proposing a design pattern for end-to-end control: embed inference inside a self-checkable dynamical profile, and decouple "is the path stable enough to measure?" from "how should I react?" Future controllers could borrow that idea even if they do not keep ICC's exact logarithmic target rate or FFT implementation.

## Limitations

The main limitation is that ICC needs time and signal quality to introspect. The paper explicitly says that when paths change too quickly or flows are too short, there may not be enough time to distinguish the projection. In those cases, ICC effectively degrades into a more ordinary delay-based controller that responds quickly but does not gain the benefit of fresh trustworthy inference. That softens the failure mode, but it also means ICC's signature idea helps least on the shortest transfers.

The controller also relies on delay measurement quality and on a fairly coherent shared bottleneck view. The authors note that if base RTTs differ by a very large amount, flows observe bottleneck variation on different timescales, and all congestion controllers struggle. Competition mode is also heuristic: it depends on fixed thresholds for spectral distance and delay/cwnd mismatch, and the TCP-friendliness argument is empirical rather than derived. Finally, the proofs use simplified queueing assumptions, and the implementation adds per-flow FFT state and computation, even if the paper argues that overhead is bounded.

## Related Work

- _Arun and Balakrishnan (NSDI '18)_ - Copa also sculpts delay behavior to infer `RTTbase`, but ICC adds an explicit introspection step so the sender checks whether the sculpted profile is actually present before trusting the inference.
- _Cardwell et al. (CACM '17)_ - BBR proactively probes for bandwidth and base RTT, whereas ICC's central claim is that those probe results should be gated by a credibility test derived from the delay signal itself.
- _Dong et al. (NSDI '15)_ - PCC pursues consistent performance by optimizing empirical utility directly, while ICC keeps a hand-designed controller whose inferences stay interpretable and mechanically checkable.
- _Abbasloo et al. (SIGCOMM '20)_ - Orca uses learning to generalize across network regimes; ICC instead pursues the same consistency goal with a lightweight introspective mechanism and no training loop.

## My Notes

<!-- empty; left for the human reader -->
