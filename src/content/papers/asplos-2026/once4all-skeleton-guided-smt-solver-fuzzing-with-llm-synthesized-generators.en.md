---
title: "Once4All: Skeleton-Guided SMT Solver Fuzzing with LLM-Synthesized Generators"
oneline: "Turns SMT solver documentation into reusable theory generators and plugs their terms into real formula skeletons to find bugs in evolving solvers."
authors:
  - "Maolin Sun"
  - "Yibiao Yang"
  - "Yuming Zhou"
affiliations:
  - "State Key Laboratory for Novel Software Technology, Nanjing University, Nanjing, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790195"
tags:
  - fuzzing
  - formal-methods
  - pl-systems
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Once4All argues that LLMs are most useful for SMT solver fuzzing when they are used once to synthesize reusable, theory-specific generators instead of being asked to emit whole formulas online. The system extracts formula skeletons from real benchmarks, fills the holes with Boolean terms produced by those generators, and differentially tests the resulting formulas across solvers and solver versions. That combination preserves the deep structural cues of real bug-triggering inputs while adapting more quickly to new SMT-LIB features and solver-specific extensions.

## Problem

The paper targets a real maintenance gap in SMT solver testing. Solver input languages are not static: SMT-LIB 2.7 adds richer language features, and solvers such as cvc5 keep introducing their own extensions. Existing fuzzers age badly under that pressure. Grammar-based generators need expert-maintained rules, mutation-based fuzzers depend on hand-written mutation strategies, and direct LLM prompting for full formulas produces a large fraction of invalid inputs while paying LLM latency and cost on every generation step.

That matters because SMT solvers sit under symbolic execution, verification, and synthesis systems. A solver bug can silently mislead a client tool into accepting an invalid proof obligation or rejecting a valid model. The paper's motivating cvc5 example is useful here: a bug in sequence handling only reproduces when a quantifier remains in the input, even though the quantifier is not the semantic core of the failing expression. The point is that effective testing must cover both newly added theory constructs and the larger logical skeletons that steer the solver into fragile internal paths.

## Key Insight

The main claim is that SMT fuzzing should separate "learn the evolving language" from "generate millions of tests." Once4All uses LLMs in the offline phase to read theory documentation, summarize context-free grammars, and synthesize reusable generators for Boolean terms. After that, fuzzing becomes a cheap, high-throughput process driven by ordinary program execution rather than repeated model queries.

The second half of the insight is that generators alone are not enough. Real solver bugs often depend on formula shape, not just on a local operator choice. Once4All therefore keeps the skeletons of existing formulas by deleting selected atomic subformulas and replacing them with placeholders. Filling those placeholders with generated terms gives the system both adaptability and depth: the generators introduce fresh theory content, while the skeleton preserves the quantifiers, connectives, and nesting patterns that help reach deeper solver behavior.

## Design

Once4All has two phases. In the generator-construction phase, it collects documentation for standard SMT-LIB theories plus solver-specific features such as Z3's Unicode theory and cvc5's extensions. It prompts GPT-4 to summarize each theory as a CFG and then to implement a Python generator with a common interface. The generator is expected to emit Boolean terms together with any required declarations, such as `declare-fun` or `declare-datatypes`, and to stay within the documented syntax of the target theory.

Because grammar summaries can still miss semantic constraints, the paper adds a self-correction loop. Each new generator produces 20 sample terms, the framework wraps them with the needed SMT-LIB scaffolding, and multiple solvers attempt to parse them. If parsing fails, Once4All deduplicates the reported errors, feeds them back to the LLM, and asks for a refined implementation. This repeats for up to 10 rounds, retaining the best generator seen so far. The authors are explicit that this does not guarantee perfect well-formedness, but it moves validity much closer to what a practical fuzzer needs.

In the fuzzing phase, Once4All randomly selects a seed formula, removes some atomic Boolean subformulas, and leaves placeholders behind. It then picks one or more theory generators, produces replacement terms, and checks sort compatibility before splicing them into the skeleton. Variables from the generated terms can be renamed to existing seed variables when the sorts match, which increases semantic interaction between old structure and new content. The final formula is run through differential testing across multiple solvers; for solver-specific features, it compares multiple versions of the same solver instead. When one solver returns `sat`, Once4All can also validate the returned model to distinguish soundness bugs from invalid-model bugs. The implementation is in Python, uses GPT-4 only for generator construction, and applies ten mutation attempts per seed during fuzzing.

## Evaluation

The evaluation uses Z3 and cvc5 on a 20-core Xeon machine, with historical bug-triggering formulas from earlier work as seeds after filtering out formulas that still reproduce already known bugs on current trunk versions. Across the full bug-hunting campaign, Once4All generated about 10 million test cases with an average size of 4,828 bytes. From those inputs it obtained 727 bug-triggering formulas that reduced to 45 reported bugs, of which 43 were confirmed and 40 had been fixed by the time of writing. The mix is not just crashes: the confirmed set includes 35 crash bugs, 6 invalid-model bugs, and 4 soundness bugs.

The most persuasive number, in my view, is not just the raw bug count but where those bugs live. Eleven of the reported bugs involve newly added or solver-specific theories that older fuzzers do not really exercise. The paper also shows that some bugs had long lifespans: three Z3 bugs reproduced on releases stretching back more than six years. That supports the authors' argument that evolving languages create blind spots that existing handcrafted fuzzers miss.

The head-to-head comparison with prior SMT fuzzers is also strong. In 24-hour code-coverage runs, Once4All consistently exceeds the baselines on both line and function coverage for Z3 and cvc5, and manual inspection shows that it reaches solver-specific implementation directories that the baselines never touch. In the known-bug experiment, Once4All finds 11 unique bugs, while no baseline exceeds 3. The ablation study is equally important: removing skeleton guidance drops the known-bug count from 11 to 7, while swapping GPT-4 for Gemini 2.5 Pro or Claude 4.5 Sonnet yields similar results. That makes the paper's causal story fairly credible: the win comes mostly from the skeleton-plus-generator design, not from one lucky model choice.

## Novelty & Impact

Relative to _Sun et al. (ICSE '23)_, Once4All inherits the insight that skeletons from historical bug-triggering inputs are valuable, but it replaces manually designed mutation logic with documentation-driven generators that can follow new theories. Relative to _Sun et al. (ASE '23)_ and _Xia et al. (ICSE '24)_, its novelty is not "use LLMs for fuzzing" in the abstract; it is using them offline as generator synthesizers so the runtime fuzzing loop stays cheap and mostly valid. Relative to _Winterer and Su (OOPSLA '24)_, it gives up exhaustive grammar enumeration in exchange for quicker adaptation to solver-specific and recently added language features.

That makes the paper useful to two audiences. Solver developers get a practical workflow for stress-testing features that are too new or too idiosyncratic to have mature handwritten fuzzing support. Researchers get a broader pattern for structured-input fuzzing: use the LLM to manufacture reusable generators from messy documentation, then combine those generators with domain-specific structural templates instead of repeatedly asking the model for whole test cases.

## Limitations

The authors are clear that Once4All currently generates Boolean terms, not arbitrary SMT terms. That keeps synthesis manageable, but it narrows the search space and may miss bugs that depend on richer non-Boolean subterms or more global formula construction choices. The paper also notes that the self-correction loop mainly targets syntactic validity; it does not explicitly optimize for semantic novelty, rare solver states, or coverage feedback.

A second limitation is that the whole approach depends on documentation quality. Solver documentation can be incomplete, informal, or lag behind implementation, and the extracted CFGs inherit those weaknesses. Skeletons partly compensate for that by preserving real formula structure, but the approach still needs periodic regeneration when grammars evolve. Finally, the bug triage pipeline remains only semi-automated: crash clustering, theory grouping, and reducer selection reduce manual work, but humans still sit in the loop before a report reaches developers.

## Related Work

- _Sun et al. (ICSE '23)_ — HistFuzz also exploits historical bug-triggering formulas, but Once4All replaces hand-crafted mutation strategies with LLM-synthesized theory generators.
- _Winterer and Su (OOPSLA '24)_ — ET enumerates formulas from expert-written grammars, whereas Once4All derives reusable generators from documentation and keeps real formula skeletons.
- _Sun et al. (ASE '23)_ — LaST uses an LLM more directly for SMT formula generation; Once4All pushes the model offline and amortizes that effort across a high-throughput fuzzing campaign.
- _Xia et al. (ICSE '24)_ — Fuzz4All is a general LLM-based fuzzing framework, while Once4All specializes to SMT by combining differential testing, theory-specific generators, and skeleton-guided synthesis.

## My Notes

<!-- empty; left for the human reader -->
