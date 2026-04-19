---
title: "Towards VM Rescheduling Optimization Through Deep Reinforcement Learning"
oneline: "VMR2L 把 VM 重调度改写成分两步的 RL：先选要迁的 VM，再选合法目标 PM，并用稀疏注意力和多轨迹择优在 5 秒预算内逼近最优方案。"
authors:
  - "Xianzhong Ding"
  - "Yunkai Zhang"
  - "Binbin Chen"
  - "Donghao Ying"
  - "Tieying Zhang"
  - "Jianjun Chen"
  - "Lei Zhang"
  - "Alberto Cerpa"
  - "Wan Du"
affiliations:
  - "University of California, Merced"
  - "University of California, Berkeley"
  - "ByteDance"
conference: eurosys-2025
category: cloud-scheduling-and-serverless
doi_url: "https://doi.org/10.1145/3689031.3717476"
code_url: "https://github.com/zhykoties/VMR2L_eurosys"
project_url: "https://drive.google.com/drive/folders/1PfRo1cVwuhH30XhsE2Np3xqJn2GpX5qy"
tags:
  - scheduling
  - virtualization
  - datacenter
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文最重要的判断是：VM 重调度不是那种可以慢慢算最优解的离线装箱题，因为规划一旦拖太久，集群状态已经变了，原本更优的解反而落不了地。`VMR2L` 用顺序式 RL、先选 VM 再选 PM 的两阶段动作、面向 PM-VM 关系的稀疏注意力，以及多条 rollout 中择优部署来处理这个问题。在 `MNL = 50` 时，它把 FR 做到 0.2941，而近似最优 MIP 是 0.2859；前者 1.1 秒出一条轨迹，后者要 50.55 分钟。

## 问题背景

大规模数据中心里，VM 会不断创建和释放，日常 VM scheduling 必须一直在线，所以工程上只能依赖 best-fit 一类轻量启发式。问题是，这些方法会把 CPU 空闲切得越来越碎，最后虽然总空闲不少，却拼不出一台新的 16-core VM。论文用 16-core fragment rate 来量化这件事。

VM rescheduling 就是离峰时段的整理动作：系统 live-migrate 一小部分 VM，把零散容量重新拼回大块可用空间，同时还要满足 NUMA、CPU/内存和 migration-number limit 等约束。真正麻烦的是，规划过程面对的是一个持续变化的集群。作者在 280 台 PM、2089 台 VM 的 trace 上看到，Gurobi 做 25 次迁移要 1.78 分钟，做 50 次迁移要 50.55 分钟；而回放实验显示，收益能维持在接近最优的前提大约只有 5 秒。超过这个窗口，再漂亮的解也会因为状态变化而失真。

## 核心洞察

论文的核心洞察是，VM 重调度更像一串必须快速完成的局部决策，而不是一次性的大求解。给定当前放置状态和某一步迁移动作，下一步状态是确定的：哪些 PM 还剩多少 CPU、多少内存、哪些 VM 被挪到了哪里，都能精确计算。也正因为环境转移是确定的，作者才敢把问题改写成 offline RL，用历史快照搭一个 simulator 来训练策略。

这样一来，时延反而变成了 RL 的优势。策略可以在秒级吐出合法动作，而 simulator 又允许它在推理阶段采样多条完整轨迹，再只部署结果最好的那条。对这个任务来说，快而近似的控制，往往比慢而精确的优化更能得到好的最终集群状态。

## 设计

`VMR2L` 把一次请求视为最多 `MNL` 步的 episode。状态里有每台 PM 两个 NUMA 的剩余 CPU、剩余内存和 fragment 信息，也有每个 VM 的资源需求与源 PM 上下文。奖励函数不用稀疏终局奖励，而是直接看每一步迁移前后，源 PM 和目标 PM 上 fragment 的变化。

最关键的系统设计是两阶段动作空间。第一阶段只决定哪台 VM 值得迁。第二阶段在 VM 已选定的前提下，把所有放不下它的 PM 按资源、NUMA 和服务约束全部 mask 掉，再从合法目标机里做选择。这样既避开了巨大的 `(VM, PM)` 联合动作空间，也让 hard anti-affinity 之类的约束更容易接入。

另一项关键设计是按放置拓扑定制的稀疏注意力。普通 transformer 看得见所有 VM 和 PM，却不天然理解同一台 PM 上的兄弟 VM 会共同决定某次迁移值不值得。论文把每台 PM 和其上的 VM 看成一棵浅树：先做树内局部 sparse attention，再做 PM-PM、VM-VM 和 VM-PM 的全局交互。这样模型才能学会那种需要连续几步才能真正消掉碎片的迁移链。

## 实验评估

实验使用两个来自真实数据中心的匿名化数据集。Medium 最多有 2089 台 VM、280 台 PM；Large 最多有 4546 台 VM、1176 台 PM；每个数据集都有 4400 个 mapping，并按 4000/200/200 划分训练、验证和测试。训练要 92 小时，用一张 RTX 3090；但部署很轻，checkpoint 小于 2 MB，Medium 上一条轨迹只要 1.1 秒。

最重要的结果和论文主张是对得上的。在 `MNL = 50` 时，`VMR2L` 的 FR 是 0.2941，只比近似最优的 MIP 差 2.86%，而后者需要 50.55 分钟，已经完全错过 5 秒实用窗口。它也稳定压过 HA、`alpha`-VBPP、POP、MCTS、Decima、NeuPlan 等基线。消融实验同样说明设计不是装饰品：去掉 sparse attention 后，FR 退化到 0.3090；不做 risk-seeking rollout 选择，则停在 0.3079。

而且作者没有把证据只压在单一 benchmark 上。论文还评估了多资源约束、anti-affinity、异常 workload、不同 MNL，以及更大的 Large 集群；在 Large 上它依然能在 3.8 秒内生成方案。这说明论文贡献不是单纯对着一个 trace 调参出来的结果，不过证据仍以离线评测为主。

## 创新性与影响

这篇论文的贡献不只是把 RL 套到资源管理上。更准确地说，它先识别出一个特殊的系统约束：规划延迟本身会改变解的质量，然后围绕这个约束重写了整个方案，包括顺序式动作分解、贴着 PM-VM 拓扑设计的状态编码，以及利用精确 world model 做多轨迹择优。和 Decima 相比，它关注的是 post-placement 的 VM 迁移；和 POP、NeuPlan 相比，它把 MIP 完全移出了在线路径。

这种 framing 对别的系统问题也有启发。只要一个控制器同时具备确定性状态转移、大动作空间和秒级决策预算，快而可泛化的 learned control 就可能在真实结果上胜过慢的精确优化。

## 局限性

最大的局限是评估保真度。论文虽然用了真实 trace，但核心比较仍发生在记录下来的 snapshot 和确定性 simulator 上，而不是生产环境闭环里，因此 live migration 的网络占用、dirty page 行为以及和在线调度的相互干扰都没有被完整覆盖。

另外，主目标也比较窄。论文主线聚焦的是面向 ByteDance 风格集群的 16-core fragment rate；虽然作者展示了多资源和混合目标扩展，但没有进一步证明 admission success 或用户侧 SLO 的直接收益。再加上当前动作一次只迁一台 VM，anti-affinity 和 noisy neighbor 处理又依赖先验知识，所以距离完全通用的自治重调度器还有一步。论文也承认，当目标集群的 PM 数量与训练集偏差超过约 20% 时，性能会开始下滑。

## 相关工作

- _Hadary et al. (OSDI '20)_ - Protean 关注的是大规模 VM 的初始放置，而 `VMR2L` 处理的是更棘手的后续重排问题，也就是在已有运行态 VM 上受迁移次数限制地重新整理放置。
- _Mao et al. (SIGCOMM '19)_ - Decima 同样使用 RL 做调度，但对象是数据处理集群；`VMR2L` 则把动作空间和编码器都按 PM 归属关系、NUMA 结构和合法 live migration 约束重新设计。
- _Narayanan et al. (SOSP '21)_ - POP 通过分块后再调用 MIP 来解决大规模资源分配，而这篇论文认为在 VM 重调度里，只要在线路径还依赖 MIP，就很难守住秒级时延要求。
- _Zhu et al. (SIGCOMM '21)_ - NeuPlan 用 RL 先剪枝，再把剩余部分交给 MIP；`VMR2L` 则直接把 RL 当成完整的在线决策器，因为这里最关键的约束就是不能把时间花在后续求解上。

## 我的笔记

<!-- 留空；由人工补充 -->
