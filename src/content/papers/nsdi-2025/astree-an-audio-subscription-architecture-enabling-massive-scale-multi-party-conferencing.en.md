---
title: "AsTree: An Audio Subscription Architecture Enabling Massive-Scale Multi-Party Conferencing"
oneline: "AsTree replaces full audio subscription with an SFU tree that forwards only hop-by-hop dominant speakers, removing most large-room audio signaling storms."
authors:
  - "Tong Meng"
  - "Wenfeng Li"
  - "Chao Yuan"
  - "Changqing Yan"
  - "Le Zhang"
affiliations:
  - "ByteDance Inc."
conference: nsdi-2025
tags:
  - networking
  - datacenter
  - scheduling
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

AsTree replaces Lark's old `FullAud` design, where every participant is pre-subscribed to every remote audio stream, with a two-hierarchy SFU tree and hop-by-hop dominant-speaker selection. Each media server forwards only a small bounded set of loud streams and initiates delivery from the media plane rather than via room-wide audio signaling. That turns large-room audio from an `O(N^2)` subscription problem into a bounded forwarding problem and improves both capacity and QoE in production.

## Problem

The motivation is operational, not theoretical. After Lark improved video QoE with simulcast, audio stalls became the largest complaint category in post-call feedback. The paper argues that audio subscription is harder than video subscription in three specific ways. First, who needs to hear which video is partially driven by UI and explicit user actions, but audio is reactive: anyone may start speaking without warning. Second, waiting for an `unmute` event and then establishing subscription is too slow for speech, because the signaling round trip can clip the beginning of an utterance. Third, unlike video, audio has no natural UI-imposed bound on fanout, since every participant may become a speaker.

Lark's early answer was `FullAud`: subscribe everyone to everyone's audio when they join, keep muted participants publishing DTX frames, and use mute/unmute broadcasts only to update the displayed status. That choice amortizes subscription setup but scales badly. Join bursts and mute/unmute events create signaling storms at local signaling units; clients waste bandwidth, CPU, memory, and battery on many silent or irrelevant streams; and servers pay `O(N^2)` edge fanout plus high inter-server WAN cost. The paper gives a simple bandwidth sanity check: on mobile, a focus video plus thumbnail needs about 0.82 Mbps, so more than 12 simultaneous unmuted speakers can already exceed the bandwidth of subscribed video, and more than 100 muted DTX streams are still material. In other words, audio, not video, becomes the bottleneck in the very large rooms that matter most.

## Key Insight

At any instant, most useful conference audio comes from a very small set of dominant speakers. The paper's real insight is not just to exploit that sparsity, but to place the selection logic in the media plane and do it hop by hop. If every SFU chooses the loudest streams among what it receives locally and from neighboring SFUs, then the system can bound per-link fanout, avoid new signaling round trips, and avoid a centralized selector that would become both a compute bottleneck and a single point of failure.

The authors describe this as moving from "select before distribute" to "select before forward." A stream should be filtered as early as possible on every hop, not forwarded everywhere and pruned only at the edge. That is what makes the WAN and server-side savings real rather than cosmetic.

## Design

The architecture keeps Lark's existing split between user plane, media plane, and logically centralized control plane, but changes the audio topology. Participants attach to nearby SFU media servers. Within each region, the first media server in that region to join a room becomes the region delegate; later servers in the same region cascade to it. Across regions, the delegates are connected by a spanning tree. The paper discusses optimization objectives such as minimizing the longest path RTT, but the deployed system uses a simpler heuristic: select one master delegate and connect the other region delegates directly to it. This is deliberately cost-effective and stable rather than globally optimal.

That stability choice matters. As participants join and leave, AsTree tries not to tear down and rebuild established cascading links. Region delegates usually remain delegates until their region becomes empty, and the master delegate changes only when latency would otherwise exceed an empirical threshold. The design accepts a modest amount of suboptimality to reduce operational churn and failover complexity.

Audio selection is fully decentralized. Each media server considers two input sets: audio streams from its directly connected participants and streams received from cascading neighbors. A selected stream is never sent back toward its source. To identify dominant speakers, AsTree uses RTP audio-level metadata rather than decoding raw audio. Each stream keeps a 15-packet ring buffer, roughly 300 ms of recent history; the server updates weighted audio-level samples every 5 packets and reruns selection every 50 ms. The algorithm first pre-selects at most `Li` loud candidates, then uses an `extraCushion` threshold and a minimum `smoothTime` residency to avoid rapid speaker flapping. The deployment defaults are `Li = 4` and `L = 10`. Streams whose audio level is 127, meaning silence, are excluded.

The control-plane simplification is equally important. AsTree does not broadcast audio `Publish` events. Instead, media servers cache incoming SDP offers; when a new active speaker is selected, the server sends an updated SDP answer to downstream servers or participants and immediately starts forwarding RTP. Join messages can be aggregated once the room is large, and mute/unmute broadcasts disappear entirely. UI mute state is therefore derived from whether a participant's audio stream is currently selected, not from their last button click.

## Evaluation

The evaluation mixes stress tests with production deployment, which is appropriate for an operational systems paper. On the client side, the authors use a Redmi Note 13 joining rooms with controlled participants that publish only audio. Under `FullAud`, CPU and memory grow nearly linearly even when those remote participants are muted, because the phone still receives and processes their DTX streams. With 50 muted participants, AsTree cuts client CPU by 64% and memory by 17% relative to `FullAud`.

On the server side, the benchmark setup uses three participant types: active talkers with camera and microphone, silent-but-unmuted participants, and fully muted audience members. This is the right workload for the paper's claim, because the whole point is that non-speaking participants dominate large rooms. In a single-region single-server experiment, AsTree scales roughly linearly while `FullAud` does not. At 125 participants, AsTree uses 80.9% less CPU and 89.5% less memory, which the paper translates to 5.2x more conferences per server. The signaling results are equally important: with participants arriving in bursts of 50 per second, `FullAud` spikes to about 75% CPU and crashes at 150 participants, while a 1000-participant AsTree room shows no comparable join spike.

QoE follows the resource story. In the benchmark, AsTree keeps all audio and video frames within 200 ms encode-to-decode latency even at 800 participants. `FullAud` at only 125 participants gets just 0.014% of audio frames and 51.6% of video frames under the same 200 ms threshold. Audio stall reaches zero only up to 25 participants under `FullAud`, but remains zero for AsTree at 800 participants; video stall is lower by nearly two orders of magnitude than `FullAud` at 125 participants. The paper notes that DTX frames are included in the audio-latency accounting, which makes `FullAud` look especially bad, but the video results tell the same qualitative story.

The strongest evidence is the rollout. From August 2021 through January 2022, across more than 100 million conferences, median audio-stall ratio fell by more than 30% and the 95th percentile by more than 45%; median and tail video-stall ratios both dropped by more than 50%; and negative reviews fell by about 40%. The extra indirection of the tree appears modest in practice: compared with other ByteDance RTC applications, Lark increased cascading links per subscribed stream by only 5.7%.

## Novelty & Impact

The novelty is not the existence of dominant-speaker selection by itself. Prior systems and products already rely on some form of loudest-speaker logic. What AsTree adds is a complete deployable architecture that combines a two-hierarchy cascading tree, distributed hop-by-hop audio selection, and the removal of audio-specific control-plane broadcasts. The paper is strongest where many systems papers are weakest: it explains why seemingly obvious alternatives are operationally unattractive, and then shows the deployment behavior of the mechanism that actually shipped.

That makes the paper useful to two audiences. RTC architects get a concrete design for scaling audio separately from video. Systems researchers get one of the clearest large-scale reports on how conferencing backends fail in practice when audio is still treated as an afterthought.

## Limitations

AsTree depends on the empirical fact that only a small number of speakers matter at once. If many people speak simultaneously, the system still scales, but the quality of selection depends much more on loudness as a proxy for importance. A quieter but semantically important speaker can lose to a louder one. The authors also accept a UI mismatch: silent unmuted users may appear muted because display state follows current selection rather than button state.

The topology algorithm is also intentionally heuristic. "First-come" region delegates and a single master delegate keep implementation and failover simple, but they are not globally optimal and can miss better routes as room composition changes. The paper explicitly leaves dynamic topology deformation and richer optimization objectives to future work. Finally, the evidence is compelling for Lark, but it is still one product's workload, network footprint, and engineering stack; the paper does not prove that the same constants or heuristics will transfer unchanged to other RTC systems.

## Related Work

- _Volfin and Cohen (Computer Speech & Language '13)_ - Early dominant-speaker identification used richer speech features, whereas AsTree must work from RTP metadata at SFUs without decoding audio.
- _Grozev et al. (NOSSDAV '15)_ - `Last N` limits dominant-speaker video forwarding, but it does not redesign audio subscription around hop-by-hop pruning.
- _Lin et al. (SIGCOMM '22)_ - `GSO-Simulcast` centrally orchestrates video simulcast streams; AsTree argues that audio needs a separate, media-plane-driven topology because any participant can speak at any time.
- _Bothra et al. (SIGCOMM '23)_ - `Switchboard` improves conferencing resource provisioning, while AsTree reduces the per-room workload that the provisioner must absorb in the first place.

## My Notes

<!-- empty; left for the human reader -->
