---
title: "History Doesn't Repeat Itself but Rollouts Rhyme: Accelerating Reinforcement Learning with RhymeRL"
oneline: "Uses cross-epoch rollout history for speculative decoding and length-aware co-scheduling, reducing RL rollout time and GPU bubbles without changing RL semantics."
authors:
  - "Jingkai He"
  - "Tianjian Li"
  - "Erhu Feng"
  - "Dong Du"
  - "Qian Liu"
  - "Tao Liu"
  - "Yubin Xia"
  - "Haibo Chen"
affiliations:
  - "Shanghai Jiao Tong University, Shanghai, China"
  - "ByteDance, Shanghai, China"
conference: asplos-2026
doi_url: "https://doi.org/10.1145/3779212.3790172"
tags:
  - llm-training
  - scheduling
  - gpu
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

RhymeRL speeds up LLM reinforcement learning by treating previous-epoch rollouts as reusable history. It uses that history twice: HistoSpec turns similar token prefixes into speculative drafts for faster generation, and HistoPipe pairs long and short rollouts across adjacent steps to reduce idle GPUs. On the authors' deployments, this improves end-to-end training throughput by up to 2.6x over veRL without changing the RL objective or hurting model quality.

## Problem

The paper starts from a blunt measurement: in modern LLM post-training, rollout dominates the wall-clock budget. On the authors' 32B math and code runs, rollout consumes 84%-91% of total RL time at 16K generation length, and more than 95% once maximum response length grows to 32K or beyond. That cost is painful because rollout is also a poor hardware match: autoregressive decoding is memory-bandwidth-bound, and the longest sample in a batch stalls reward and training for everyone else.

The second bottleneck is imbalance inside a rollout batch. Different prompts produce very different reasoning lengths, so some rollout workers finish early and sit idle while waiting for the tail. The paper reports more than 46% GPU idleness in veRL and shows cases where the earliest-finishing GPU is idle for about 76% of the rollout interval. Existing fixes are unsatisfying. Truncation-based methods cut the tail but trade efficiency against correctness because later tokens come from stale weights. Fully asynchronous systems such as AReaL keep GPUs busier, but they relax the rollout-train dependency and pay recomputation overhead when weights change. The authors want a system that keeps current RL semantics intact while attacking both rollout time and rollout bubbles.

## Key Insight

The central claim is that RL rollouts across adjacent epochs are much more repetitive than people assumed. Mainstream algorithms such as PPO, GRPO, and DAPO deliberately constrain policy updates through clipping and gradient clipping, so the model evolves steadily rather than chaotically. Because the same prompts are revisited over multiple epochs, that stability makes history predictive.

The paper measures two kinds of predictability. First, token sequences for the same prompt in neighboring epochs are highly similar: 75%-95% of tokens can be reused as speculative drafts. Second, response-length distributions are stable enough for scheduling: after ranking prompts by generated length, only 2%-4% of responses experience major rank shifts across adjacent epochs. Once you accept that "rollout history rhymes," history stops being passive logging metadata and becomes an online systems primitive. It can accelerate decoding and also forecast which workers should receive long versus short work in the next step.

## Design

RhymeRL keeps the familiar disaggregated RL pipeline: rollout workers generate responses, reward workers score them, and train workers update the policy. The new piece is a set of history workers running on otherwise idle CPU resources. They index finished rollouts, ship prompt-specific history back to rollout workers, and provide length-ranking hints to the controller.

HistoSpec is the first half of the design. For each prompt, RhymeRL builds a suffix tree over historical responses from the last rollout. During decoding, the current response uses its last few generated tokens as a prefix, looks for a matching suffix in that tree, and proposes the following tokens as a speculative draft. Because multiple historical branches may share the same prefix, the tree is reward-aware: each branch carries priority derived from the rewards of responses that traversed it, so the system prefers drafts from historically high-reward continuations. The paper argues this is a better fit for RL than generic corpus-based drafting because it aligns speculation with the policy's own training signal.

The second HistoSpec ingredient is an AIMD-like control loop for how many draft tokens to speculate. The window starts at 2 tokens, grows additively by 2 when all draft tokens are accepted, and snaps back to 2 after any rejection, up to a default cap of 32. Prefix length similarly backs off from 7 to 3 if matching fails. This avoids the usual speculative-decoding tradeoff between wasting verification work on overly long drafts and leaving throughput on the table with overly short drafts. The appendix further shows that HistoSpec preserves the target model's output distribution because its model-free draft is just a one-hot proposal plugged into standard speculative sampling.

HistoPipe is the scheduling half. RhymeRL ranks prompts by historical response length, forms ranking groups, and then alternates their placement across neighboring rollout steps: odd steps assign short-to-long groups in ascending order, while even steps assign them in descending order. The intent is to let a long group in one step overlap with a short group in the next, reducing bubbles over time rather than demanding perfect balance inside a single step. Outliers are handled by migration-based tail rebalancing. If a rollout is both in the last 10% of unfinished work in its group and longer than a growth threshold derived from history, RhymeRL either migrates it within the current step or defers it to the next one after KV-cache recomputation. A second-tier scheduler then gives more rollout workers to the long groups than the short ones, using profiled execution-time curves and binary search to approximate a linear completion-time distribution instead of an exponential long tail.

## Evaluation

The evaluation is substantial and mostly aligned with the paper's claim. The authors run on 16 nodes with 128 Hopper GPUs, training Qwen3-8B, Qwen3-14B, and Qwen2.5-32B models on internal math and code datasets, with veRL and AReaL as the main baselines. They keep rollout/train-worker configurations matched across systems, which matters because scheduling papers are otherwise easy to overfit to hand-tuned resource splits.

The headline result is strong: RhymeRL improves end-to-end training throughput over veRL by up to 2.6x, with about 1.9x average gains at 8K max generation length and about 2.3x average gains at 16K. Against AReaL, it improves throughput by up to 2.1x when AReaL's off-policyness is 1, and still wins when the threshold is relaxed to 8. The ablation study also tells a coherent story. On Math-14B, HistoPipe alone gives a 1.43x gain, Two-tier Scheduling adds another 1.10x over the naive hybrid pipeline, and HistoSpec adds a further 1.50x. On Code-14B the same pattern appears, with slightly smaller but still material gains.

The micro-results support the mechanism. HistoSpec increases per-step rollout throughput by up to 1.86x, and its acceptance rate stays in the 65%-79% range while increasing over training. HistoPipe reduces per-10-step training time by up to 1.68x, while migration remains limited to 2.2%-5.5% of math samples and 1.6%-4.6% of code samples. Most importantly, the accuracy curves on AIME24, AIME25, SimpleRL Hard, and CodeR1 validation tasks track veRL closely, which supports the authors' claim that they improved systems efficiency without buying speed through stale-policy drift. I found that argument convincing for multi-epoch RL on repeated-prompt datasets, which is exactly the regime the paper targets.

## Novelty & Impact

Relative to _Sheng et al. (EuroSys '25)_, RhymeRL inherits the disaggregated RL architecture of HybridFlow but adds the missing optimization target: the rollout stage itself. Relative to _Leviathan et al. (ICML '23)_ and _Miao et al. (ASPLOS '24)_, its novelty is not speculative decoding alone, but adapting speculation to RL by using prompt-local historical rollouts plus reward-aware branch selection instead of a draft model or generic inference cache. Relative to fully asynchronous RL systems such as AReaL, its main contribution is proving that much of the same efficiency headroom can be captured without changing the training semantics.

That makes the paper important to teams building large-scale post-training infrastructure. The likely impact is practical rather than purely conceptual: if repeated-prompt RL remains the default recipe for reasoning models, RhymeRL offers a direct systems blueprint for reclaiming rollout waste. The fact that HistoSpec was merged into veRL's codebase strengthens the case that the design is implementable beyond the paper prototype.

## Limitations

RhymeRL depends on history being informative. The first epoch has no history at all, and the paper's answer is operational rather than algorithmic: pre-warm traces, reuse previous runs, or exploit multi-response sampling to seed history. The benefits should also shrink when prompts are not revisited across epochs or when model behavior changes too abruptly; that is my inference from the design, not a directly measured claim.

The system also spends real CPU memory and profiling effort to make history useful. In one large setting, suffix-tree storage stays under 80 GB of host memory per node with 8 nodes, which is acceptable on the authors' machines but not free. Gains are weaker at higher sampling temperature, which confirms that the method is tied to cross-epoch regularity. Finally, the evaluation is broad across model sizes and algorithms, but still centered on a repeated-prompt RL workflow with internal math/code datasets. The paper does not address multi-model serving, radically different RL algorithms, or scenarios where rollout history is sparse or privacy-constrained.

## Related Work

- _Sheng et al. (EuroSys '25)_ — HybridFlow provides the controller and disaggregated RL architecture RhymeRL builds on, but it does not shorten rollout execution or balance rollout length tails.
- _Leviathan et al. (ICML '23)_ — speculative decoding gives the theoretical distribution-preserving foundation, while RhymeRL specializes it to one-hot history drafts and RL-specific control logic.
- _Miao et al. (ASPLOS '24)_ — SpecInfer also uses tree-structured speculative inference, but for general LLM serving rather than repeated-prompt RL rollouts with reward-aware branch choice.
- _Kwon et al. (SOSP '23)_ — PagedAttention makes large-scale LLM execution practical, whereas RhymeRL targets the scheduling and decoding inefficiencies specific to RL post-training on top of such runtimes.

## My Notes

<!-- empty; left for the human reader -->
