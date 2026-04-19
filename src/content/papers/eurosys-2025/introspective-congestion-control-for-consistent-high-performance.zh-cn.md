---
title: "Introspective Congestion Control for Consistent High Performance"
oneline: "ICC 先把时延波形塑造成可识别的稳定轮廓，再只在 FFT 判断路径稳定时信任 RTT 和带宽推断，从而把高吞吐和低排队时延同时保住。"
authors:
  - "Wanchun Jiang"
  - "Haoyang Li"
  - "Jia Wu"
  - "Kai Wang"
  - "Fengyuan Ren"
  - "Jianxin Wang"
affiliations:
  - "Central South University"
  - "Tsinghua University"
conference: eurosys-2025
category: networking-and-dataplane
doi_url: "https://doi.org/10.1145/3689031.3696084"
code_url: "https://github.com/Wanchun-Jiang/ICC-Introspective-Congestion-Control-for-Consistent-High-Performance"
tags:
  - networking
  - datacenter
  - observability
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

ICC 抓住的核心问题不是「反应够不够快」，而是发送端经常在不该相信的时候相信了路径推断。它先把自己的速率调节塑造成一种对称、可检测的时延振荡，再用 FFT 观察最近的 `RTTstanding` 序列，只有当这种轮廓连续稳定出现时，才去更新 `RTTbase` 和 `C/N` 之类的隐藏路径量。论文在仿真、Internet 实验和 Alipay 的 QUIC 线上部署里都展示了同一个结果：吞吐不吃亏，排队时延明显下降。

## 问题背景

论文对现有拥塞控制的批评很直接：很多方案已经不满足于看到拥塞就退，而是会主动做路径条件推断，可这些推断经常没有可信度检查。BBR 依赖 `ProbeRTT` 和 `ProbeBW` 去估计 base RTT 与瓶颈带宽，Copa 则通过周期性地把队列放空来估计 base RTT。问题在于，网络条件本来就可能在变，或者探测动作本身就会扰动测量对象；一旦推断结果过期或出错，后面的速率控制就会沿着错误方向继续前进。

这类错误在现实网络里尤其致命，因为场景跨度太大了。论文考虑的既有数据中心级别的微秒 RTT，也有卫星链路那种 800ms RTT；既有无线网络里的随机丢包，也有不同流数量、不同链路带宽不断变化的公共 Internet。学习型方案当然试图用训练去覆盖这些变化，但它们的代价是训练成本、可解释性差，以及遇到未见场景时的不确定行为。ICC 想保留手工设计控制器的可推理性，同时把一致性做出来。

## 核心洞察

ICC 最重要的想法是：不要直接从原始时延信号里盲目猜路径状态，而要先让控制器自己制造出一种只有在稳定路径下才会出现的可识别信号。它把速率增减设计成对称结构，于是当路径条件不变时，瓶颈队列会围绕一个较低平衡点做周期性、近似对称的振荡。这个振荡在频域上会留下稳定主频；如果相邻两个 FFT 窗口里主频差不多、平均 RTT 也差不多，就说明此时主要是 ICC 自己的控制律在塑造信号，而不是外界路径变化在主导信号。

有了这个前提，ICC 才去相信主动探测的结果。它会在稳定期探测 `RTTbase`，并把最终合适的步长和 `C/N` 关联起来；一旦这种频域轮廓消失，ICC 就停止相信新的路径推断，只拿上一个可信状态留下来的参数去做快速响应。换句话说，ICC 把「推断路径」变成了一个先验条件更严格、而不是默认总能成立的动作。

## 设计

ICC 围绕 standing RTT 工作。它把排队时延定义为 `Qd = RTTstanding - RTTbase`，再通过一个对数目标速率函数来决定当前应该逼近哪个发送速率，其中 `Bd` 负责限定目标排队区间，`Rc` 决定速率尺度。真正的更新律是对称的：当前速率低于目标时按某个单位增加，高于目标时按同样形状减少。论文认为，这种对称性既让稳态时的队列振荡保持低幅度，也让它的频域投影变得可监控。

整个控制器可以分成四层。第一层是 profile sculpting，本质就是这套对称速率调节规则。第二层是 projection monitor：ICC 周期性地对最近的 `RTTstanding` 做 FFT，先用较长窗口起步，等稳定主频出现以后，再按主频调整窗口长度。如果连续两个窗口里的主频和平均 RTT 都接近，ICC 就把当前状态视为路径基本不变、平衡点也没有漂移。

第三层是 proactive probe。ICC 用一个 AIMD 规则调节步长 `lambda`，让队列振幅逐渐扩大，直到碰到当前的 `RTTmin` 推断。如果扩大的过程中又看到了更小 RTT，就说明原来的 `RTTmin` 估大了，需要修正。与此同时，最终收敛下来的 `lambda` 会对应 `C/N`，因为它正好把振幅推到平衡点附近。探测成功后，ICC 会把振幅减半，把运行点拉回更低时延区域，同时保留那个已经证明有用的步长。第四层是 fast response：当发送端已经连续两个 RTT 以上都在增速时，`theta` 会按 RTT 加倍，让它迅速抓住新增带宽；否则回到 1。当频域轮廓消失时，ICC 冻结 `RTTmin` 和上一次可信的 `lambda`，只做快速响应，不接纳新的路径推断。

论文还加了一个 competition mode 来应对 Cubic 这类 buffer-filling 流。ICC 会比较 RTT 与 `cwnd` 在频域和时域上的协调程度；如果两者明显脱节，或者队列时延已经超过它自己的控制上界，就判断当前共享链路里存在把缓冲区持续顶满的对手。此时 ICC 会抬高自己的平衡点，并像 Cubic 一样在丢包时做乘性减小，以提升 TCP-friendliness。

## 实验评估

这篇论文的实验面很宽，而且大部分都正好对准它宣称的优势，也就是在变化环境里保持稳定表现。作者分别在 NS3、Linux 用户态和 QUIC 里实现了 ICC。先看真实 Internet：他们在 Amsterdam、Frankfurt、Toronto、Seoul 四个云节点之间用 Pantheon 跑跨洲和洲内链路，ICC 的吞吐比 BBR 高 20.4%，比 Copa 高 27.4%，比 Cubic 高 31.1%，比 Indigo 高 10.1%，比 Remy 高 24.1%，比 Vegas 高 48.1%，比 PCC-Vivace 高 15.3%，同时平均排队时延和尾时延都保持在较低水平。

更能说明机制是否成立的是诊断型实验。异构 RTT 场景里，ICC 能持续推对 `RTTbase`，而 Copa 在路径变化后会把最小 RTT 更新错。覆盖宽 BDP 范围的实验里，ICC 在吞吐和时延之间给出最好的整体折中。随机丢包从 1% 到 10% 时，ICC、BBR、Copa 都能基本吃满链路，而 Cubic、Orca、Vivace 会因为把非拥塞丢包当成拥塞而明显掉吞吐。流进入离开的动态实验里，ICC 也比 Cubic、BBR、Copa 更快、更平滑地回到公平点。

应用层结果同样有说服力。数据中心里的 web-search 工作负载上，ICC 对 64KB 以下小流的 FCT 相比 DCTCP 降了约 9.9 倍，基本追上 Copa 的低时延表现，同时还能按可用带宽自适应调整自己的步长。在 Alipay 的 QUIC 生产部署里，ICC 的吞吐与 BBR 接近且高于 Cubic，但 80% 的记录其排队时延低于 152ms，分别比 BBR 和 Cubic 低 22.8% 与 40.6%；看 90% 截点时，降幅仍有 13.1% 和 26.5%。这些结果基本支撑了论文的中心论点，不过在卫星链路这类超大 RTT 场景里，ICC 主要赢在更低时延，而不是绝对最高吞吐。

## 创新性与影响

ICC 的创新点不只是又发明了一套 delay-based 控制律，而是提出了一个新的设计顺序：先把控制器本身塑造成能留下稳定频域签名的系统，再利用这个签名去判断当前的路径推断到底值不值得信。这和 BBR、Copa 那类默认探测结果可以直接使用的做法不一样，也和学习型方案把一切判断塞进模型内部不同。它给出的，是一种更可解释、更容易做失效分析的路线。

所以 ICC 的影响很可能不只属于这一篇 paper。哪怕未来有人不照搬它的对数目标速率，也不照搬 FFT 细节，这种「先判断环境是否适合测量，再根据测量调节控制器」的思路，本身就很可能被后续 CC 设计借走。论文真正贡献的，既是一个协议，也是一个控制器设计范式。

## 局限性

ICC 的第一条限制来自时间尺度。论文明确说了，如果流太短，或者路径条件变化太快，发送端就来不及把频域轮廓辨认出来。此时 ICC 会退化成更普通的 delay-based 控制器：还能快速响应，但拿不到那部分经过自检的路径推断收益。换句话说，它最有辨识度的那套 introspection，在最短的小流场景里反而最难完整发挥。

第二条限制来自信号质量和共享瓶颈假设。ICC 依赖足够准确的时延测量，也依赖多个流对同一瓶颈队列看到的变化大体一致。作者还特别指出，当不同流的 base RTT 相差极大时，发送端感知到的瓶颈变化会发生明显错位，这时所有 CC 都会变差。competition mode 里的阈值也是经验性设定，TCP-friendliness 主要靠实验而不是严格推导来证明。最后，理论分析建立在简化队列模型上，而实现里每个流还要承担 FFT 的状态和计算开销，只是论文认为这部分开销是有界的。

## 相关工作

- _Arun and Balakrishnan (NSDI '18)_ - Copa 也会通过塑造时延行为去推断 `RTTbase`，但 ICC 多了一层显式 introspection，只有在目标轮廓真的出现时才信任这类推断。
- _Cardwell et al. (CACM '17)_ - BBR 的带宽与 base RTT 推断依赖主动探测；ICC 的核心观点则是，探测结果应该先经过由时延信号本身导出的可信度检查。
- _Dong et al. (NSDI '15)_ - PCC 通过直接优化经验效用来追求跨场景一致性，而 ICC 选择保留手工设计控制器，让推断过程始终可解释、可检查。
- _Abbasloo et al. (SIGCOMM '20)_ - Orca 借助学习来跨网络环境泛化；ICC 试图在不引入训练环节的前提下，用轻量级 introspective 机制达到类似的一致性目标。

## 我的笔记

<!-- 留空；由人工补充 -->
