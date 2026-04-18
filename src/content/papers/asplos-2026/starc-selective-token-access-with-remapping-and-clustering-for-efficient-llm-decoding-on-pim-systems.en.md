---
title: "STARC: Selective Token Access with Remapping and Clustering for Efficient LLM Decoding on PIM Systems"
oneline: "Clusters semantically similar KV pairs into row-aligned PIM layouts so sparse LLM decoding can skip rows without giving up token relevance."
authors:
  - "Zehao Fan"
  - "Yunzhen Liu"
  - "Garrett Gagnon"
  - "Zhenyu Liu"
  - "Yayue Hou"
  - "Hadjer Benmeziane"
  - "Kaoutar El Maghraoui"
  - "Liu Liu"
affiliations:
  - "Rensselaer Polytechnic Institute, Troy, NY, USA"
  - "University of Massachusetts, Amherst, Amherst, MA, USA"
  - "IBM Research – Ruschlikon, Ruschlikon, Switzerland"
  - "IBM T. J. Watson Research Center, Yorktown Heights, NY, USA"
conference: asplos-2026
category: llm-inference
doi_url: "https://doi.org/10.1145/3779212.3790226"
code_url: "https://github.com/EPIC-RPI/STARC"
tags:
  - llm-inference
  - hardware
  - memory
  - energy
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

STARC turns sparse KV retrieval into a row-aligned operation for PIM: it clusters semantically similar keys, co-locates their KV pairs, and retrieves whole clusters by centroid scores. With `K=4` and 64-token blocks chosen to match AttAcc's balance point, it cuts attention-layer latency and energy by up to `78%` and `65%` versus token-wise sparsity, and by up to `93%` and `92%` versus full KV retrieval, while staying close to SparQ on accuracy.

## Problem

The paper starts from a direct mismatch between sparse attention and PIM execution. During autoregressive decoding, attention repeatedly scans a growing KV cache, so the bottleneck is memory traffic. HBM-PIM designs such as AttAcc help by moving simple GEMV computation near the banks, but they still operate at row granularity: once a row is activated, the bank fetches and processes the whole row.

That makes both obvious sparse choices unsatisfying. Token-wise methods such as SparQ and InfiniGen find relevant tokens, but those tokens are physically scattered, so PIM still performs many row activations and over-fetches unrelated data. Page-wise methods such as Quest are more hardware-friendly because a page can align with a row, but they fetch by position rather than semantics, so each retrieved block often contains only a few useful tokens. STARC is aimed exactly at this gap: preserving semantic selectivity without giving up row-level efficiency.

## Key Insight

The central claim is that sparse attention becomes PIM-friendly once tokens that are likely to matter together are also stored together. STARC therefore clusters semantically similar key vectors, lets the corresponding values inherit the same labels, and lays out each cluster contiguously in HBM-PIM. A row activation now tends to fetch a useful semantic group instead of an arbitrary positional window.

The paper also argues that the cluster count must be hardware-aware, not purely empirical. Its arithmetic-intensity analysis shows that cosine K-means on FP16 vectors scales roughly with `K`, while the simulated AttAcc system has a compute/bandwidth tipping point near `4 FLOPs/Byte`. That is why STARC fixes `K=4`: the clustering workload itself is chosen to sit near the substrate's balance point.

## Design

STARC is built around AttAcc's row layout. Each row stores `1 KB`; with FP16 and head dimension `128`, one key or value vector occupies `256 B`. By splitting a vector across the four banks in a bank group, one row across the group holds `16` complete vectors, so `blkrow = 16`. This directly yields the main block size: `N = K * blkrow = 64`.

Clustering is done inside HBM-PIM rather than on a GPU. STARC maps cosine K-means onto AttAcc commands: `MAC_AB` for dot products, `WRGB` and `MVGB` for moving vectors into buffers, `MVSB` for gathering scores, and one lightweight `VNORM` operation for approximate normalization. The paper's point is that normalization, assignment, and centroid updates reuse existing PIM datapaths and avoid extra area overhead; only the final `argmax` over centroid scores is left to the host.

The online path is append-only. After prefill, the KV cache is divided into non-overlapping 64-token blocks; STARC clusters keys only, with random initialization and at most `16` Lloyd iterations, and stores the resulting clusters contiguously. During decoding, new tokens remain unclustered and are always included in attention until `64` of them accumulate; then only that newest block is clustered and appended. Retrieval is then simple: score the current query against all centroids, sort clusters by score, fetch clusters until the KV budget `B` is reached, truncate the last cluster if needed, and include all still-unclustered recent tokens. Because old clusters are never reshuffled, clustering overhead grows linearly with context length rather than with the number of decode steps squared.

## Evaluation

The accuracy evaluation covers LongChat-7B-v1.5-32K, LLaMA-3.1-8B-Instruct, and Mistral-7B-Instruct-v0.3 on LongBench, RULER, and PG-19, against Quest, InfiniGen, SparQ, and full KV retrieval. Under the main `1024`-token KV budget, STARC is consistently better than page-wise Quest and usually very close to the best token-wise baseline. On LongBench average score, it reaches `39.71` on LLaMA-3.1 versus `39.76` for SparQ, `39.51` for InfiniGen, and `36.38` for Quest; on Mistral it scores `46.29`, again beating Quest's `44.57` and staying close to InfiniGen's `46.53` and SparQ's `47.77`. On RULER, STARC averages `0.8727`, close to full KV's `0.8812` and SparQ's `0.8831`, while clearly ahead of InfiniGen's `0.8419` and Quest's `0.7848`. PG-19 shows the same pattern qualitatively: STARC tracks full KV closely, beats Quest and InfiniGen, and trails SparQ only slightly.

The systems evaluation uses AttAcc on a DGX-like platform with `8` H100 GPUs, `40` HBM3 stacks on the GPU side, `40` HBM3 stacks on the PIM side, batch size `16`, and sequence pairs `(2K,16K)`, `(2K,24K)`, and `(2K,32K)`. Crucially, the authors map each method's attention masks down to row granularity, which is exactly the right measurement for their claim.

The main numbers support the thesis well. End-to-end decoding sees `25%-48%` speedup and `34%-56%` energy reduction relative to full KV retrieval; the paper also frames this as `13%-21%` faster execution and `11%-18%` lower energy than token-wise sparsity methods. When the attention layer is isolated, STARC cuts latency and energy by up to `93%` and `92%` versus full KV, and still by up to `78%` and `65%` versus token-wise sparsity. The extra clustering cost stays around `0.02%` of total decoding latency and energy in long-context settings. That is the paper's strongest result: near page-wise hardware efficiency without page-wise accuracy loss.

## Novelty & Impact

Relative to AttAcc, the novelty is not another dense-attention mapping, but a sparse-attention layout explicitly designed for row-level PIM execution. Relative to SparQ and InfiniGen, the key move is recognizing that good token selection is not enough if those tokens remain physically scattered. Relative to Quest, STARC replaces positional pages with semantic clusters, which is why it preserves better relevance while still enabling coarse-grained skipping.

That makes the paper interesting to both long-context LLM inference work and PIM architecture work. It is a real mechanism, not just a measurement study, and later papers on sparse KV retrieval or GPU-PIM co-design are likely to treat it as an early reference point.

## Limitations

The design is tightly coupled to the simulated hardware organization. `K=4`, `blkrow=16`, and the 64-token block size all follow AttAcc's FP16 row layout and compute/bandwidth balance, so portability to different head sizes, precisions, or PIM organizations is not free. STARC also fixes clusters once formed, which keeps remapping cheap but prevents adaptation if old-token neighborhoods drift later in decoding.

The evaluation has the usual caveats for this area. The performance claims come from simulation rather than a real PIM deployment, STARC clusters keys only and lets values inherit labels, and the paper optimizes retrieval under a fixed KV budget rather than solving KV-capacity management. The baseline setup also keeps the first two layers dense because their sparsity is low, so the gains apply after that choice.

## Related Work

- _Park et al. (ASPLOS '24)_ — AttAcc provides the HBM-PIM substrate for transformer attention, while STARC adds sparse-layout remapping and in-memory clustering on top of that dense-oriented design.
- _Lee et al. (OSDI '24)_ — InfiniGen predicts which tokens matter during decoding, but leaves them physically scattered; STARC adds a semantic layout that makes those selections profitable on row-granular PIM.
- _Zhou et al. (HPCA '22)_ — TransPIM accelerates transformer execution inside memory with dense-style dataflows, whereas STARC focuses on sparse token access and row-aware KV placement.
- _Kwon et al. (SOSP '23)_ — PagedAttention solves KV-cache memory management for LLM serving on GPUs, but it does not address how sparse token retrieval should be physically organized for PIM execution.

## My Notes

<!-- empty; left for the human reader -->
