---
title: "Radshield: Software Radiation Protection for Commodity Hardware in Space"
oneline: "Radshield 用空闲期电流建模检测 SEL，并用冲突感知的并行三模冗余拦截 SEU，让普通航天计算机也能靠软件抵御辐射。"
authors:
  - "Haoda Wang"
  - "Steven Myint"
  - "Vandi Verma"
  - "Yonatan Winetraub"
  - "Junfeng Yang"
  - "Asaf Cidon"
affiliations:
  - "Columbia University, New York, NY, USA"
  - "Jet Propulsion Laboratory, California Institute of Technology, Pasadena, CA, USA"
  - "Aptos Orbital, Palo Alto, CA, USA"
conference: asplos-2026
category: hardware-and-infrastructure
doi_url: "https://doi.org/10.1145/3760250.3762218"
tags:
  - hardware
  - fault-tolerance
  - energy
reading_status: read
star: false
written_by: codex
summary_date: 2026-04-18
---

## TL;DR

Radshield 的核心观点是，航天器上的 commodity Linux 计算机并不一定只能在“裸奔”和“使用昂贵抗辐射芯片”之间二选一。它把软件保护拆成两部分：`ILD` 通过空闲期电流建模检测 latchup，`EMR` 则通过冲突感知的并行冗余执行来捕获 `SEU`，同时规避共享且未受保护的 cache。结果是，它能提供接近工程可部署的辐射防护，同时把运行时和能耗开销压到远低于朴素三模冗余的水平。

## 问题背景

这篇论文的出发点是空间计算的经济现实已经变了。发射成本持续下降之后，运营方更愿意发射大量低成本卫星，而这些卫星又越来越需要在轨完成成像、导航、网络处理和局部数据分析等计算任务。传统抗辐射处理器当然更可靠，但在性能与成本上明显落后于 commodity 芯片。于是，真正的任务系统已经开始把 Raspberry Pi、x86 CPU、手机 SoC 这类现成 Linux 平台送上天。

问题在于，计算能力是买到了，可靠性却掉了一截。论文聚焦于运维上最常见、代价也最高的两类辐射故障。`SEL` 会形成局部短路，导致电流上升、芯片发热，如果不及时 power cycle，最终可能造成永久硬件损坏。`SEU` 则会翻转 bit 或注入异常信号，轻则触发崩溃，重则产生 silent data corruption。作者强调这些不是实验室里的极端情形，而是现实任务里已经发生过的事故，包括 SmallSat 计算机被烧毁、火星车软件被 SEU 扰动，以及推理与加密计算被单 bit 错误破坏。

现有方案两头都不满意。`SEL` 检测通常把设备当黑盒，只盯着电流本身看；但现代 CPU 会因为负载和 DVFS 自然出现很大的电流波动，而一个 micro-`SEL` 的额外电流可能只有 `0.07A`，完全淹没在正常噪声里。`SEU` 防护则大多依赖串行的三模冗余 `3-MR` 或 checksumming，这会显著增加运行时间、能耗和热量。对电源和散热都很紧张的航天器来说，这种开销会直接吞掉本来能拿来做任务的预算。所以真正的问题是：能不能利用 Linux 已经看得到的执行状态，用软件把辐射错误检测得更准、掩蔽得更省？

## 核心洞察

论文最重要的洞察是，一旦不再把计算机视为黑盒，软件层面的辐射防护就会变得更有效。对于 `SEL`，关键不是“当前电流是不是很高”，而是“在当前执行状态下，这个电流是不是异常地高”。由于航天器常常在一段计算突发之后长时间空闲，Radshield 可以专门在 quiescent window 中观察系统；在这些阶段，正常电流更稳定，小幅异常也更容易看出来。

对 `SEU` 来说，核心命题是：并行冗余只有在多个副本没有共享同一份脆弱状态时才真正成立。把三个副本同时跑起来当然能缩短暴露时间，但如果它们读写了同一片未受保护的 cache line，那么一次 cache upset 就可能同时污染三个副本，投票也救不回来。Radshield 的回答是显式建模数据重叠关系：只有当多个冗余 job 在 reliability frontier 之下不会互相冲突时，才允许它们并行执行。

## 设计

Radshield 由两个组件组成。`ILD` 负责处理 latchup。它直接从航天器电源监控芯片读取真实电流，而不是依赖 CPU 自己估算出来的功耗计数器；同时每毫秒收集一次 OS 可见性能指标，并用一个轻量级 linear model 预测“当前本应有多少电流”。作者选取的特征包括 instruction completion、bus cycle、频率、branch miss、cache hit 和磁盘 I/O。检测刻意只在 quiescence 阶段发生，因为论文观察到空闲期的维护任务负载波动远小于应用执行期。如果长任务迟迟没有自然空闲窗口，`ILD` 会主动插入三秒的 quiescence bubble；如果这次观测没有发现异常，就在接下来的三分钟内不再插 bubble。为了压制瞬时尖峰，它还会在采样点前后维护一个 rolling minimum current，只有当“实测电流 - 预测电流”的偏差持续抬高一段时间后才触发 reboot。

`EMR` 负责处理 upset。开发者把工作负载表达成“同一个函数在很多 dataset 上反复执行”，每个 dataset 又是一组内存区域。Radshield 先把这些实例化成 job，再创建三个冗余 executor，并自动检测冲突：如果两个 job 会访问重叠的内存区域，它们就不能在同一个时刻运行。不会冲突的 job 会被打包成 jobset 并行执行；不同 jobset 之间则插入 cache flush，保证一次共享 cache 中的 upset 不会传染到多份副本。

这里最关键的系统抽象是 reliability frontier。frontier 以内、受硬件保护的部分，例如 ECC storage，很多时候还包括 ECC DRAM，可以被视为可信，不需要再做三份复制；frontier 以外的部分，如 pipeline、cache，以及某些没有 ECC 的 DRAM，则必须靠软件冗余来覆盖。这个抽象让同一个运行时可以适配不同航天平台，而不是把保护策略写死。为了进一步减少 cache flush 的成本，`EMR` 还会把高频共享的 common data，例如 AES key 或模板图像，复制到各个 executor 的私有内存里，从而把原本必须串行的冲突点重新变成可并行工作。整个实现都保持在 userspace、运行在未修改的 Linux 之上，这也符合论文的部署前提：任务方通常愿意接受用户态库，但极不愿意在上天前改动 kernel。

## 实验评估

论文把 `ILD` 和 `EMR` 分开评估，而且平台选择很贴近真实部署。`ILD` 运行在与作者 SmallSat 实际使用相同的 Raspberry Pi Zero 2 W 上，通过并联一个可控电阻来模拟 latchup，并执行真实 flight software 工作负载。`960` 小时实验里，`ILD` 没有漏掉任何一次诱发的 `SEL`；相比之下，黑盒基线表现很差，不论是 random-forest 分类器还是静态阈值法，都同时出现较高的漏检和误报。论文还做了一个灵敏度实验：只要额外 latchup 电流超过 `0.05A`，`ILD` 就不再出现 false negative，而这个阈值低于先前工作报告的最小 `0.07A` micro-latchup。运行期开销方面，负载下的平均 runtime 增幅约为 `3%`，而主动插入 idle bubble 的最坏开销约为 `2%`，对“保住设备不被烧毁”这个目标来说是相当可接受的。

`EMR` 的评估覆盖了五类代表性工作负载：AES 加密、DEFLATE 压缩、基于正则的入侵检测、图像处理，以及一个神经网络基准。和串行 `3-MR` 相比，EMR 在达到同等正确性目标的同时明显更高效，因为它把计算并行化了，并且把 cache clear 的成本摊薄到了 jobset 边界。论文报告，和现有主流保护方案相比，EMR 平均能把 runtime overhead 降低 `63%`，把能耗降低 `60%`。细粒度图表也说明了这个结论：EMR 相比一个不安全的并行基线只慢 `7-77%`，却能覆盖全部脆弱区域；而受保护的 `3-MR` 则要慢得多。reliability frontier 的实验也很关键：把可信状态落在 DRAM 上显然比落在磁盘上快得多，但无论 frontier 在哪，EMR 都仍然优于 `3-MR`。最后，在图像处理 workload 上的 fault injection 中，`EMR` 和 `3-MR` 都没有出现 silent data corruption；它们仅在最后结果比较这一极短窗口里保留少量残余暴露面。

我认为这组实验对主张的支撑是比较扎实的。工作负载并不是只挑一个最容易成功的内核，而是覆盖了不同冲突图形态和不同共享数据模式；再加上火星任务中的部署案例，整篇论文的“可落地性”是成立的。最大的保留意见在于，部分可靠性论证仍然是间接的：由于 QEMU 型 fault injector 不能真实地对 cache 状态单独注错，作者只能依靠运行时结构和分析模型来说明 shared cache 不会同时污染三份副本。

## 创新性与影响

相较于 _Dorise et al. (RADECS '21)_，Radshield 在 `SEL` 方向上的新意是，不再孤立地判断电流尖峰，而是结合软件可见执行状态，在 quiescence 时段里预测“应有电流”。相较于 _Shen et al. (DSN '19)_，它在 `SEU` 方向上的贡献也不只是“把冗余执行搬到 multicore 上”，而是进一步基于内存区域冲突做调度，避免共享且未受保护的 cache 破坏并行投票。相较于 _Borchert et al. (DSN '23)_ 这类 checksum 路线，Radshield 追求的是一种更通用的 runtime，能跨多种航天 workload 部署，而不要求每个应用都重新做一次算法级改造。

因此，这篇论文的价值同时面向体系结构研究者和航天系统工程实践者。它真正改变的不是某一个底层指令技巧，而是部署假设本身：既然 commodity hardware in space 已经是现实，那么合理的比较对象就不再是“理想但昂贵的抗辐射硬件”，而是“今天的软件到底能把现成硬件保护到什么程度”。

## 局限性

Radshield 明确是一个 userspace best-effort mitigation，而不是端到端可靠性封装。kernel 基本不在它的保护范围里，作者主要依赖任务侧经验来论证航天 workload 在 kernel 中停留时间极短。如果某个任务的中断更频繁、driver 更复杂、或者 kernel activity 明显高于论文假设，这个前提就会变弱。`ILD` 还依赖平台能够暴露可信的电流遥测，并且依赖系统存在足够多的自然或人工 quiescence 窗口，以便在热损伤真正积累之前发现 latchup。

`EMR` 也假设 workload 具有相对明确的结构：同一段计算在许多 dataset 上重复执行，而且这些 dataset 的重叠关系可以分析。这覆盖了重要的图像处理、加密和模式匹配场景，但并不能涵盖所有 onboard 应用。它的性能还强烈依赖 reliability frontier 的位置，以及有多少 common data 值得复制。最后，论文的 fault injection 方法没法直接制造“只发生在 cache 中、不会同步污染主存”的错误，因此有一部分正确性论证仍建立在精心设计的运行时不变量之上，而不是直接测量。

## 相关工作

- _Dorise et al. (RADECS '21)_ — 只根据电流轨迹做辐射高电流事件检测，而 Radshield 额外利用白盒执行状态特征和空闲期检测逻辑。
- _Shen et al. (DSN '19)_ — 研究在 COTS multicore 上做冗余执行容错，但 Radshield 进一步处理了 shared-cache conflict 下的数据流正确性问题。
- _Borchert et al. (DSN '23)_ — 用编译器插入 differential checksum 来保护内存值，而 Radshield 瞄准的是覆盖 cache、pipeline 与运行时调度的一般化软件模型。
- _Wang et al. (HotNets '23)_ — 从更高层面提出软件抵御 space radiation 的必要性；Radshield 则把这个方向落实为一个可部署的双组件系统，并给出了地面实验与飞行部署。

## 我的笔记

<!-- 留空；由人工补充 -->
