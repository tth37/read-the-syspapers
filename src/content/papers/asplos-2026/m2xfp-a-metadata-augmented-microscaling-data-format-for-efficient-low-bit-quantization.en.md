---
title: "M2XFP: A Metadata-Augmented Microscaling Data Format for Efficient Low-bit Quantization"
oneline: "Adds 0.25 metadata bits per value to MXFP by refining weight scales offline and preserving activation maxima online."
authors:
  - "Weiming Hu"
  - "Zihan Zhang"
  - "Haoyan Zhang"
  - "Chen Zhang"
  - "Cong Guo"
  - "Yu Feng"
  - "Tianchi Hu"
  - "Guanglin Li"
  - "Guipeng Hu"
  - "Junsong Wang"
  - "Jingwen Leng"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "Shanghai Qi Zhi Institute, Shanghai, China"
  - "Computing Product Line, Huawei, Shanghai, China"
  - "Computing Product Line, Huawei, Beijing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790185"
tags:
  - hardware
  - llm-inference
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

M2 XFP argues that 4-bit microscaling fails mainly because MXFP4 mishandles each block's dominant values. It therefore uses metadata asymmetrically: weights get offline subgroup-scale refinement, while activations get online protection for the subgroup maximum. The resulting 4.5-bit format cuts reported accuracy loss by 70.63% versus MXFP4 and still fits a lightweight systolic-array design.

## Problem

Microscaling formats such as MXFP4 are attractive because a block of 4-bit values shares one compact scale, so hardware stays fast and cheap. The failure mode is that the scale is usually E8M0, a power-of-two value. At 4-bit precision that coarse scale often cannot align with the block maximum, so the largest element is rounded badly and the whole block inherits the error.

Prior fixes all give something back: FP8 shared scales narrow range and need extra rescaling, custom datatypes demand more decoder logic and runtime choice, and heavier metadata schemes add too much control overhead. The paper asks whether a very small metadata budget can recover most of the lost accuracy without breaking MX's hardware story.

## Key Insight

The key claim is that metadata should not be spent uniformly. Under a fixed shared scale, the best use of bits is to preserve the most important element in each subgroup with extra mantissa, because that directly attacks block-maximum error. But once offline search is allowed, subgroup-level scale refinement becomes stronger because the search can jointly choose a better scale and metadata setting. So weights should refine subgroup scales, while dynamic activations should protect the subgroup top-1 value online. M2 XFP is exactly that hybrid.

## Design

The authors first classify metadata along two axes: extra mantissa vs. extra exponent, and element-level vs. subgroup-level placement. That yields four families: `Elem-EM`, `Elem-EE`, `Sg-EM`, and `Sg-EE`. Their exploration shows that extra mantissa is the useful direction.

The final format uses group size `32` and subgroup size `8`. For weights, each subgroup gets 2 metadata bits that refine the subgroup scale to one of `{1.0, 1.25, 1.5, 1.75} x S`, and offline search may also bias the group exponent by `-1`, `0`, or `+1`. For activations, the online quantizer computes the group scale, quantizes to baseline FP4, finds the subgroup top-1 in quantized space, and re-encodes only that value with two extra mantissa bits. The encoding is biased and clamped so the high four bits still match the original FP4 code. Hardware support stays modest: a top-1 decode unit, an augmented FP4 x FP4 PE, and a streaming quantization engine. The PE treats the extended-mantissa activation as a baseline FP4 value plus a small correction term, and weight refinement is implemented with shift-and-add.

## Evaluation

The evaluation covers both model quality and hardware cost. Accuracy is tested on LLaMA-2 7B, LLaMA-3 8B and 70B, OPT-6.7B, Mistral-7B, Falcon-7B, and DeepSeek-R1-Distill-Qwen 1.5B and 7B. Hardware is modeled with DNNWeaver plus 28 nm synthesis at 500 MHz.

The headline result is the average loss on the 7B and 8B LLM suite. MXFP4 incurs `5.38%` average accuracy loss relative to FP16, while M2 XFP reduces that to `1.58%`, a reported `70.63%` reduction. Against NVFP4 at the same effective 4.5-bit width, M2 XFP lowers average loss from `2.52%` to `1.58%`, a `37.30%` improvement. Wikitext perplexity shows the same trend: LLaMA3-8B improves from `8.30` to `6.84`, and LLaMA3-70B from `4.84` to `3.56`. On DeepSeek-R1-Distill-Qwen-1.5B, the average reasoning score rises from `36.91` under MXFP4 to `44.44`, versus `49.03` for FP16.

The hardware results are favorable, though not silicon-measured. Relative to MicroScopiQ, M2 XFP reports up to `1.91x` speedup and `1.75x` energy reduction on average, while the extra top-1 decode units and quantization engine contribute only `0.26%` area overhead and `0.36%` power overhead across all components. That supports the central claim.

## Novelty & Impact

Relative to _Rouhani et al. (ISCA '23)_, M2 XFP's novelty is a systematic argument that mantissa-oriented metadata is a better use of bits than exponent-oriented metadata in this regime. Relative to _Ramachandran et al. (ISCA '25)_, it aims for a smaller control footprint and a cleaner online activation path. Relative to datatype-centric work such as _Guo et al. (MICRO '22)_ and _Hu et al. (HPCA '25)_, it argues that changing the base datatype is the wrong center of gravity for dynamic inference tensors.

## Limitations

The biggest practical limitation is that the weight path depends on offline adaptive search, so the full design is not equally convenient for all deployment pipelines. The evaluation is also centered on GEMM-dominated linear layers; the paper discusses Attention and KV-cache extension, but does not implement that end to end. The hardware evidence comes from simulation and synthesis rather than a fabricated chip, and the final choice of group size `32` and subgroup size `8` is empirically motivated rather than universally justified.

## Related Work

- _Rouhani et al. (ISCA '23)_ — SMX adds shared microexponents to neighboring values, while M2 XFP argues that mantissa refinement is a better metadata budget at 4-bit precision.
- _Guo et al. (MICRO '22)_ — ANT improves quantization by changing the underlying datatype, whereas M2 XFP keeps the FP4 datapath and moves the extra expressiveness into metadata.
- _Hu et al. (HPCA '25)_ — M-ANT extends the adaptive-datatype idea to group quantization, but M2 XFP argues that dynamic activations need a cheaper online path than runtime type search.
- _Ramachandran et al. (ISCA '25)_ — MicroScopiQ uses block-level structural metadata and mixed precision for outlier handling, while M2 XFP pursues lower-overhead metadata that still fits regular MX-style hardware.

## My Notes

<!-- empty; left for the human reader -->
