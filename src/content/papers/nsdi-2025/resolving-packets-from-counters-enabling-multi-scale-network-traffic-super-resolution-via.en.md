---
title: "Resolving Packets from Counters: Enabling Multi-scale Network Traffic Super Resolution via Composable Large Traffic Model"
oneline: "ZOOMSYNTH reconstructs packet-level or intermediate traffic traces from coarse counters by cascading per-scale transformers and optionally conditioning them on counter rules."
authors:
  - "Xizheng Wang"
  - "Libin Liu"
  - "Li Chen"
  - "Dan Li"
  - "Yukai Miao"
  - "Yu Bai"
affiliations:
  - "Tsinghua University"
  - "Zhongguancun Laboratory"
conference: nsdi-2025
code_url: "https://github.com/wxzisk/ZoomSynth_NSDI2025"
tags:
  - networking
  - observability
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

This paper introduces `ZOOMSYNTH`, the first system that tries to recover fine-grained network traffic traces from coarse counter traces rather than from packet captures. Its core `CLTM` model decomposes super-resolution into a tree of per-scale `GTT` modules, optionally conditions generation on counter rules such as ACLs, and reaches packet-synthesis quality that is close to or better than prior packet-input generators on several metrics. On an 8x A100 server, the system also meets the paper's real-time target for second-level inputs.

## Problem

The paper starts from an operational asymmetry. Fine-grained traces are useful for evaluating congestion control, packet schedulers, telemetry algorithms, anomaly detectors, service recognizers, and network digital twins, but obtaining them directly is hard because packet capture stresses devices, exposes confidential behavior, and creates privacy concerns. In contrast, byte and packet counters are already exposed by almost every router, switch, or software data plane and are easy for network management systems to collect.

The gap is that counters are too coarse. Typical production collection happens on the scale of seconds, tens of seconds, or minutes, while many downstream uses need sub-second or packet-level structure. Existing traffic synthesizers also do not solve this problem: prior work such as NetShare assumes packet traces as input, while image-super-resolution style approaches inherit the wrong inductive bias because traffic is a time series, not a pixel grid. The paper argues that TSR has three hard properties at once: the input/output representations differ, the upscaling ratio can be as large as `10^9` from 1 second to 1 nanosecond, and different environments such as ISPs, data centers, and access networks can share similar coarse counters while having very different fine-grained behavior.

That combination makes the naive alternatives fail for different reasons. A single large model has to learn every granularity transition at once, diffusion models built for images impose artificial spatial structure, and pure rule-free generation cannot honor the ACL-style semantics that operators often use to decide which traffic gets counted in the first place.

## Key Insight

The central insight is that a coarse counter is not just a blurry observation of packets; it is a recursive summary of many finer counters. A 1-second counter summarizes ten 100 ms counters, each 100 ms counter summarizes ten 10 ms counters, and so on. If the data naturally forms a tree of aggregation relationships, the model should follow that tree instead of trying to jump directly from seconds to packets.

That leads to `CLTM`, a compositional model built from many `Granular Traffic Transformer` (`GTT`) stages. Each `GTT` learns only one local upscaling step, such as `1s -> 100ms` or `10ns -> 1ns`, so it can focus on traffic structure at that resolution rather than learning the whole end-to-end transformation at once. The paper then adds two control mechanisms around that core idea: a CLIP-style rule-following model that embeds textual counter rules into the generation path, and LoRA-based fine-tuning so the model can adapt to new traffic domains without retraining everything.

## Design

`ZOOMSYNTH` is organized as six modules: an SR module that runs `CLTM`, a rule interpreter, a GPT-2-based header assembler, a resource scheduler, a task adaptor for downstream uses, and a new-scenario adaptor based on LoRA. The API surface mirrors those roles: `gen_pkts` produces packet traces, `gen_counters` produces intermediate-resolution counters, and `gen_for_task` adds task-specific adaptation for anomaly detection, sketches, or service recognition.

Inside each `GTT`, the authors combine a Transformer with a BiLSTM. The Transformer models long-range temporal structure, while the BiLSTM handles extreme values that a plain Transformer tends to smooth toward the mean. Training also enforces a domain-specific invariant: after a stage upsamples a counter series, aggregating the result back down must recover the input counter. The loss therefore mixes `MSE`, `EMD`, and an augmented-Lagrangian penalty for this counter-equality constraint.

`CLTM` composes those `GTT`s as a tree. For packet synthesis from second-level counters with `k=10`, the tree includes stages such as `1s -> 100ms`, `100ms -> 10ms`, and so on down to `1ns`. The number of `GTT` tasks expands by `k` at each layer so each task still handles a fixed-size input chunk. To guide generation with counter rules, the rule-following model maps both rule text and packet traces into a shared latent space, and its output vector is concatenated into every `GTT` layer. For packet headers, the paper uses an IP2Vec-style embedding for categorical fields and a GPT-2-small generator that reconstructs the five-tuple after `CLTM` has already generated timestamps and sizes.

The systems contribution is not only the model graph. The scheduler pipelines `GTT` stages across GPUs, prioritizes coarser-grained stages first, and prefers data-affine placement on the same GPU as preceding work. The appendix adds a practical early-stop optimization: if an intermediate counter becomes obviously sparse or reaches the finest possible representation, later upscaling stages are skipped.

## Evaluation

The prototype is implemented in Python and PyTorch, and the main evaluation uses a server with `8x NVIDIA A100`, `2x 64-core Xeon Platinum` CPUs, and `2 TB` of RAM. The training corpus combines seven public datasets including TON, CIDDS, UGR16, CAIDA, and MAWI. For the headline packet-synthesis task, the authors use a `CLTM-1.8B` model and compare against NetShare, NetDiffusion, and a single-model Zoom2Net-style baseline.

The main result is that counter-only synthesis is viable. Across four datasets, `ZOOMSYNTH` reduces `EMD` by `69.5%` on average versus Zoom2Net and by `48.4%` versus NetDiffusion, while reducing `JSD` by `49.6%` and `35.6%`, respectively. It is still slightly worse than packet-input NetShare on header-distribution `JSD`, but the gap is small enough that the paper can reasonably claim "comparable" quality despite using much weaker inputs.

The downstream-task results are more persuasive because they test whether the traces are useful rather than merely similar. With only counters as input, fine-tuned `CLTM` improves anomaly-detection accuracy by up to `27.5%` over NetShare and service-recognition accuracy by `9.8%`. For real-time synthesis, the system generates up to `10^9` packets from one second of counters in `0.966` seconds on the 8-GPU server, which satisfies the paper's definition of real-time. Two smaller but telling ablations also matter: using real nanosecond counters, the dedicated header generator beats NetShare's header generation by roughly an order of magnitude in `JSD`; and when a `Deny TCP` rule is provided, the rule-following path cuts leaked TCP traffic in the final packet trace from `42%` to `3%`.

## Novelty & Impact

The paper's novelty is not merely "apply a Transformer to traffic." Its real contribution is to reframe network trace synthesis as a compositional super-resolution problem over nested counter granularities, then build an architecture whose decomposition matches that structure. That is what separates it from NetShare-style packet generators, Zoom2Net-style single-model imputers, and diffusion systems borrowed from image synthesis.

If the approach holds up in broader deployments, it could make fine-grained traces available in settings where packet capture is impossible or politically unacceptable. That matters for researchers who need realistic traces, operators who want failure diagnosis from counters alone, and future network-digital-twin systems that cannot ingest every packet directly.

## Limitations

The strongest practical limitation is cost. The paper's best real-time result uses a `1.8B`-parameter model on `8x A100`, which is a high bar for the operators who are most likely to have counters but not packet traces. The approach also accumulates error across stages, and the paper explicitly shows that approximate `CBF` counters hurt quality, especially for timestamps and packet lengths.

The generated packet headers are also less general than the timing model. The header generator largely reuses values seen in training data, which the authors themselves call out as a generalization problem. More broadly, the downstream tasks are limited to three relatively structured settings, and the paper admits weaker support for stateful protocol behaviors such as congestion-control dynamics, sequence numbers, or switch-buffer evolution. Finally, a reviewer-style concern is that the evaluation is entirely on public datasets and one lab testbed; the paper argues for production relevance, but it does not yet show an operational deployment in a live network-management workflow.

## Related Work

- _Yin et al. (SIGCOMM '22)_ - `NetShare` generates packet traces from packet-level inputs, while `ZOOMSYNTH` works from counters and pushes the synthesis problem back through multiple aggregation scales.
- _Gong et al. (SIGCOMM '24)_ - `Zoom2Net` uses a single Transformer with constraints for telemetry imputation, whereas this paper decomposes TSR into stage-specific `GTT`s and uses the decomposition as the main inductive bias.
- _Jiang et al. (HotNets '23)_ - `NetDiffusion` adapts image-diffusion machinery to traffic generation, and this paper argues that the time-series nature of traffic requires a native architecture instead of image-style folding.
- _Xu et al. (DMLSD '21)_ - `STAN` is an earlier neural traffic generator, but it does not recover traces from coarse counters or provide multi-scale outputs and rule-conditioned synthesis.

## My Notes

<!-- empty; left for the human reader -->
