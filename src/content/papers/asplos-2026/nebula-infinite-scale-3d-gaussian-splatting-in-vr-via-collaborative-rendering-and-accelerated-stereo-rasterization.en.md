---
title: "Nebula: Infinite-Scale 3D Gaussian Splatting in VR via Collaborative Rendering and Accelerated Stereo Rasterization"
oneline: "Offloads memory-hungry LoD search for large-scene 3DGS to the cloud, streams only delta Gaussians, and reuses stereo work on the client for VR rendering."
authors:
  - "He Zhu"
  - "Zheng Liu"
  - "Xingyang Li"
  - "Anbang Wu"
  - "Jieru Zhao"
  - "Fangxin Liu"
  - "Yiming Gan"
  - "Jingwen Leng"
  - "Yu Feng"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "ICT, Chinese Academy of Sciences, Beijing, China"
  - "Shanghai Jiao Tong University, Shanghai Qi Zhi Institute, Shanghai, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790190"
tags:
  - hardware
  - gpu
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Nebula splits large-scene 3DGS at the LoD boundary: the cloud finds the Gaussian cut, the client renders from that cut, and stereo reuse avoids repeating most right-eye work. The paper reports up to `52.7x` faster LoD search and `12.1x` end-to-end speedup over a mobile GPU baseline.

## Problem

The paper starts from two scaling failures. Large-scene 3DGS does not fit on headsets: the authors measure scenes reaching `66 GB` of runtime memory demand, versus under `12 GB` on typical VR devices. As scenes grow, the bottleneck also shifts: instead of rasterization, LoD search can consume up to `47%` of end-to-end latency on a mobile Ampere GPU.

Cloud video streaming fixes memory but not bandwidth. The paper cites over `1 Gbps` demand for `4K`, `90 FPS` VR video, and its own breakdown shows transmission dominating latency. Prior collaborative renderers still partition work at the pixel level, which mismatches 3DGS because the hard part is selecting Gaussians.

## Key Insight

Nebula's core claim is that the right split point is immediately after LoD search. LoD search touches the full hierarchical scene and bears the highest memory demand, while the later stages operate on a much smaller cut that a client device can keep locally. Cloud-client partitioning therefore becomes a Gaussian-selection problem instead of a video-streaming problem.

That split works because the selected Gaussians are highly reusable. The paper reports about `99%` overlap between consecutive cuts and still above `95%` overlap at a frame gap of `64`. The stereo views are also highly redundant, with under `1%` non-overlapping pixels. Nebula therefore sends only temporal Gaussian deltas and reuses Gaussian geometry across the two eyes rather than warping pixels, preserving bit accuracy.

## Design

Nebula has three linked mechanisms. First, cloud LoD search. The initial frame uses a fully streaming GPU traversal with breadth-first links, fixed-size node blocks per warp, and shared-memory staging. Later frames use temporal-aware LoD search: the tree is partitioned offline into balanced subtrees, and the search starts from the previous cut and explores only relevant local subtrees before falling back to higher levels. The paper says this matches full-search output bit-for-bit.

Second, Gaussian delta management. The cloud tracks which Gaussians the client already holds with a management table and reuse window `w_r`. Each frame sends only a `Delta cut`, and both sides evict stale Gaussians when `w_r` exceeds `w_r* = 32`. The data is further compressed with vector quantization for spherical-harmonic coefficients and `16-bit` fixed point for smaller attributes.

Third, client stereo rendering. The client preprocesses and sorts once over a widened FoV covering both eyes. Any Gaussian that survives the left-eye `alpha` check is triangulated into the right-eye view, inserted into one of four disparity-bounded lists, and later merged into the right-eye tile's sorted intersection list. The paper extends GSCore with a decoder, stereo reprojection unit, merge unit, and a `16 KB` stereo buffer per VRC, for about `14%` extra area.

## Evaluation

The evaluation mixes algorithms and hardware. The authors implement Nebula as a `1 GHz` GSCore-derived RTL design, scale results to `8 nm`, compare against a mobile Ampere GPU, GSCore, and GBU, and use two `A100-80GB` GPUs on the cloud side. Workloads include `Urban`, `Mega`, and `HierGS`.

The quality result is strong: relative to independently rendering both eyes, Nebula loses only `0.1 dB` PSNR, which the paper attributes to compression rather than stereo rasterization; SSIM and LPIPS do not drop. Temporal-aware LoD search reaches up to `52.7x` speedup over prior LoD-search methods, and stereo rasterization improves local rendering by `1.4x`, `1.9x`, and `1.7x` over GPU, GBU, and GSCore.

End to end, Nebula is the best collaborative design in the paper. It delivers `12.1x` speedup over the mobile GPU baseline, about `70.1 FPS` at the default hardware size, `14.9x` lower client energy than the mobile GPU baseline, and `1.4x` lower energy than GSCore. The paper repeatedly summarizes Nebula as reducing traffic by `1925%` relative to lossy video streaming; the wording is awkward, but the figures clearly support the qualitative point that Gaussian-delta streaming is much smaller than pixel streaming here.

## Novelty & Impact

Relative to _Kerbl et al. (TOG '24)_, Nebula is not a new representation but a new systems boundary built around hierarchical LoD. Relative to _Lee et al. (ASPLOS '24)_ and _Ye et al. (HPCA '25)_, its contribution is coupling a client accelerator to cloud LoD search and bit-accurate stereo reuse. Relative to _Feng et al. (ISCA '24)_, its key move is to stream Gaussian assets instead of warped pixels.

## Limitations

Nebula depends on temporal and stereo coherence. The paper shows those properties are strong on its datasets, but it does not directly test regimes with abrupt head motion or scene changes that would lower overlap. The concern that benefits may shrink there is my inference from the design, not an explicit experimental claim.

The deployment story is also narrower than the headline. Default hardware reaches only `70.1 FPS`; hitting `90 FPS` requires increasing rendering units from `128` to `256`, which raises area by `62.9%`. The paper also excludes LoD-tree construction cost, multi-user contention, and broader cloud scheduling issues.

## Related Work

- _Kerbl et al. (TOG '24)_ — HierGS provides the hierarchical 3DGS representation and LoD-tree abstraction that Nebula builds around, but it does not address cloud-client partitioning or stereo reuse.
- _Lee et al. (ASPLOS '24)_ — GSCore accelerates 3DGS rendering on device; Nebula reuses that style of accelerator as a client substrate and adds collaborative offload plus stereo-specific support.
- _Feng et al. (ISCA '24)_ — Cicero exploits stereo similarity through warping, while Nebula argues that Gaussian-level reprojection better fits view-dependent 3DGS.

## My Notes

<!-- empty; left for the human reader -->
