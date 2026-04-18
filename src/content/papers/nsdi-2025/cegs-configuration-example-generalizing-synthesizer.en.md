---
title: "CEGS: Configuration Example Generalizing Synthesizer"
oneline: "CEGS retrieves vendor configuration examples, maps them onto a target topology with GNNs, and uses an LLM+SMT pipeline to synthesize correct configs without hand-written templates."
authors:
  - "Jianmin Liu"
  - "Li Chen"
  - "Dan Li"
  - "Yukai Miao"
affiliations:
  - "Tsinghua University"
  - "Zhongguancun Laboratory"
conference: nsdi-2025
tags:
  - networking
  - formal-methods
  - verification
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

CEGS tries to automate the missing step between vendor manuals and formal configuration synthesis: finding a relevant documented example, mapping it onto the target topology, and turning it into symbolic templates that a solver can complete. It uses GNNs for example retrieval and device matching, then constrains the LLM to template generation while syntax checks, local/global verifiers, and NetComplete enforce correctness. On the paper's routing workloads, that combination reaches networks with up to 1,094 routers and is dramatically faster than prior LLM-only baselines in the scenarios those baselines support.

## Problem

The paper starts from a practical bottleneck in network operations. Formal synthesizers such as NetComplete can fill symbolic configuration templates, and DSL-based systems can compile high-level policies, but neither removes the expert work of translating a natural-language intent plus a target topology into per-device templates. An operator still has to read the vendor documentation, locate the right example, decide which snippet belongs to which router, and then mark the parameters that must remain symbolic. That work is repetitive, brittle, and exactly where institutional knowledge tends to hide.

Pure LLM approaches do not eliminate the problem either. The paper argues that asking an LLM to directly emit complete network-wide configurations forces it to do too much at once: understand the intent, reason over topology, remember vendor syntax, and choose globally consistent policy values. Prior work such as COSYNTH therefore needs many correction loops and often still requires experts in the loop. The real missing capability is what the authors call example following and generalization: automatically identifying a documentation example that matches the target intent and then adapting that example to a different topology.

## Key Insight

The core claim is that example following and generalization should be treated as a structured graph problem plus a constrained synthesis problem, not as open-ended text generation. A suitable example is one that matches both the semantics of the intent and the topology pattern in which that intent is realized. Once the system represents "intent plus topology" as an intent graph, example retrieval and node mapping become similarity problems that GNNs can solve more reliably than a free-form prompt alone.

The second half of the insight is to narrow the LLM's job aggressively. CEGS does not ask the model to choose concrete policy parameters for the whole network. Instead, it asks the model to emit only templates grounded in the retrieved examples, leaving route preferences, communities, costs, and other policy values symbolic. Those values are then checked and filled by verifiers plus a formal synthesizer. That division of labor is the reason the system can be both faster and more trustworthy than an LLM-only loop.

## Design

CEGS has three phases: retrieval, association, and generation. In the retrieval phase, it first parses configuration examples from device documentation into a uniform format containing a natural-language intent, a topology, and per-device configurations. For a user intent, the Querier uses GPT-4o to normalize the intent into a canonical phrasing without device-specific proper nouns, then uses SBERT cosine similarity to keep only examples of the same intent type. From there it builds an intent graph for each candidate example and for the target network: topology nodes become graph nodes, links become edges, and GPT-4o assigns each node a role attribute such as source, relay, destination, or non-involvement. FastText embeds those textual roles and GraphSAGE produces graph embeddings so the system can pick the most similar example by graph distance.

The association phase maps routers in the target topology to routers in the retrieved example. The Classifier first does the easy part with exact role matching. When several example nodes share the same role, it uses another GraphSAGE-based comparison over neighborhood structure to pick the closest analogue. This matters because two routers can both be "relays" yet require different configurations depending on which kinds of neighbors surround them.

The generation phase is an iterative LLM-plus-verifier loop. To stay inside context limits, CEGS partitions devices into batches of 40 and asks GPT-4o to generate templates for each batch in parallel. The templates contain concrete syntax and structural boilerplate, but leave policy parameters symbolic. A Syntax Verifier extends the Batfish parser so those symbols are still parseable. A Local Attribute Verifier checks per-device facts such as interface attributes, AS numbers, neighbor declarations, and OSPF/BGP basics against the intended topology and intent description. A Global Formal Verifier converts the natural-language intent into NetComplete's formal specification with GPT-4o, encodes the symbolic templates plus the formal intent into SMT, and checks whether some assignment of values can satisfy the policy. Error messages from these stages are fed back to the LLM for the next loop. Once templates for all intents pass, CEGS merges configuration segments and invokes NetComplete to fill the symbols with concrete values.

## Evaluation

The evaluation uses 20 sampled Topology Zoo ISP PoP topologies ranging from 20 to 754 routers, plus a merged 1,094-router topology. The workload covers six routing-intent types across Static, OSPF, and BGP, and the corpus contains 300 parsed configuration examples from Cisco documentation and a cloud provider. The strongest component-level result is that, on 90 synthesis scenarios, the Querier achieves 100% example-recommendation accuracy and the Classifier achieves 100% device-classification accuracy. The paper also reports 100% accuracy for GPT-4o when converting the 1,350 evaluation intents into the formal specification expected by NetComplete, although that result is explicitly tied to this dataset rather than claimed as universal.

The system-level comparisons support the main claim within the baselines' supported regimes. Against COSYNTH on BGP no-transit problems, CEGS synthesizes correct configurations in 24 seconds to 1 minute 32 seconds, while COSYNTH fails to finish within 300 loops and one hour, then still needs 2 to 22 manual correction loops. Against NETBUDDY on ECMP, CEGS finishes in 42 seconds to 3 minutes 26 seconds, whereas NETBUDDY again fails within 300 loops and three hours. The paper's interpretation is fair: grounding the LLM with retrieved examples and offloading global reasoning to formal synthesis removes the main source of looping.

The scalability results are also meaningful. On a 1,094-router topology, CEGS synthesizes six OSPF Any-path intents in 14 minutes 30 seconds and six BGP Ordered intents in 24 minutes 50 seconds, all validated with Batfish. In a mixed 197-router scenario containing 15 intents across Static, OSPF, and BGP, it finishes in 10 minutes 30 seconds. These experiments exercise both topology growth and intent growth, so they do test the claimed bottlenecks. The main caveat is scope: the paper studies a fixed example corpus, six routing-intent families, and Cisco-style configurations, so the evidence is strong for that slice of NetOps rather than for arbitrary vendor ecosystems.

## Novelty & Impact

The novel move is not "use an LLM for configuration generation" or "use a GNN on network graphs" in isolation. CEGS frames example following and generalization as the missing systems layer between documentation and formal synthesis, then builds an end-to-end pipeline around that claim. The Querier and Classifier operationalize the topology-aware retrieval problem, while the synthesis stage puts the LLM in a deliberately narrow role and reserves correctness-critical reasoning for verifiers and SMT.

That makes the work relevant to both research and practice. For researchers, it is a concrete design pattern for combining retrieval, graph learning, LLMs, and formal methods without letting any one component do work it is bad at. For operators and vendors, it suggests that documentation examples can become machine-usable assets rather than static prose. Even if CEGS itself is not deployed unchanged, the paper likely influences future configuration assistants that sit on top of vendor manuals instead of asking operators to rewrite network knowledge into a new DSL.

## Limitations

The paper is explicit that CEGS depends on documentation coverage. If the manual contains no usable example for a user's intent, the system cannot invent the missing configuration strategy and the operator must go back to the vendor. CEGS is also only as expressive as the formal synthesizer behind it; because the implementation uses NetComplete, supported intents are restricted to what NetComplete can encode and solve.

There are also several model- and dataset-dependent pieces. GPT-4o is used to normalize intents, assign node roles, and translate intents into NetComplete's formal language, so the correctness story still includes an LLM front end. The reported 100% translation accuracy is encouraging but only demonstrated on the paper's 1,350 intents. The example corpus itself requires one-time parsing from manuals, and topology figures are converted with GPT-4o plus manual proofreading. Finally, the number of synthesis loops still grows with network size and policy complexity, reaching 37 loops for the largest BGP Ordered case, so the system is faster than prior LLM-based methods rather than loop-free.

## Related Work

- _El-Hassany et al. (NSDI '18)_ - `NetComplete` fills symbolic templates with SMT, while `CEGS` tries to automate the harder step of deriving those templates from vendor examples in the first place.
- _Beckett et al. (SIGCOMM '16)_ - `Propane` compiles routing intents written in a DSL, whereas `CEGS` starts from natural-language intents and retrieves documentation examples instead of requiring a new language.
- _Ramanathan et al. (NSDI '23)_ - `Aura` also synthesizes routing configurations from high-level intent, but it depends on a dedicated DSL rather than documentation-grounded example following and generalization.
- _Mondal et al. (HotNets '23)_ - `COSYNTH` uses an LLM plus verifier loops to synthesize configurations directly from intent, while `CEGS` narrows the LLM to template generation and leaves concrete policy values to formal synthesis.

## My Notes

<!-- empty; left for the human reader -->
