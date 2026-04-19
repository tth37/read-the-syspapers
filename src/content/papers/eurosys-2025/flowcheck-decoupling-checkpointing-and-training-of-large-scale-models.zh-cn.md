---
title: "FlowCheck: Decoupling Checkpointing and Training of Large-Scale Models"
oneline: "FlowCheck 在交换机侧镜像 DP allreduce 流量，在训练路径之外重建梯度并逐迭代更新 checkpoint，因此保存 checkpoint 不再阻塞训练。"
authors:
  - "Zimeng Huang"
  - "Hao Nie"
  - "Haonan Jia"
  - "Bo Jiang"
  - "Junchen Guo"
  - "Jianyuan Lu"
  - "Rong Wen"
  - "Biao Lyu"
  - "Shunmin Zhu"
  - "Xinbing Wang"
affiliations:
  - "Shanghai Jiao Tong University"
  - "Alibaba Cloud"
  - "Peking University"
  - "Zhejiang University"
  - "Hangzhou Feitian Cloud"
conference: eurosys-2025
category: ml-and-llm-systems
doi_url: "https://doi.org/10.1145/3689031.3696088"
code_url: "https://github.com/AlibabaResearch/flowcheck-eurosys25"
tags:
  - llm-training
  - fault-tolerance
  - networking
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

FlowCheck 把 checkpoint 从训练 worker 身上拆出来，交给挂在数据中心网络里的 CPU checkpoint server 去做。它在交换机侧镜像 data parallel allreduce 流量，从镜像包里重建完整梯度，再在训练路径之外执行同样的 optimizer update。论文在 8 张 A100 的实机上表明，逐迭代保存 checkpoint 时，iteration time 仍与不做 checkpoint 时一致；按作者采用的故障模型估算，有效训练时间可维持在 98% 以上。

## 问题背景

这篇论文抓的不是 checkpoint 本身快不快，而是它为什么总要打断训练。大模型集群的故障频率已经高到不能把 checkpoint 当成后台事务处理。作者引用 OPT-175B 的训练日志：992 张 GPU 的训练平均每天会遇到大约两次故障与回滚。可现有做法里，无论是 PyTorch checkpoint API 还是 CheckFreq，本质上都还是训练节点主动把模型状态搬出显存，于是 checkpoint 与训练天然耦合。论文还给出一个很直观的数据点：千卡级训练任务一次 checkpoint 往往要 10 到 15 分钟，因此工业实践通常只能一小时做一次，这会把故障后的重算浪费放大。

作者对 GEMINI 这类方案也不满意。它的思路是把 checkpoint 流量塞进训练通信的空隙里，看起来不像传统做法那样硬停训练，但 checkpoint 流量依旧来自训练节点本身，也仍然可能和正常通信发生冲突。FlowCheck 想做得更彻底一些：checkpoint 既不暂停训练，也尽量不占用训练节点的通信路径。

机会点来自 DP allreduce。同步训练里，真正驱动模型从第 `t-1` 次迭代走到第 `t` 次迭代的是全局梯度 `Δ_t`。而这些梯度本来就会在 allreduce 里穿过叶交换机。如果网络侧能把足够多的包看到并拼回完整梯度，checkpoint 节点就能在本地重放同样的 optimizer step。难点在于三件事：镜像流里夹杂着别的训练通信；只盯一个端口看 ring allreduce 拿不到完整梯度；镜像链路掉包后也不会像 RDMA 正常链路那样自动重传。

## 核心洞察

FlowCheck 最值得记住的判断是：checkpoint 不一定非得从 worker 的内存里导出，也可以把网络流量本身当作 checkpoint 的事实来源。只要 checkpoint server 得到和训练节点相同的 `Δ_t`，它就能用相同的 optimizer 把本地保存的参数和 optimizer state 一起推进到下一次迭代。

但这不是简单抓包就够了。ring allreduce 里，完整梯度只会在 allgather 阶段出现在网络上；单个被监控端口还会固定缺掉某些 chunk。因此 FlowCheck 把问题改写成一个协议解析问题：先根据 workload、layer 大小、MTU 和 DP group size 预计算每层会发多少包，再用实时 packet count 判断当前包处在哪个阶段、哪一层、哪个 offset。只有这样，镜像出来的 payload 才能被放回正确的梯度位置。

## 设计

整个系统分成两部分。第一部分是流量镜像网络。FlowCheck 假设大规模训练采用常见的静态、同步执行方式，而且 DP 流量会经过叶交换机。在这种前提下，它利用 multi-rail 网络结构，把 CPU-only checkpoint server 部署在与目标 DP group 相同的 leaf switch 之下，并至少镜像两个、推荐镜像三个 GPU 端口的入站或出站流量。checkpoint server 本地持有模型参数和 optimizer state，但正常训练过程中不需要和 worker 做额外同步。

第二部分是 checkpoint update pipeline，也是论文真正有技术含量的地方。系统先用 five-tuple 过滤出训练相关的 RDMA 流，再把每次迭代建模成有限状态机：先是 non-allreduce traffic，然后是 reduce-scatter，最后是 allgather。由于 NCCL 的 allreduce 按 layer 执行，解析器还要结合每层参数量持续推进 packet counter。只有当计数器进入某层的 allgather 区间时，FlowCheck 才会把当前包当作可恢复梯度的一部分，并据此算出它属于哪一层、哪一段偏移，把 payload 写回对应 gradient tensor。reduce-scatter 阶段的包不会被拿来更新 checkpoint，因为那时还不是完整梯度。

为了赶在下一次迭代的镜像流到来之前做完这些事，FlowCheck 把运行时处理拆成流水线。最前面是 Packet Dumper，借助多个 CPU-side DMA engine 把 NIC 上的包实时搬进 huge-page memory；随后由 Packet Parser 解析头部、Data Concatenator 按索引拼接 payload，最后 Model Updater 在某一层梯度收齐后立刻做本地参数更新。论文强调的是 deadline，而不是平均吞吐：如果第 `t` 次迭代的 checkpoint 处理拖到第 `t+1` 次迭代开始，前面的设计就失效了。

镜像链路掉包是另一条主线。因为 checkpoint server 并不在训练 RDMA 连接里，镜像包丢失后不会自动重传。FlowCheck 的办法是利用 ring allreduce 天然存在的重叠副本。不同被监控节点看到的 allgather 流量有部分重复，因此可以互相做冗余备份。论文给出的建议是每个 DP ring 监控三个训练 GPU；在作者实测约 `10^-9` 的镜像链路丢包率下，这会把单次迭代不可恢复的概率压到 `6 x 10^-12`。

## 实验评估

实现上，论文使用双路 Xeon 8369B 加 ConnectX-6 NIC 的 CPU 服务器作为 checkpoint node；训练侧则用两台各带 4 张 A100 40GB 的服务器，并通过禁用机内 NVLink 的方式把它们模拟成 8 个节点。工作负载覆盖 BERT-110M、RoBERTa-330M、GPT-3 1.3B 与 Llama2-7B。主要对比对象是 vanilla PyTorch checkpointing 和 CheckFreq；GEMINI 因未开源，只在讨论中出现。

核心结果比较清楚，但范围也比较集中。在 8 GPU 的 DP-only 与 DP+MP 场景下，FlowCheck 做到每次迭代都保存 checkpoint，同时 iteration time 与不做 checkpoint 时相同。其余基线之所以更慢，是因为训练 worker 仍要承担从 GPU 显存向外搬运 checkpoint 的成本。论文随后把这些单步时延换算成带故障情况下的有效训练时间，给出的结论是 FlowCheck 能保持在 98% 以上，而其他方法会随着模型变大明显下滑。

更关键的是几个系统细节实验。只靠 CPU core dump 包时，100 Gbps 镜像流会丢包；换成多 DMA engine 后，包可以完整落到内存里。流水线式 parser 和 updater 也能在相邻两次 allreduce 之间的时间窗内完成工作，而非流水线版本做不到。可靠性实验则解释了为什么三节点冗余是必要的：两节点冗余仍会留下可见的不可恢复概率，三节点后这个概率才降到足够低。

不过，论文最吸引人的大规模结论主要来自估算，而不是实机。对于 175B 到 1T 的 Megatron-LM 配置，作者借助 Calculon 的时间模型估算在 1536 到 3072 张 GPU 上也能在单次迭代内完成 checkpoint。这说明思路可能有扩展性，但还不能等价于真实生产部署已经被验证。

## 创新性与影响

FlowCheck 的新意不在于把 checkpoint 做得更快一点，而在于换了 checkpoint 的位置。此前工作多半是在 worker 侧继续做文章，例如压缩、分层存储、挪动发送时机；FlowCheck 则问了一个更激进的问题：训练网络里本来就传着足够多的状态，能不能直接从这里恢复 checkpoint，而不再让 worker 额外发送一遍。论文给出的答案是可以，但前提是你得把 allreduce 的结构、镜像部署方式和掉包冗余都设计清楚。

这让它对 LLM training 系统和 datacenter networking 都有启发。即便最后不照搬交换机镜像这一实现，论文也给出了一种值得复用的系统思路：有些容错状态也许已经隐含在应用必经的通信里，重新导出它反而是更贵的路径。

## 局限性

这套设计的适用范围其实不算宽。FlowCheck 依赖静态、同步训练，也依赖 data parallelism 且相关流量经过叶交换机；实做上直接支持的是 ring allreduce。tree allreduce、FSDP、ZeRO-3 等扩展只在讨论部分提到，没有进入正式评测。

部署成本也不能忽略。系统需要额外的 CPU checkpoint server、镜像端口，以及每个 DP ring 至少两个、实际推荐三个被监控节点，才能把掉包风险压到论文声称的水平。如果交换机端口紧张，作者只能讨论用 optical splitter 之类的替代方案。

另外还有几处现实边界。论文明确假设训练流量未加密；如果用了加密通信，checkpoint 节点还得有解密能力。实验实测只做到 8 张 A100，千卡级结果依赖估算。再者，一旦镜像流仍然发生不可恢复的丢包，FlowCheck 还是要通知训练框架在下一次迭代做常规 checkpoint，因此所谓对训练「零影响」实际上建立在镜像链路长期维持极低丢包率这一前提上。

## 相关工作

- _Mohan et al. (FAST '21)_ - CheckFreq 仍由训练 worker 主导 checkpoint，只是优化了暂存路径；FlowCheck 试图把 steady-state checkpoint 完全挪出 worker。
- _Wang et al. (SOSP '23)_ - GEMINI 通过预测网络空隙去塞入 checkpoint 流量，而 FlowCheck 直接从镜像出的训练流量里重建 checkpoint，不再让 worker 额外发一遍。
- _Zhong et al. (PPoPP '23)_ - Swift 通过记录足够的迭代状态来减少故障后的重算，但它仍属于 worker-side 容错设计，不是 network-side 设计。
- _Eisenman et al. (NSDI '22)_ - Check-N-Run 针对推荐模型训练在训练服务器上加速 checkpoint；FlowCheck 面向更通用的大模型 DP 训练，并引入独立 checkpoint node。

## 我的笔记

<!-- 留空；由人工补充 -->
