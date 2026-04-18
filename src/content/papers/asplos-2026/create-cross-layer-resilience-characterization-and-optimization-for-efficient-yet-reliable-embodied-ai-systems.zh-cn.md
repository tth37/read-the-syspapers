---
title: "CREATE: Cross-Layer Resilience Characterization and Optimization for Efficient yet Reliable Embodied AI Systems"
oneline: "CREATE 用电路异常清除、planner 权重旋转和基于任务关键度的控制器电压调节，让具身 AI 在降压后仍保持任务质量。"
authors:
  - "Tong Xie"
  - "Yijiahao Qi"
  - "Jinqi Wen"
  - "Zishen Wan"
  - "Yanchi Dong"
  - "Zihao Wang"
  - "Shaofei Cai"
  - "Yitao Liang"
  - "Tianyu Jia"
  - "Yuan Wang"
  - "Runsheng Wang"
  - "Meng Li"
affiliations:
  - "School of Integrated Circuits, Peking University, Beijing, China"
  - "School of EECS, Peking University, Beijing, China"
  - "Georgia Institute of Technology, Atlanta, GA, USA"
  - "Institute for Artificial Intelligence, Peking University, Beijing, China"
conference: asplos-2026
category: ml-systems-beyond-llm
doi_url: "https://doi.org/10.1145/3779212.3790147"
tags:
  - hardware
  - energy
  - fault-tolerance
  - ml-systems
  - llm-inference
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

CREATE 的核心判断是：具身 AI 在降压运行时并不是“整体同样脆弱”，而是 planner 更敏感，controller 更耐错，而且 controller 只会在某些关键步骤突然变脆。论文据此做了一个三层协同方案：硬件里清掉大幅度 timing-error outlier，planner 用离线权重旋转缓和 LLM 激活 outlier，controller 则按当前步骤关键度动态调电压。作者在其建模加速器上报告，在任务质量不下降的前提下，平均计算能耗比标称电压降低 `40.6%`。

## 问题背景

现代具身 agent 往往由高层 LLM 或多模态 planner 加上低层 RL controller 组成，既要做长链路推理，又要持续输出细粒度动作，所以在电池供电设备上，计算能耗很快会成为瓶颈。降压看起来是最直接的节能手段，因为动态功耗会随着供电电压显著下降。

但降压带来的不是温和的精度退化，而是 timing violation 和计算位翻转；在具身 AI 里，这会直接表现为任务失败或完成步数暴涨。一次 planner 的错误分解，或者 controller 在关键时刻的错误动作，都可能让整条任务轨迹偏航。已有方案也不太合适：冗余和 timing-borrowing 会增加硬件成本，`ABFT` 类恢复机制可能拖慢实时链路，retraining 型方法又大多面向单个模型。论文真正想解决的是，如何在 planner/controller 这条异构协同栈上做分层的能效-可靠性权衡。

## 核心洞察

论文最重要的洞察是：具身 AI 的容错性具有明确层次。planner 更脆弱，因为 LLM 的 activation outlier 会和后续 normalization 叠加，让单个硬件错误足以把 `mu`、`sigma` 拉歪，从而破坏子任务生成。controller 更耐错，因为它调用更频繁、激活分布更均匀；但它也不是始终稳健，在探索阶段噪声更容易被吸收，在关键执行阶段则会迅速变脆。

因此，合适的方案不是统一加保护，而是把保护精确用在会导致灾难性失败的地方，把节能留给还能容忍噪声的地方。

## 设计

CREATE 有三个部件。第一层是电路级 anomaly detection and clearance（AD），放在 systolic array 的 GEMM 累加输出之后。由于合法 INT8 结果很少占据最高有效位，高位 timing fault 往往会把输出直接推到非法量化范围外；AD 就做范围检查，超界就 clamp 为零。第二层是模型级 weight-rotation-enhanced planning（WR），用并入权重的 Hadamard rotation 把 planner 的 activation outlier 摊平，让 normalization 没那么脆。第三层是应用级 autonomy-adaptive voltage scaling（VS），根据图像和子任务 embedding 预测 controller action logits 的 entropy，再用 LDO 按预测结果调电压，默认每 5 步更新一次。

实现上，论文建模了一个带 `128 x 128` systolic array 的加速器，在输出端接入 AD 单元，并用分布式数字 LDO 把 PE array 电压在 `0.6V` 到 `0.9V` 之间以 `10mV` 步长调整。AD 与 WR 改变的是计算表面，entropy predictor 加上 LDO 策略决定的是 controller 何时可以安全降压。

## 实验评估

实验主要围绕 Minecraft 中的 JARVIS-1，因为它同时具备 LLM planner、Transformer controller 和多阶段长链路任务。硬件方面，作者基于商用 `22nm` PDK 做后布局估计；planner 延迟为 `11.2 ms`，controller 延迟为 `942 us`，entropy predictor 延迟为 `8.57 us`。新增硬件开销也确实很小：AD 只增加 `0.08%` 面积和 `0.10%` 功耗，分布式 LDO 增加 `0.13%` 面积和 `0.14%` 功耗。

单个部件的收益很清楚。对 planner 而言，在 `BER = 1 x 10^-5` 时，AD 把 `wooden` 成功率从 `0%` 提高到 `85%`，把 `stone` 从 `0%` 提高到 `83%`；在 `BER = 2 x 10^-5` 时，WR 又把两者成功率分别提高 `43%` 和 `40%`，平均步数下降 `33%` 和 `49%`。对 controller 而言，entropy predictor 与真实 entropy 的拟合达到 `R^2 = 0.92`，最终选中的自适应策略在不降低成功率的前提下，把有效电压再压低了 `7.3%`。AD+WR 让 planner 在 `BER = 1 x 10^-2` 时仍能维持任务质量；在八个 JARVIS-1 任务上，`0.75V` 无保护几乎会崩掉，只开 AD 时平均恢复到 error-free 成功率的 `71%`，叠加 WR 后可恢复到 `97%`。

系统级结果也比较扎实。相对标称电压，完整 CREATE 平均节省 `40.6%` 计算能耗；相对作者选取的最强兼容基线，仍可再省 `35.0%`。换算到芯片级，总能耗下降 `29.5%` 到 `37.3%`；论文据此估算整机电池续航可延长约 `15%` 到 `30%`。跨平台结果也有帮助：AD+WR 在 JARVIS-1、OpenVLA、RoboFlamingo 上平均降低 planner 能耗 `50.7%`，AD+VS 在 JARVIS-1、Octo、RT-1 上平均降低 controller 能耗 `39.3%`。这些实验比较支持论文的中心结论，但它本质上仍然是仿真加 fault-injection 研究，而不是实物机器人实测。

## 创新性与影响

和 _Agarwal et al. (ISSRE '23)_ 相比，这篇论文不再把 LLM 当成单独对象，而是把 planner 和 controller 作为一个具身系统来分析。和 _Wan et al. (DAC '21)_ 相比，CREATE 面向的是更异构的 agent 架构，并把容错直接绑定到电压调节这一系统杠杆上。和 _Xie et al. (DAC '25)_ 相比，它没有采用偏恢复型方案，而是用电路、模型、应用三层协同换取更低能耗。所以它既会被具身 AI 平台研究者引用，也会吸引体系结构与 dependable ML 社区。

## 局限性

最明显的局限是现实性。论文做了加速器综合、后布局估计和大规模 fault injection，但没有在流片芯片或真实机器人上展示 CREATE 的端到端运行，所以电池续航提升仍然是基于芯片级能耗模型和已有机器人功耗分解得出的估算，而不是实测结果。

第二个局限是故障模型范围。论文聚焦于瞬态计算 timing error，并基本把内存错误交给 ECC 等手段处理；因此它对“整套具身 AI 系统可靠性”的覆盖并不完整。其最强结果也主要建立在 JARVIS-1 这一类 planner/controller 栈之上，WR 尤其依赖大 Transformer planner 的 outlier 加 normalization 脆弱性。entropy 驱动的 controller 策略还需要额外训练 predictor，并为平台搜索 entropy-to-voltage mapping。最后，跨平台泛化是分别移植 planner 和 controller 技术完成的，而不是在 JARVIS-1 之外展示完整端到端 agent 栈。

## 相关工作

- _Agarwal et al. (ISSRE '23)_ — 研究的是独立大语言模型在瞬态硬件故障下的鲁棒性，而 CREATE 处理的是具身 planner/controller 流水线，并利用这种异构性来决定保护策略。
- _Wan et al. (DAC '21)_ — 面向 learning-based navigation systems 的容错分析与改进，而 CREATE 扩展到了带 LLM planner 和低层 controller 的现代具身 agent。
- _Mahmoud et al. (ISSRE '21)_ — 讨论通过 selective protection 提升 CNN resilience；CREATE 则更强调改变 planner 的激活统计特性，以及根据 controller 的执行状态做电压策略。
- _Xie et al. (DAC '25)_ — REALM 关注独立 LLM 推理的统计型 ABFT 可靠性，而 CREATE 更强调面向能量受限具身部署的无恢复跨层协同优化。

## 我的笔记

<!-- 留空；由人工补充 -->
