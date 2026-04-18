---
title: "Tooth: Toward Optimal Balance of Video QoE and Redundancy Cost by Fine-Grained FEC in Cloud Gaming Streaming"
oneline: "Tooth sets FEC redundancy per frame from frame length and predicted loss patterns, cutting cloud-gaming stalls and redundancy cost while raising delivered bitrate."
authors:
  - "Congkai An"
  - "Huanhuan Zhang"
  - "Shibo Wang"
  - "Jingyang Kang"
  - "Anfu Zhou"
  - "Liang Liu"
  - "Huadong Ma"
  - "Zili Meng"
  - "Delei Ma"
  - "Yusheng Dong"
  - "Xiaogang Lei"
affiliations:
  - "Beijing University of Posts and Telecommunications"
  - "Hong Kong University of Science and Technology"
  - "Well-Link Times Inc."
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - fault-tolerance
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Tooth argues that cloud-gaming FEC should be chosen per frame, because short frames need much higher redundancy than long ones under the same packet-loss conditions. It predicts near-future loss rate and loss aggregation at RTCP timescales, then uses frame length plus those forecasts to choose Reed-Solomon redundancy for each encoded frame. On a production platform, that cuts stalls by 40.2%-85.2%, raises video bitrate by 11.4%-29.2%, and reduces redundancy cost by 54.9%-75.0%.

## Problem

Cloud gaming has a tight application-level deadline: if input-to-screen latency rises above roughly 100 ms, players perceive the game as laggy. The authors' field study over more than 60,000 sessions and 66k players shows that downlink video delivery is the dominant bottleneck. Existing recovery methods all miss the real unit of control. Retransmission still adds loss-detection time plus at least one RTT, which is already too expensive in this regime. Existing FEC is mostly coarse-grained: it chooses one redundancy rate for a whole stream, a time window, or a set of GOP positions.

The paper shows why that fails in cloud gaming. Frame length varies dramatically, from 2 packets to more than 80 packets, because of bitrate adaptation and variable-bitrate encoding. Under the same network conditions, small frames can have much higher loss rate in frame (LRIF) than large ones. The authors report small frames with LRIF above 30% while large frames can need only around 2%. Uniform redundancy therefore overprotects large frames, wastes bandwidth, and still leaves small frames unrecovered. Worse, excess redundancy can increase congestion bursts and raise future LRIF, so blindly adding more parity can actually increase stall frequency.

## Key Insight

The key claim is that the sender should target per-frame recovery probability, not stream-level average loss. That probability is shaped by three variables the system can estimate online: frame length, network loss rate, and how concentrated packet losses are across adjacent frames. The paper names the third factor network loss aggregation. Once Tooth predicts the near-future loss pattern, it can assign more redundancy to the rare short frames that are genuinely fragile and less to long frames whose effective LRIF is lower by the law of large numbers. Fine-grained FEC only pays off if it captures both application-level frame structure and transport-level loss structure.

## Design

Tooth splits the problem into a slow module and a fast module so per-frame FEC stays cheap enough for real-time use. The slow module runs when RTCP feedback arrives. It takes recent loss-rate history, recent loss-aggregation history, and a packet-arrival bitmap, then uses a compressed neural model to predict future loss rate and future loss aggregation. Its loss function penalizes underestimation more than overestimation, because missing needed redundancy is worse for QoE than modest overprotection.

The loss-aggregation metric is a useful part of the design. Instead of only counting how many packets were lost, it measures whether losses are spread across many frames or concentrated within a few. That matters because Reed-Solomon recovery cares about how many packets are missing from a given frame, not whether those packets were contiguous on the wire.

The fast module runs once per encoded frame. Its inputs are predicted loss rate, predicted loss aggregation, and current frame length; its output is the frame's redundancy level. The authors use a random forest rather than a larger neural network because the mapping is nonlinear and discontinuous but must execute inside a frame interval. They also partition the training data so different trees do not overfit to one feature. In the deployed system, Tooth sits between the video codec and FEC codec in a WebRTC-based streaming stack, uses Reed-Solomon coding, keeps decision time around 0.7 ms, and keeps FEC encoding below 1 ms.

## Evaluation

The evaluation combines a large production measurement study with a six-week live deployment on a commercial platform. The deployment covers about 2,300 sessions and compares Tooth against RTC-FEC, RTC-FEC+, RL-AFEC, and Hairpin. The main result is that Tooth finds a better operating point than prior FECs rather than merely moving along the same trade-off curve. It reduces stall frequency to 0.49 times per minute, increases delivered video bitrate to 17.8 Mbps, lowers redundancy bandwidth cost by 54.9%-75.0%, and lowers frame-recovery failure rate by 51.9%-89.3% relative to the FEC baselines.

The ablations support the mechanism. Replacing the random-forest fast module with a heuristic raises recovery failures and bandwidth cost, which suggests the frame-level mapping really is too nonlinear for a simple rule. Replacing the neural slow module with simple averaging also hurts accuracy, meaning that future loss aggregation is not captured well by naive smoothing. Tooth's dual-module structure is also materially cheaper than a single large neural model. The paper further shows gains across WiFi and cellular, 2D and 3D games, four ISPs, and intra-city versus cross-city sessions. A smaller controlled study with volunteers also reports better PSNR and VMAF than the next best baseline.

## Novelty & Impact

Relative to prior adaptive FEC work, the novelty is not a new code or another bitrate-loss controller. It is the argument that cloud gaming needs frame-level redundancy tuned by frame length and loss aggregation, plus a deployable split architecture that makes that decision fast enough for production use. That combination makes the paper useful to cloud-gaming platforms, WebRTC/FEC designers, and more broadly to real-time video systems whose current control loops still operate at stream or GOP granularity.

## Limitations

The deployment is convincing but narrow. Tooth is evaluated on one commercial stack built around WebRTC/RTP, H.265 with NVENC, RTCP feedback every 100 ms, and network conditions from one platform's user base in China. The paper does not specify how much retraining or retuning would be needed for different codecs, transport settings, or client mixes.

The system is also not a black-box add-on. It depends on packet-level feedback, a trained model, and integration into the media and network path. Finally, the visual-quality study is much smaller than the field deployment, and Hairpin is a structurally weak baseline for sub-100 ms interaction budgets because retransmission is disadvantaged before implementation details even matter.

## Related Work

- _Holmer et al. (ICIP '13)_ - RTC-FEC chooses redundancy from coarse bitrate/loss heuristics, while Tooth adds frame length and loss aggregation to decide protection per frame.
- _Chen et al. (MMSys '22)_ - RL-AFEC adapts redundancy around GOP-critical frames, whereas Tooth argues that cloud gaming's infinite-GOP, highly variable frames require frame-by-frame control.
- _Rudow et al. (NSDI '23)_ - Tambur uses streaming codes across multiple frames for videoconferencing, while Tooth stays frame-local to avoid delay that would violate cloud-gaming deadlines.
- _Meng et al. (NSDI '24)_ - Hairpin improves retransmission for interactive video, but Tooth argues that cloud gaming still needs proactive FEC because one extra RTT is already too costly.

## My Notes

<!-- empty; left for the human reader -->
