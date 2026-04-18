---
title: "Static Analysis for Efficient Streaming Tokenization"
oneline: "Uses a static grammar analysis to identify when maximal-munch tokenization can stream with bounded memory, then runs a one-pass tokenizer that avoids flex-style backtracking."
authors:
  - "Angela W. Li"
  - "Yudi Yang"
  - "Konstantinos Mamouras"
affiliations:
  - "Rice University, Houston, Texas, USA"
conference: asplos-2026
category: compilers-languages-verification
doi_url: "https://doi.org/10.1145/3779212.3790227"
tags:
  - compilers
  - pl-systems
  - formal-methods
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

The paper splits streaming tokenization into two cases: grammars whose maximal-munch behavior inherently needs unbounded waiting, and grammars whose needed lookahead is finitely bounded. It captures that boundary with maximum token neighbor distance (max-TND), computes it statically, and uses the result to build `StreamTok`, a one-pass tokenizer with no backtracking. On practical data-format grammars, `StreamTok` is typically `2x-3x` faster than `flex` while using only kilobytes of memory.

## Problem

The paper studies maximal-munch tokenization for streams, where the lexer should emit tokens online instead of buffering the whole input. That is hard because maximal munch delays output until the lexer knows no longer token still fits. For some grammars, that means there may be no safe emission point without remembering arbitrarily much input. The paper proves exactly that worst-case lower bound: some tokenization grammars require `Omega(n)` space in streaming mode. So the real systems question is not "how do we make any lexer stream?" but "which grammars admit bounded-memory streaming tokenization, and how do we exploit that structure efficiently?"

## Key Insight

The key insight is that streamability depends on a semantic property of the grammar: how many extra characters may be needed to certify that a recognized token cannot be extended into a longer token. The paper calls this the token neighbor distance, and its maximum over the grammar is max-TND. If max-TND is unbounded, the lexer may have to wait arbitrarily long before emitting. If max-TND is bounded by `K`, then only the next `K` characters matter. That one number simultaneously explains when `flex`-style backtracking can get bad and when a true one-pass streaming algorithm is possible.

## Design

The design has two parts. First, a DFA-based static analysis computes max-TND. The core theorem says that for a regular language, max-TND is either infinite or at most `m + 1` for minimal-DFA size `m`, so a bounded answer can be found by exploring only a finite horizon. The paper also proves the general problem is PSPACE-hard, but gives a polynomial-space algorithm and a practical DFA procedure that runs in `O(M^2)` time for DFA size `M`.

Second, `StreamTok` uses the bound `K` at runtime. For `K = 1`, a small token-extension table is enough: after each character, the lexer checks whether one more character could keep the current final state extendable. For general bounded `K`, the paper builds a token-extension automaton that summarizes all token extensions of length up to `K`. During execution, that automaton runs `K` symbols ahead of the ordinary tokenization DFA. If the forward automaton shows that no extension path beginning at the current final state survives in the next `K` characters, the token is maximal and can be emitted. The result is a strictly left-to-right tokenizer with constant work per symbol and only a bounded `K`-sized delay buffer.

## Evaluation

The evaluation first asks whether bounded max-TND is common. Across `2669` de-duplicated GitHub grammars, about `68%` are bounded, and among those bounded grammars `53%` have max-TND `1`. The paper also reports sensible values for common formats: JSON `3`, CSV `1`, TSV `2`, and XML `6`, while the tested C, R, and SQL grammars are unbounded. The analysis cost looks practical: `99.4%` of grammars finish in under `100 ms`, and `99.96%` in under `1 s`.

Performance results support the runtime story. On the adversarial family `r_k = (a{0,k}b)|a`, `StreamTok` stays constant in `k` while prior streaming-friendly baselines effectively pay `Theta(k)` work per symbol. On practical workloads such as CSV, JSON, TSV, XML, YAML, FASTA, DNS zone files, and logs, `StreamTok` is typically `2x-3x` faster than `flex`, the most relevant baseline because it already supports streaming input. Memory usage is where the streaming design matters most: for `1000 MB` inputs, `StreamTok` stays around `0.1 MB`, while offline `ExtOracle` needs about `2003-2019 MB`. In higher-level applications such as log parsing, JSON minification, and CSV validation, replacing `flex` with `StreamTok` yields end-to-end speedups of roughly `2.5x-5.39x`.

## Novelty & Impact

Relative to _Li and Mamouras (OOPSLA '25)_, the paper's main move is not another offline no-backtracking algorithm, but the claim that streaming feasibility itself is statically decidable from the grammar. Relative to _Reps (TOPLAS '98)_, it trades input-sized memoization for grammar-side analysis plus bounded lookahead. Relative to `flex`, it turns "bad backtracking behavior" into a semantic property of the grammar rather than an opaque implementation artifact.

That makes the paper important for two audiences. Systems builders get a practical recipe for low-memory tokenization of JSON-, CSV-, XML-, and log-like streams from grammar specifications rather than handwritten scanners. PL and compilation researchers get max-TND as a reusable abstraction for separating grammars that are fundamentally hostile to online emission from grammars that merely need better runtime machinery.

## Limitations

The main limitation is explicit: `StreamTok` only works for grammars with bounded max-TND. That covers many data formats, but not the programming-language grammars the paper analyzes, so this is not a universal lexer replacement. The approach also assumes a fixed grammar with precomputed automata and tables, which is natural for generated lexers but less appealing for highly dynamic grammars.

The CSV case study shows another practical wrinkle. The RFC-style quoted-field rule has unbounded max-TND, so the authors switch to a variant with an optional closing quote and recover well-formedness with a separate even-quote check. That is a workable engineering compromise, but it means the fastest streaming path may require grammar refactoring plus side conditions. A reviewer-style concern inferred from the construction is that the token-extension automaton still comes from a subset-style build, so worst-case state blowup is not ruled out even though the paper's measured cases remain small.

## Related Work

- _Li and Mamouras (OOPSLA '25)_ — ExtOracle and TokenSkip remove backtracking for all grammars, but they are offline algorithms that need the whole input before processing starts, whereas `StreamTok` is explicitly stream-first.
- _Barenghi et al. (IPDPS '21)_ — Plex attacks lexing throughput with parallel backtrack-free prescanning, while this paper focuses on single-pass streaming enabled by a grammar-side semantic bound.
- _Egolf et al. (CPP '22)_ — Verbatim++ emphasizes verified derivative-based lexer generation, whereas this paper prioritizes static streamability analysis and runtime efficiency for maximal-munch tokenization.
- _Tan and Urban (ITP '23)_ — bit-coded derivative-based POSIX lexing preserves standard lexical semantics, but it does not characterize when those semantics admit bounded-memory streaming execution.

## My Notes

<!-- empty; left for the human reader -->
