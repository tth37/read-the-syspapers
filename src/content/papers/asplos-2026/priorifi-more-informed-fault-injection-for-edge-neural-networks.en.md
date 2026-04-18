---
title: "PrioriFI: More Informed Fault Injection for Edge Neural Networks"
oneline: "PrioriFI combines a Hessian prior with live fault-injection feedback to surface the most error-sensitive edge-NN bits early and guide reliability co-design."
authors:
  - "Olivia Weng"
  - "Andres Meza"
  - "Nhan Tran"
  - "Ryan Kastner"
affiliations:
  - "University of California San Diego, La Jolla, CA, USA"
  - "Fermi National Accelerator Laboratory, Batavia, IL, USA"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790204"
code_url: "https://github.com/KastnerRG/priorifi"
tags:
  - hardware
  - ml-systems
  - fault-tolerance
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

PrioriFI is a fault-injection scheduler for quantized edge neural networks. It starts from a Hessian-based prior, then keeps reordering future bit flips using the damage already observed in the campaign. That adaptive loop finds high-sensitivity bits earlier than BinFI, StatFI, or Hessian-only rankings.

## Problem

The target setting is harsh edge deployment, not cloud inference. The paper's motivating example is the `ECON-T` ASIC for the High Luminosity Large Hadron Collider, where each neural network must finish inference in `25 ns`, fit in about `4 mm^2`, and tolerate a radiation environment the paper describes as more than `1000x` space. In that regime, designers cannot protect everything equally; they need to know which parameter bits are actually dangerous.

Exhaustive single-bit fault injection can answer that, but it is extremely expensive because even a small fixed-point model has thousands to hundreds of thousands of candidate bits. Prior speedups mostly rely on bit-level monotonicity: higher-order bits should be at least as harmful as lower-order ones. PrioriFI argues that this breaks often enough to matter. Across the nine models studied here, the paper reports `15%` intra-parameter monotonicity violations and `80%` inter-parameter violations. Once those exceptions appear, monotonicity-driven search either wastes injections on the wrong bits or delays discovering the truly sensitive ones.

## Key Insight

The core claim is that bit sensitivity should be ranked online. The Hessian is a good starting prior, but once injections begin, the best clue about the next useful flip is the `ΔC` already observed from recent flips. PrioriFI therefore watches which bit-significance classes are currently producing the most task damage and steers the campaign there. If recent `MSB-1` flips are hurting the model more than the next untested `MSB`s, it pivots immediately instead of continuing to trust monotonicity.

## Design

PrioriFI uses the standard single-bit-flip model on weights and biases. Its task-level sensitivity metric is `ΔC = max(C_faulty - C_faultless, 0)`: for classifiers, `C` is the number of mispredictions; for `ECON-T`, it is reconstruction loss measured with Earth Mover's Distance.

The algorithm is simple. It first ranks parameters with the Hessian, then creates one ordered list per bit significance: all `MSBs`, all `MSB-1`s, and so on, with each list internally sorted by Hessian rank. It flips the first bit from every list once to seed real measurements. After that, PrioriFI computes the median of the last `k` observed `ΔC` values for each significance list, chooses the list with the highest recent median, and flips the next Hessian-ranked bit from that list.

Unlike BinFI, PrioriFI does not imply the status of unflipped bits, so it avoids accumulating false positives or false negatives. The result is a characterization tool for the larger power-performance-area-reliability tradeoff, not a protection mechanism by itself.

## Evaluation

The authors evaluate nine fixed-point edge models: three `ECON-T` autoencoders on `HGCal`, three `SmartPixel` classifiers, and three `CIFAR-10` models. Sizes range from `825` bits to `944,208` bits, with quantization from `3` to `8` bits. Crucially, every model also gets an exhaustive Oracle ranking from full single-bit FI, so the paper can measure how close each accelerated method gets to ideal ordering.

PrioriFI is the best approximate ranking on seven of the nine models. Its normalized AUC relative to the Oracle is `0.93` or higher everywhere. The biggest gains appear on the least monotonic models: on `SmartPixel-L`, PrioriFI reaches `0.97` AUC versus `0.87` for Hessian; on `SmartPixel-M`, it reaches `0.94` versus `0.88`. On the more monotonic `CIFAR-10` models, the gain is smaller, which matches the paper's monoscore analysis.

The time study also matters. PrioriFI reaches `50%` of total cumulative sensitivity `43%` faster than Hessian on `SmartPixel-M`, and `14%` faster on `CIFAR-10-M`, saving `1 hour 37 minutes`. Setup overhead stays below `1%` of full campaign time for most models. Just as important, PrioriFI has no false positives or false negatives because it explicitly flips bits instead of inferring them. The baselines do not have that property: the paper reports `31.3%` false negatives for `StatFI` on `ECON-T-M` and `66.5%` on `CIFAR-10-M`, which would be dangerous if the ranking were used to decide what hardware to protect.

## Novelty & Impact

Relative to _Chen et al. (SC '19)_, PrioriFI's novelty is dropping monotonicity as a hard inference rule. Relative to _Ruospo et al. (DATE '23)_, it shows that magnitude-based sampling is a poor proxy for quantized edge models once downstream masking enters the picture. Relative to Hessian-guided approaches such as FKeras, its contribution is the adaptive loop that keeps retargeting the campaign as evidence arrives. That makes the paper useful to both dependable-ML researchers and edge-hardware designers deciding where parity, `TMR`, or selective protection are worth the cost.

## Limitations

PrioriFI is still an FI campaign, not a closed-form shortcut. It reduces time to the important bits, but full campaigns remain costly, and the evaluation's Oracle is only an offline reference. The fault model is also narrow: single-bit flips in weights and biases rather than multi-bit errors, activation faults, or broader hardware failures. Finally, the gains depend on how non-monotonic a model actually is. The `CIFAR-10` networks are more monotonic, so PrioriFI only modestly improves on Hessian there, and the paper openly admits that `medianLastK` still leaves a gap to the Oracle.

## Related Work

- _Chen et al. (SC '19)_ — BinFI accelerates FI with binary search under monotonicity assumptions, while PrioriFI flips bits explicitly and adapts when those assumptions fail.
- _Ruospo et al. (DATE '23)_ — StatFI samples bits based on expected magnitude swings, whereas PrioriFI measures task-level damage directly and shows why magnitude is unreliable for quantized edge NNs.
- _Schmedding et al. (ISSRE '24)_ — Aspis uses gradient or Taylor-style sensitivity estimates to guide protection, but PrioriFI stays in the FI regime and produces a true bit-level ranking rather than a lightweight proxy.
- _Reagen et al. (DAC '18)_ — Ares is a general DNN resilience framework, while PrioriFI focuses on aggressively prioritizing FI for small fixed-point edge models where exhaustive campaigns are otherwise too slow.

## My Notes

<!-- empty; left for the human reader -->
