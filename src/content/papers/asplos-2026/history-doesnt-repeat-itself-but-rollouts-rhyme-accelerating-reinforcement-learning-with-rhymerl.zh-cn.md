---
title: "History Doesn't Repeat Itself but Rollouts Rhyme: Accelerating Reinforcement Learning with RhymeRL"
oneline: "RhymeRL 利用跨 epoch rollout 历史做 speculative decoding 与长短样本配对调度，在不改变 RL 语义的前提下减少 rollout 时间和 GPU 气泡。"
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
category: llm-training
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

RhymeRL 的核心做法，是把前一个 epoch 的 rollout 当成可复用历史。它一方面用 HistoSpec 把相似 token 前缀变成 speculative draft，缩短生成时间；另一方面用 HistoPipe 在相邻 step 之间配对长短 rollout，减少 GPU 空转。作者报告显示，在不改变 RL 目标函数、也不损伤模型质量的前提下，它相对 veRL 的端到端训练吞吐最高可提升 2.6x。

## 问题背景

这篇论文先抓住了一个很扎实的现象：在当代 LLM post-training 里，rollout 已经压倒性地主导总耗时。作者在 32B 的数学和代码训练上观察到，当最大生成长度为 16K 时，rollout 占整个 RL 时间的 84%-91%；当最大长度提升到 32K 或更高时，这个比例会超过 95%。问题不只是“时间长”，而是 rollout 本身也很难把硬件吃满：自回归 decoding 天生受内存带宽约束，而同一批次里最长的那个样本会阻塞 reward 和 training 阶段，让所有较早完成的 worker 一起等待。

第二个瓶颈是 batch 内部的不平衡。不同 prompt 会生成长度差异很大的 reasoning chain，于是有些 rollout worker 很早就做完，却只能等着尾部长样本收尾。论文报告 veRL 中存在超过 46% 的 GPU 空闲，并展示了最早完成的 GPU 在一次 rollout 期间约有 76% 的时间处于 idle。现有补救办法都不够理想。基于 truncation 的方案确实能削尾，但会在效率与正确性之间做交换，因为后续 token 变成用 stale weights 继续生成。像 AReaL 这样的全异步系统能让 GPU 更忙一些，但它放松了 rollout-train 依赖，并在权重变化时付出 KV cache 重算的代价。作者想解决的是：不改当前 RL 语义，也同时减少 rollout 时间和 rollout bubbles。

## 核心洞察

论文最重要的判断是，相邻 epoch 之间的 RL rollout 比大家通常以为的更“押韵”。像 PPO、GRPO、DAPO 这样的主流算法，都会通过 clipping 和 gradient clipping 刻意约束策略更新幅度，所以模型演化是渐进的，而不是每一步都剧烈漂移。又因为同一批 prompt 会在多个 epoch 中反复出现，这种稳定性就让历史本身变得可预测。

作者测了两类可预测性。第一，同一 prompt 在相邻 epoch 里的 token 序列高度相似，75%-95% 的 token 可以作为 speculative draft 复用。第二，响应长度分布也足够稳定，若按生成长度给 prompt 排名，真正发生大幅排名变化的响应只有 2%-4%。一旦接受“rollout history 会押韵”这个事实，历史就不再只是日志，而会变成在线系统里的调度信号：它既能帮助加速 decoding，也能预测下一步哪些 worker 更适合接长任务，哪些更适合接短任务。

## 设计

RhymeRL 保留了大家熟悉的解耦式 RL 流水线：rollout workers 负责生成响应，reward workers 负责打分，train workers 负责更新策略。新增的是一组运行在闲置 CPU 资源上的 history workers。它们负责索引已完成的 rollout，把 prompt 相关的历史回传给 rollout workers，并向 controller 提供长度排序信息。

HistoSpec 是第一部分。对每个 prompt，RhymeRL 都会基于上一次 rollout 的历史响应构建 suffix tree。当前响应在 decoding 时，用最近生成的若干 token 作为前缀，到树里查找匹配的 suffix，再把后续 token 作为 speculative draft 提出来。由于多个历史分支可能共享同一个前缀，树不是“命中就随便挑一条”，而是 reward-aware 的：每个分支都带有由历史响应 reward 聚合而来的优先级，因此系统会优先选择历史上高 reward 的续写。论文认为，这比通用 corpus-based drafting 更贴合 RL，因为它直接沿用了策略训练时已经暴露出来的偏好。

HistoSpec 的第二个关键点，是一个类似 AIMD 的 draft 长度控制回路。speculation window 初始为 2 个 token；若这轮 draft 全部被接受，就加性增长 2；一旦有 token 被拒绝，就立刻把窗口重置回 2，默认上限为 32。前缀长度也会在匹配失败时从 7 逐步退回到 3。这样做是为了避免 speculative decoding 里很常见的两难：draft 过长会浪费大量验证计算，draft 过短又吃不到吞吐提升。附录还给出证明，说明 HistoSpec 不会改变目标模型的输出分布，因为它本质上只是把 one-hot 的历史提议代入了标准 speculative sampling。

HistoPipe 是调度部分。RhymeRL 先依据历史响应长度给 prompt 排名并分组，然后在相邻 rollout step 之间交替放置这些组：奇数 step 按从短到长分配，偶数 step 按从长到短分配。它追求的不是“单个 step 内绝对平衡”，而是让相邻 step 之间形成长短互补，从时间维度上消掉 bubbles。异常长尾则由 migration-based tail rebalancing 处理：如果某个 rollout 同时落在本组最后 10% 的未完成任务里，并且长度又超过基于历史增长率得出的阈值，RhymeRL 就会把它迁移到同一步的其他组，或者在重算 KV cache 后推迟到下一步完成。第二层调度再根据 profile 出来的执行时间曲线，把更多 rollout workers 分给长组、较少 workers 分给短组，用二分搜索逼近线性的完成时间分布，而不是让其继续维持指数式长尾。

## 实验评估

这篇论文的实验比较扎实，而且大体上和它的主张是对齐的。作者在 16 台节点、128 张 Hopper GPU 上做评估，训练 Qwen3-8B、Qwen3-14B 和 Qwen2.5-32B，并使用内部数学与代码数据集，把 veRL 和 AReaL 作为主要基线。更重要的是，他们让不同系统使用一致的 rollout/train worker 配置，这一点很关键，因为调度论文最容易通过手工资源切分把比较做偏。

总体结果很强。相对 veRL，RhymeRL 的端到端训练吞吐最高提升 2.6x；当最大生成长度为 8K 时，平均提升约 1.9x；当最大长度为 16K 时，平均提升约 2.3x。相对 AReaL，当其 off-policyness 设为 1 时，RhymeRL 最高提升 2.1x；即使把阈值放宽到 8，RhymeRL 仍然占优。消融实验也讲得通。以 Math-14B 为例，HistoPipe 单独带来 1.43x 提升，Two-tier Scheduling 再相对 naive hybrid pipeline 增加 1.10x，而 HistoSpec 继续再加 1.50x。Code-14B 上也是同样趋势，只是增幅略小一些。

更细粒度的结果也支持机制本身。HistoSpec 的单步 rollout 吞吐最高提升 1.86x，acceptance rate 维持在 65%-79% 之间，并且随着训练推进而上升。HistoPipe 则把每 10 个 step 的训练时间最高缩短到 1.68x，同时迁移比例只占数学样本的 2.2%-5.5%、代码样本的 1.6%-4.6%。最关键的是，AIME24、AIME25、SimpleRL Hard 以及 CodeR1 验证任务上的准确率曲线与 veRL 基本一致，这很好地支持了作者的核心论点：他们得到的速度提升不是靠放松训练语义、引入更严重的 stale-policy 偏差换来的。我认为这点在“多 epoch、重复 prompt”的 RL 场景里是相当有说服力的，而这正是论文的目标应用区间。

## 创新性与影响

和 _Sheng et al. (EuroSys '25)_ 相比，RhymeRL 继承了 HybridFlow 的解耦式 RL 架构，但真正把优化目标推进到了 rollout 阶段本身。和 _Leviathan et al. (ICML '23)_ 以及 _Miao et al. (ASPLOS '24)_ 相比，它的新意不只是“也用了 speculative decoding”，而是把 speculation 专门改造成适配 RL：draft 来源不是额外小模型，也不是通用推理缓存，而是 prompt 局部的历史 rollout，再结合 reward-aware 分支选择。和 AReaL 这类全异步 RL 系统相比，它最有价值的一点，是证明了不少效率空间其实可以在不改变训练语义的前提下拿到。

因此，这篇论文对大规模 post-training 基础设施团队的意义会比较直接。它的影响更像是一张可落地的系统设计蓝图，而不只是一个漂亮的概念：如果“重复 prompt 的 RL 训练”仍然是推理型模型的主流训练配方，那么 RhymeRL 提供了一条非常明确的路线，去回收 rollout 阶段本来被浪费掉的大量资源。论文还提到 HistoSpec 已经合入 veRL 代码库，这也增强了它不只是原型系统的可信度。

## 局限性

RhymeRL 的收益依赖历史本身足够有信息量。第一轮 epoch 没有任何历史，论文给出的解决方案更多是工程性的：预热 trace、复用此前运行记录，或者利用多响应采样先种出一批历史。若 prompt 不会在多个 epoch 中重复出现，或者模型行为变化过于剧烈，这套方法的收益也会下降；这句话是我根据论文设计做出的推断，并不是作者直接测量过的结论。

此外，为了让历史真正可用，系统需要额外的 CPU 内存与 profiling 成本。在一个较大的设置里，suffix tree 的 host memory 开销可以控制在每节点 80 GB 以下（8 个节点），这在作者机器上是可接受的，但并不等于零成本。论文也显示，当采样温度升高时，收益会减弱，这进一步说明该方法绑定于跨 epoch 的规律性。最后，尽管评估覆盖了多种模型规模和算法，但整体仍聚焦在“重复 prompt 的 RL 工作流 + 内部数学/代码数据集”这一类场景，并没有真正回答多模型服务、完全不同的 RL 算法，或者历史稀疏/受隐私约束场景下该怎么办。

## 相关工作

- _Sheng et al. (EuroSys '25)_ — HybridFlow 提供了 RhymeRL 所沿用的 controller 与解耦式 RL 架构，但它本身并不缩短 rollout 执行时间，也不处理 rollout 长度的长尾平衡。
- _Leviathan et al. (ICML '23)_ — speculative decoding 提供了分布保持的理论基础，而 RhymeRL 则把它具体化为 one-hot 历史草稿与 RL 特定的控制逻辑。
- _Miao et al. (ASPLOS '24)_ — SpecInfer 同样利用树形结构做 speculative inference，但它面向的是通用 LLM serving，而不是带 reward-aware 分支选择的重复 prompt RL rollout。
- _Kwon et al. (SOSP '23)_ — PagedAttention 让大规模 LLM 执行更可行，而 RhymeRL 处理的是建立在这类 runtime 之上的 RL post-training 调度与 decoding 低效问题。

## 我的笔记

<!-- 留空；由人工补充 -->
