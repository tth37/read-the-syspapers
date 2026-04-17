---
title: "cuJSON: A Highly Parallel JSON Parser for GPUs"
oneline: "Parses standard JSON on GPUs by turning UTF checks, tokenization, and bracket matching into branch-light bitmap, scan, and sort primitives."
authors:
  - "Ashkan Vedadi Gargary"
  - "Soroosh Safari Loaliyan"
  - "Zhijia Zhao"
affiliations:
  - "University of California, Riverside"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3760250.3762222"
code_url: "https://github.com/AutomataLab/cuJSON"
tags:
  - gpu
  - databases
  - observability
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

cuJSON shows that JSON parsing can be reformulated into GPU-friendly bitmap, scan, and sort operations rather than a branchy stack machine. It validates UTF-8, tokenizes structural characters, and matches brackets on the GPU, then emits a compact pairing index that preserves hierarchy. On large inputs, that is enough to beat strong CPU parsers.

## Problem

JSON is common in logs, document stores, web services, and analytics, and prior work reports that parsing alone can dominate query time. CPU parsers such as simdjson and Pison already exploit SIMD well, but GPU support remains weak. Existing GPU parsers are mostly limited to JSONL, often normalize into tabular outputs that discard nesting, and still lean on branch-heavy or stack-based logic. cuJSON therefore targets a harder problem: preserve JSON hierarchy, support standard JSON as well as JSONL, validate UTF-8 correctly, and expose enough word-, byte-, and bit-level parallelism to justify offloading.

## Key Insight

The central claim is that JSON parsing becomes GPU-friendly once it is expressed as data-parallel transformations on bitmaps and indices. cuJSON applies that idea end to end: UTF-8 validation becomes branch-free checks over adjacent words; tokenization becomes a bitmap pipeline that removes pseudo-structural characters inside strings; and nesting recognition becomes depth labeling plus sorting rather than serial stack manipulation. The output format is part of the insight: instead of building a mutable tree, cuJSON emits a structural index and a pairing index, which are easy to construct in parallel and still let queries skip entire unmatched subtrees.

## Design

The parser accepts standard JSON or JSONL; JSONL is rewritten into one large array by surrounding lines with brackets and replacing newlines with commas. If the estimated memory footprint exceeds device capacity, the parser aborts rather than spilling.

Phase one is UTF-8 validation. cuJSON first checks whether any non-ASCII bytes exist and skips the heavy path for pure ASCII input. Otherwise, each thread examines neighboring 32-bit words to detect malformed, overlong, surrogate, and too-large sequences using GPU byte-wise comparisons and bit logic.

Phase two is tokenization. The system builds bitmaps for the six JSON structural characters, plus backslashes and quotes. It handles escape dependency with backward counting over backslash bitmaps, then handles quote parity with quote counts, an exclusive scan, and an emulated prefix-XOR. After masking out string contents, it extracts a structural index plus an open-close array for brackets and braces.

Phase three is structure recognition. cuJSON maps open and close delimiters to signed values, scans to compute depth, adjusts opener depths, and stable-sorts delimiters by depth so candidate matches become adjacent. A validation pass rejects illegal bracket or brace pairings, and an expansion step produces the pairing index. Kernel fusion and multi-streaming with pinned host memory reduce launch and transfer overhead.

## Evaluation

The evaluation compares cuJSON with RapidJSON, simdjson, and Pison on CPUs, and with cuDF, GPJSON, and MetaJSON on GPUs, using six real-world datasets roughly `842 MB-1.2 GB` on both a Quadro P4000 desktop and an A100 server.

For standard JSON, cuJSON beats the CPU baselines on large inputs by about `1.3x-2.8x` over the second-best parser, usually Pison, even after including host-device transfer time. The result is explicitly not universal: below about `8 MB`, GPU overhead outweighs the benefit and simdjson wins. Against existing GPU parsers on JSONL, cuJSON reports average speedups of `117.9x` over cuDF, `14.8x` over GPJSON, and `3.2x` over MetaJSON. Validation is the cheapest stage; tokenization and structure recognition dominate compute; and host-to-device copy is often the largest cost. Peak GPU memory stays around two to three times input size, competitive with the other GPU systems.

The query results support the paper's narrower claim. cuJSON's pairing index helps object-specific queries by skipping subtrees, so it beats Pison there, but it still trails pointer-rich CPU tree representations such as simdjson and RapidJSON. For all-object JSONL queries, GPJSON remains faster because cuJSON still queries on the CPU. The evaluation therefore supports cuJSON as a parser and compact read-only representation, not as the fastest query engine.

## Novelty & Impact

Relative to _Langdale and Lemire (VLDB '19)_, cuJSON's novelty is not SIMD parsing itself, but porting the problem into GPU-native primitives rather than CPU shuffle instructions. Relative to _Jiang et al. (VLDB '20)_, it replaces CPU multi-core dependency breaking with a GPU bitmap pipeline plus scan-and-sort bracket matching. Relative to earlier GPU systems such as cuDF, MetaJSON, and GPJSON, its strongest result is that standard JSON, hierarchy preservation, and full UTF validation can coexist with good GPU performance.

That gives the paper real impact for semi-structured analytics systems and GPU-centric data pipelines that currently pay CPU parsing cost up front.

## Limitations

cuJSON is not a universal replacement for CPU parsers. Small files lose because transfer and launch overhead dominate below the paper's breakeven point. Standard JSON must fit in GPU memory; otherwise the current implementation aborts instead of streaming. The parser is also read-only and does not support in-place mutation.

Its output format brings query tradeoffs as well. Because cuJSON stores indices into the original byte array rather than a fully materialized tree, some queries still require CPU-side scanning, which is why simdjson and RapidJSON remain faster for certain patterns. GPU-accelerated querying and mutation-friendly outputs are left for future work, so the design is strongest for parse-heavy analytics.

## Related Work

- _Langdale and Lemire (VLDB '19)_ — simdjson shows how far branch-light, SIMD-oriented JSON parsing can go on CPUs; cuJSON adapts the spirit, but not the exact primitives, to GPUs.
- _Li et al. (VLDB '17)_ — Mison introduced bitmap-oriented JSON parsing for analytics workloads, and cuJSON extends that style of thinking into a GPU setting with hierarchy-preserving output.
- _Jiang et al. (VLDB '20)_ — Pison breaks parsing dependencies across CPU cores for a single large JSON record; cuJSON tackles the same "one big JSON" problem with GPU scans, bitmaps, and sorting.
- _Kaczmarski et al. (DSAA '22)_ — MetaJSON demonstrates GPU JSON parsing via metaprogramming, but targets schema-driven normalization rather than general hierarchy-preserving parsing.

## My Notes

<!-- empty; left for the human reader -->
