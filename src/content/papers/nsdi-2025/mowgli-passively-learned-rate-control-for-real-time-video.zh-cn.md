---
title: "Mowgli: Passively Learned Rate Control for Real-Time Video"
oneline: "Mowgli 直接从 GCC 遥测日志学习视频码率控制，再用保守的离线 RL 重排 GCC 风格动作，在不拿真实用户做训练的前提下超过 GCC。"
authors:
  - "Neil Agarwal"
  - "Rui Pan"
  - "Francis Y. Yan"
  - "Ravi Netravali"
affiliations:
  - "Princeton University"
  - "University of Illinois Urbana-Champaign"
conference: nsdi-2025
tags:
  - networking
  - observability
  - ml-systems
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

Mowgli 不再像已有学习式方案那样在真实通话中边试错边训练，而是完全从现网 GCC 产生的遥测日志中学习实时视频的码率控制策略。它把 GCC“方向通常对、时机经常晚”的码率调整当作可重排样本，再结合保守离线 RL 和分布式价值建模去提前做出更好的动作。结果是在仿真与真实蜂窝网络上都优于 GCC，同时避免了在线 RL 训练时对用户 QoE 的伤害。

## 问题背景

论文真正盯住的不是“能不能做出更强的码率控制器”，而是“更强的学习式控制器为什么一直进不了生产”。此前面向实时视频会议的 RL 方案已经证明，它们在动态网络上常常能胜过 Google Congestion Control，尤其是在带宽波动很大的蜂窝网络里。但这些方法要把尚未训练好的策略直接放到真实用户通话里，通过试错积累经验。

代价非常具体。在线 RL 训练期间，62% 的通话平均码率比 GCC 更差，43% 的通话 freeze rate 更高；最糟糕时 freeze rate 可上升 79%，平均码率可下降 77%。对于真正的大规模会议平台，这种训练成本本身就无法接受。

只在 simulation 或 emulation 里训练也不可靠，因为已有工作已经指出 simulation-to-reality gap：一旦遇到真实 codec 行为和网络抖动，策略就可能失效。至于只调 GCC 参数，论文认为也不够，因为 GCC 的局限来自其整体启发式设计，而不只是参数设置。于是核心问题变成：能否既不让未成熟策略碰真实用户，也不依赖高保真模拟器，而是只用现网已有数据学出更好的控制器？

## 核心洞察

Mowgli 的核心观察是，GCC 的日志比表面上更有价值。GCC 的主要缺点往往不是“方向完全错了”，而是“反应太慢”或“爬升太保守”。带宽下降时，它最终还是会往低码率走；带宽恢复时，它最终也会往高码率走。也就是说，在那些表现不佳的日志里，已经包含了许多“正确但来迟了”的动作。

这让学习目标从“发明全新动作”变成了“把已有动作用在更合适的时机”。论文用一个受限 oracle 说明了这一点：即便 oracle 只能从 GCC 日志里已经出现过的动作中挑选，只要它知道真实网络变化，仍能显著提升码率、降低 freezes。

不过离线学习必须正面处理两种不确定性。第一是 distribution shift：日志没有直接反馈“如果在别的状态下提前用这个动作会怎样”，过度外推会把 actor 推到训练数据不支持的区域。第二是环境噪声：相同的 `(state, action)` 在不同实例里可能因为 codec 行为或网络随机波动而得到不同结果。Mowgli 的方法就是把这两件事显式编码进学习过程里：对外推保持保守，对回报建模成分布而不是单个期望值。

## 设计

Mowgli 的工作流分成三步。第一步是数据处理。系统从生产环境中已有的遥测日志里提取 `(state, action, reward)` 轨迹。状态由大约每 50 ms 采样一次的应用层和传输层统计组成，并取一个 1 秒窗口，包括发送码率、确认码率、时延与抖动、RTT、丢包率、上一次动作、历史最小 RTT，以及反馈是否陈旧等信息。动作是新的 target bitrate，奖励则是归一化后的 `2 * throughput - delay - loss`。

第二步是离线策略生成。Mowgli 使用 Soft Actor-Critic 训练轻量神经网络策略，并在 actor/critic 前面加 GRU 来提炼时间趋势。模型本身不大：两层 256 维隐藏层、GRU 隐状态 32，最终部署的策略约 7.9 万参数。

真正关键的是它对离线 RL 的两处改造。第一是 Conservative Q-Learning：对日志没有充分支持的动作压低 Q 值，防止 actor 去追逐被错误高估的动作，论文把 `alpha` 设为 0.01。第二是 distributional critic：critic 不再只输出单个期望回报，而是输出回报分布，并用 Quantile Huber loss 训练，从而显式表达环境随机性。部署也很直接：模型在服务端离线训练后下发到客户端，WebRTC sender 通过 IPC 把实时遥测送给 Python 子进程，再取回新的 target bitrate。论文报告模型约 316 kB，CPU 推理约 6 ms。

## 实验评估

实验建立在端到端 WebRTC testbed 上，底层使用 AlphaRTC 和 Mahimahi。作者收集了 87 小时真实网络带宽 trace，来自 FCC 宽带数据集和 Norway 3G 蜂窝数据集，并切成 1 分钟片段；训练、验证、测试按 60%/20%/20% 划分，RTT 在 40、100、160 ms 中随机分配。对比基线包括 GCC、按既有文献实现的 online RL、Behavior Cloning，以及 CRR。

主结果很稳定。仿真网络上，Mowgli 在所有统计分位数上都优于 GCC：平均视频码率提升 14.5% 到 39.2%，freeze rate 降低 59.5% 到 100%，frame rate 最多提升 35.3%，端到端 frame delay 仍保持在 400 ms 交互阈值以内。它与 online RL 的差距已经很小，例如 P75/P90 的 freeze rate，Mowgli 为 0.77% 和 2.87%，online RL 为 0.66% 和 2.41%，而 GCC 分别是 2.09% 和 7.09%。论文还显示，Mowgli 的 bitrate 已经接近一个受限 approximate oracle，上界差距在 6% 以内。

这些收益确实集中在论文最关心的高动态网络上：码率提升 10.8% 到 43.8%，freeze rate 降低 47.4% 到 100%。Behavior Cloning 因为只会模仿日志而过于保守，CRR 在这类单策略日志下甚至比 GCC 更差，这都支持了作者关于“不确定性必须显式处理”的论点。

真实蜂窝网络实验规模更小，但仍有参考价值。作者在美国四个城市的 LTE 网络上测试，先在 Princeton 和 San Jose 收集超过 8 小时 GCC 日志训练，再在“相同城市/相同网络”和“新城市”两种场景中交替运行 GCC 与 Mowgli。结果显示，前一类场景的 bitrate 提升为 3.0% 到 2.1x，后一类场景为 2.0% 到 20.8%。至于 freeze rate，论文认为事件太稀少，样本量不足以下统计显著结论。

## 创新性与影响

Mowgli 最重要的创新不只是“把离线 RL 用在视频码率控制上”，而是提出了一整套更可部署的学习路径：只依赖现网已有遥测、只从一个已部署启发式策略的日志中学习、训练阶段不碰真实用户、部署阶段只替换码率控制逻辑。这比单纯说“离线也能学”更强，因为它直接回应了生产系统最核心的阻力。

从方法上看，论文把三个想法扎实地拼在一起：GCC 日志中的动作重排机会、Conservative Q-Learning 对外推风险的压制，以及 distributional critic 对环境噪声的显式表达。它既不是简单模仿 GCC，也不是把通用 offline RL 原样套进来，而是围绕视频会议的遥测形态与部署限制做了定制。

## 局限性

Mowgli 的首要局限和大多数数据驱动系统一样：它只能在训练日志覆盖到的分布上表现好。论文在跨数据集实验里已经展示了这一点，训练于 LTE/5G 的策略迁移到 Wired/3G 环境时会明显失效，说明一旦网络条件发生显著漂移，就必须重新收集日志并重训模型。

另一个局限是评估范围。原型只覆盖单向视频、不含音频，并通过关闭 WebRTC 的 `DegradationPreference` 来尽量隔离 rate control 的作用。更深一层地说，Mowgli 虽然通过保守学习与分布式价值函数降低了反事实推断风险，但并没有真正消除 latent confounders；在日志稀疏、环境变化更复杂时，它本质上仍可能退回接近 GCC 的保守行为。最强的 freeze 改善证据也仍来自仿真环境，而不是更小规模的真实网络实验。

## 相关工作

- _Zhang et al. (MobiCom '20)_ - OnRL 在移动视频通话中通过在线 RL 学习码率控制，而 Mowgli 的目标正是去掉这种会伤害真实用户的在线探索。
- _Zhang et al. (MobiCom '21)_ - Loki 同样研究学习式实时视频自适应，但 Mowgli 更强调如何只依赖 incumbent controller 的遥测日志完成离线训练并可部署落地。
- _Yen et al. (SIGCOMM '23)_ - Sage 也从日志离线学习拥塞控制，不过它依赖多个 expert TCP policy 的数据；Mowgli 证明只有一个已部署 RTC 策略的日志，在足够保守的学习框架下也能学到改进。
- _Fouladi et al. (NSDI '18)_ - Salsify 通过 codec 与 transport 的协同设计降低实时视频时延，而 Mowgli 保持大体 WebRTC 栈不变，只替换 bitrate controller。

## 我的笔记

<!-- empty; left for the human reader -->
