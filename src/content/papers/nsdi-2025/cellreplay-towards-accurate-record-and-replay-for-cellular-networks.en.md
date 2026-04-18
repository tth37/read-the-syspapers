---
title: "CellReplay: Towards accurate record-and-replay for cellular networks"
oneline: "CellReplay records cellular links under synchronized light and heavy workloads, then interpolates between their traces to replay app performance with much less bias than Mahimahi."
authors:
  - "William Sentosa"
  - "Balakrishnan Chandrasekaran"
  - "P. Brighten Godfrey"
  - "Haitham Hassanieh"
affiliations:
  - "University of Illinois Urbana-Champaign"
  - "VU Amsterdam"
  - "Broadcom"
  - "EPFL"
conference: nsdi-2025
category: wireless-cellular-and-real-time-media
code_url: "https://github.com/williamsentosa95/cellreplay"
tags:
  - networking
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CellReplay argues that accurate cellular record-and-replay needs more than one saturating trace. It records a light packet-train trace plus a heavy saturator trace, separately tracks time-varying base delay, and interpolates between the two during replay. Across web browsing, file downloads, and adaptive bitrate streaming, that cuts replay bias substantially relative to Mahimahi.

## Problem

Evaluating applications on real cellular networks is slow, expensive, and hard to reproduce. Throughput and latency vary with signal strength, interference, mobility, and operator behavior, so repeated live trials are necessary just to get stable numbers. That is why systems papers and app developers often fall back to record-and-replay emulation: record one trace in the wild, replay it locally, and compare application behavior under supposedly identical network conditions.

The paper shows that the standard modern version of this idea, Mahimahi-style replay, is systematically wrong for cellular networks. Mahimahi records packet delivery opportunities, or PDOs, by saturating the link with MTU-sized packets and then replays those opportunities later with a fixed propagation delay. The authors demonstrate two failure modes. First, cellular base RTT is not fixed. Even under good stationary conditions, Mahimahi underestimates median RTT by 16.88% on T-Mobile and 13.25% on Verizon, because PDO gaps only partially encode delay variation and sparse application traffic can miss those blackout periods entirely. Second, available delivery rate depends on workload. In one Verizon measurement, a 100-packet train sees 2.6x the delivery rate of a 10-packet train, and train completion times can deviate by up to 35.8% from what the saturator's bandwidth would predict. A single heavy trace therefore makes light and bursty workloads look too fast.

That bias is not cosmetic. The paper reports a 17.1% average page-load-time error for web browsing and a 49% error for 250 KB file downloads under Mahimahi. Worse, this can change experimental conclusions, as shown later in the paper's ABR case study. The core problem is that cellular networks expose both time-varying delay and workload-conditioned bandwidth, while prior replay tools effectively pretend that one heavy probe can stand in for every application.

## Key Insight

The paper's central claim is that faithful black-box replay does not require modeling the operator's scheduler, but it does require separating two phenomena that Mahimahi conflates. Base delay should be recorded directly as a time series, because it changes over time even for sparse traffic. Delivery opportunities should be recorded under more than one workload, because the network allocates bandwidth differently to short bursts and long trains.

CellReplay therefore records two representative workloads at the extremes. A light packet-train probe captures RTT and early-train delivery behavior without forcing the link into full heavy mode. A saturator captures the heavy-workload PDOs that long transfers eventually experience. Replay then starts each burst on the light trace, transitions into the heavy trace as the packet sequence grows, and falls back to the light regime after an idle gap. The claim is not that every cellular scheduler is linear; it is that many real application flows can be approximated well enough by interpolating between these two boundary conditions.

## Design

CellReplay's recording phase gathers three traces: base delay, light PDOs, and heavy PDOs. One phone runs the packet-train probing workload. Every `G` milliseconds, the client sends `U` back-to-back MTU-sized packets uplink; when the server receives the first packet, it responds with `D` back-to-back MTU-sized packets downlink. The receiver-side arrival offsets of these trains form the light PDO traces, while the time from the first uplink send to the first downlink receive yields the current RTT sample, which CellReplay halves into a one-way base delay estimate. A second phone runs a saturator that continuously requests bandwidth beyond the bottleneck rate and records the heavy PDO trace. The two-phone design matters because a single-device saturator would inflate queues and corrupt the light-workload measurements; the authors rely on per-user queue separation in commercial networks and validate that the phones still see distinct light and heavy behavior.

Replay runs inside a Mahimahi-style shell but changes the control logic. CellReplay has inactive and active states. When the first packet of a new burst arrives at replay time `t`, the emulator looks up the most recent base-delay sample and light-PDO sample at or before `t`, interpolating delay between samples when needed. It then constructs a temporary PDO schedule by shifting the light PDOs by the current delay and concatenating the suffix of the heavy PDO trace after the light schedule ends. Each packet is delayed by that base delay plus a packet-size compensation term `comp(s)`, because the paper measured RTT differences across packet sizes that are much larger than pure serialization time would explain. After delay, packets enter a byte queue serviced according to the temporary PDO schedule. If the queue stays empty for `F` milliseconds, CellReplay returns to the inactive state so the next burst starts again from a fresh light-workload trace instead of remaining stuck in heavy mode.

The remaining challenge is parameter selection. The paper calibrates the light train sizes `U` and `D` by running randomized packet-train experiments and choosing the train size whose combined light-plus-heavy estimate minimizes interpolation error across other train lengths. It derives `Gmin`, the smallest safe gap between trains, by shrinking the inter-train gap until the observed train-completion behavior stops matching a truly light workload. It then infers the fallback timer `F` from the gap needed for the queue to drain, measures `comp(s)` using randomized packet-size RTT tests, and estimates the replay queue size `B` using a standard max-min bottleneck-buffer method.

## Evaluation

The evaluation is careful and appropriately skeptical. The authors compare live-network behavior against replayed behavior using randomized trials, the same client and server machines, and a geographically close server to minimize unrelated Internet-path noise. They normalize Earth Mover's Distance by the live mean to obtain an application-level distribution error. The workloads include web-page loads over HTTP/1.1 and HTTP/2, random file downloads from 1 KB to 10 MB, and the startup phase of three adaptive bitrate streaming algorithms. They test T-Mobile and Verizon 5G, plus good stationary conditions, weak signal, crowded spaces, walking, and driving.

At the microbenchmark level, CellReplay closely tracks live RTT distributions, while Mahimahi persistently underestimates them. For web browsing, CellReplay reduces mean emulation error from 17.1% to 6.7% across the tested pages and protocols. For small file downloads, it drops mean errors from 8.4%-20.7% to 0.5%-3.5% on T-Mobile and from 7.9%-49% to 0.2%-22.4% on Verizon. For medium files, its mean distribution error is 9.14% for 1 MB downloads and 6.54% for 10 MB downloads, versus 23.35% and 17.06% for Mahimahi. These results support the paper's main argument: variable delay plus workload-aware PDO interpolation is much closer to live cellular behavior than replaying one saturator trace.

The robustness results are also useful because they show where the design bends. In a basement and a crowded library, CellReplay cuts error from 15.22% to 5.74% and from 22.51% to 8.47%, respectively. Under mobility, it still beats Mahimahi, reducing walking error from 14.48% to 4.13% and driving error from 13.15% to 6.97%, though the gap narrows because driving introduces handover-related drops that CellReplay does not explicitly model. The ABR use case is especially convincing: Mahimahi overestimates startup bitrate by 17.73% on average and incorrectly makes BOLA look far better than BB, while CellReplay reduces that bias to 5.89% and preserves the live-network ordering much more closely.

## Novelty & Impact

The novelty is not a new congestion-control algorithm or a white-box model of the radio access network. It is a black-box replay substrate that explicitly acknowledges two facts about cellular networks: delay varies over time, and bandwidth allocation depends on the workload that asked for it. Mahimahi captured the first practical wave of record-and-replay for HTTP, but CellReplay shows that its single-saturator assumption is too coarse for modern cellular evaluation. Pantheon-style calibrated emulators also differ philosophically: they tune fixed parameters to mimic a path, whereas CellReplay replays measured time-varying traces with a workload-conditioned switch between light and heavy service regimes.

That makes the paper important for anyone evaluating cellular transports, mobile applications, or adaptive application logic such as ABR. The open-source release of both code and traces lowers the barrier to reuse. More broadly, the paper is a warning to the community that convenient replay setups can introduce directional bias, not just harmless noise.

## Limitations

CellReplay still simplifies the network in important ways. It does not record and replay random packet losses except those induced by queue overflow or manually configured drop rates, so it is weaker under mobility regimes where handovers cause actual IP-level drops. The calibration parameters are fixed before each recording session, which means a trace may age poorly if the environment changes materially during a long run.

The two-phone setup is also a compromise rather than a clean abstraction. Under mobility, the phones can briefly attach to different base stations or hand over at slightly different times, and the authors report that this happened during driving experiments. Finally, the recorder uses UDP probes, so it cannot capture protocol-specific middlebox behavior such as TCP-specific discrimination. Residual interpolation error on larger flows, especially on Verizon, shows that two boundary workloads are a strong approximation, not a full model of provider internals.

## Related Work

- _Netravali et al. (USENIX ATC '15)_ - Mahimahi made practical HTTP record-and-replay mainstream, and CellReplay is best understood as a cellular-specific fix for Mahimahi's single-saturator replay assumption.
- _Noble et al. (SIGCOMM '97)_ - The original trace-based mobile emulation paper established the record-and-replay idea, but it targeted much older wireless environments without modern 4G/5G workload dependence.
- _Mishra et al. (CCR '21)_ - NemFi is also a record-and-replay emulator, but it is tailored to WiFi frame aggregation rather than cellular path dynamics and workload-conditioned bandwidth allocation.
- _Yan et al. (USENIX ATC '18)_ - Pantheon calibrates parameterized emulators from traces, whereas CellReplay replays measured delay and delivery opportunities directly and lets the workload determine when to switch regimes.

## My Notes

<!-- empty; left for the human reader -->
