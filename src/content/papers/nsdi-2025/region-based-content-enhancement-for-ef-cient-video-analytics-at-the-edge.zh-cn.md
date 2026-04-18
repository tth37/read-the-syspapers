---
title: "Region-based Content Enhancement for Efficient Video Analytics at the Edge"
oneline: "RegenHance 预测真正影响分析精度的 macroblock，跨流打包并联合规划 enhancement 与 inference，在比整帧增强高 2-3 倍的吞吐下把精度提高 10-19%。"
authors:
  - "Weijun Wang"
  - "Liang Mi"
  - "Shaowei Cen"
  - "Haipeng Dai"
  - "Yuanchun Li"
  - "Xiaoming Fu"
  - "Yunxin Liu"
affiliations:
  - "Institute for AI Industry Research (AIR), Tsinghua University"
  - "State Key Laboratory for Novel Software Technology, Nanjing University"
  - "University of Göttingen"
conference: nsdi-2025
category: llm-and-ml-training-serving
code_url: "https://github.com/mi150/RegenHance"
tags:
  - ml-systems
  - scheduling
  - gpu
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-19
---

## TL;DR

这篇论文认为，edge video analytics 不应该对整帧做增强，因为真正会改变下游精度的像素只占很小一部分。RegenHance 先预测重要 macroblock，再把这些区域跨视频流致密打包，并联合规划 decoding、prediction、enhancement 和 inference。作者在五类异构设备上表明，它相对直接推理可多拿到 10-19% 精度，同时相对基于整帧的增强基线把吞吐提高到 2-3 倍。

## 问题背景

edge video analytics 面临一个典型矛盾：摄像头便宜、上行带宽有限，而下游 DNN 又对模糊、压缩伪影和低分辨率非常敏感。内容增强能缓解这个问题，因为 super-resolution 或 restoration 模型可以在推理前补回细节；但最直接的做法代价太高，对每一帧都增强会显著拉高时延，并直接和分析模型争抢 GPU 资源。

论文的动机实验说明，已有的 selective frame enhancement 对 analytics 依旧不够好。逐帧 super-resolution 的确能把精度提高 10% 以上，但端到端吞吐相比直接推理会下降 76% 以上。anchor-frame 方法虽然回收了一部分吞吐，但它把增强后的内容复用于邻近帧。对人眼观看来说这通常还能接受，可对 DNN 推理就不成立，因为很小的失真都可能翻转预测结果。为了达到 90% 的目标精度，选择性增强方法平均仍要在一个 120-frame chunk 里增强 27-61 帧，这对 edge server 来说仍然太重。

## 核心洞察

论文最核心的判断是，增强的“工作单位”选错了。真正影响 analytics 的，不是整帧有没有被增强，而是那些增强后会改变下游推理结果的区域有没有被增强。作者把这类区域称为 Eregions。在 object detection 中，超过 75% 的帧里 Eregion 只占整帧 10-25% 的面积；在 semantic segmentation 中，70% 的帧只需要增强 10-15% 的面积。与此同时，增强时延主要随输入尺寸增长，而不是随像素取值增长，所以把其余区域涂黑并不能省时间。

因此，论文提出了一个很明确的命题：只要系统能识别出“哪些 macroblock 的增强最能提升下游精度”，它就应该只增强这些 macroblock，把它们跨流致密批处理，并把资源分配到不会让任何流水线阶段成为瓶颈的状态。由此，系统必须同时解决三个问题：快速预测重要区域、把稀疏区域转成高效的增强输入，以及在异构流和异构设备上做全局调度。

## 设计

RegenHance 由三个部分组成。第一部分是 MB-based region importance prediction。系统不在像素粒度上工作，而是把 H.264 这类 codec 的 macroblock，例如 16x16 MB，作为基本单位。这样既足以捕捉小目标，又比逐像素推断便宜得多。论文定义了一个 importance metric，结合两个信号：下游 analytical accuracy 对像素变化的敏感度，以及相对于 bilinear interpolation，增强会让该像素变化多少。离线阶段，系统先增强训练帧，再对分析模型做一次 forward/backward，得到每个 MB 的重要性标签。

在线阶段，RegenHance 把 MB importance prediction 近似成一个只有 10 个 importance level 的轻量 segmentation 任务。作者重新训练了多个候选模型，最终选择 MobileSeg，因为它在精度上接近重模型，但运行速度快 4-18 倍。为了避免对每一帧都做预测，系统还在时间维度复用 MB importance。它利用压缩流 Y-channel residual 的轻量面积变化算子挑选代表帧，只对这些帧做 importance prediction，再把结果复用于相邻帧。论文报告，这个 predictor 单核 i7-8700 CPU 就能跑到 30 fps，放到 GPU 上可达 973 fps。

第二部分是 region-aware enhancement。RegenHance 先把所有视频流里的 MB 汇总到一个按 importance 排序的全局队列，再选择当前增强预算下最值得增强的前 N 个 MB。由于 enhancement model 需要矩形 tensor，而被选中的 MB 往往是稀疏且不规则的，系统会先把相连 MB 组成 region，再用矩形包围它们，切分过大的 box，并按 importance density 而不是按面积排序。随后，它把这些 box 旋转后尽量塞进固定大小的 bins，在 GPU 上把真实像素拼成致密 tensor，运行 super-resolution，再把增强后的内容贴回经过 bilinear upsampling 的原帧。importance-density 排序是关键，因为传统的大块优先打包会把预算浪费在包含太多无关像素的大矩形上。

第三部分是 profile-based execution planning。RegenHance 把 decoder、importance predictor、enhancer 和 analytical model 看成一张 DAG，在具体 edge 设备上 profiling 每个组件在不同硬件上的吞吐，然后搜索满足时延和精度目标的硬件映射与 batch size。论文用的是 DAG 上的动态规划。这个模块之所以重要，是因为朴素的 round-robin 或串行执行会让 CPU、GPU 长时间闲置，还会把增强预算错误地分给收益较低的视频流。

## 实验评估

实验覆盖两个下游任务，object detection 和 semantic segmentation，并在五类异构设备上运行：RTX4090、A100、RTX3090Ti、Tesla T4 和 Jetson AGX Orin。基线包括 `only infer`、NeuroScaler、Nemo，以及论文自己构造的若干删减版流水线。这个评估设计比较扎实，因为它同时覆盖了轻重两类分析模型，并系统性改变了设备档次、任务类型、分辨率、流数量和目标精度。

最核心的结果和论文命题是一致的。跨设备平均来看，RegenHance 相比直接推理可带来 10-19% 的精度提升，同时相对现有基于整帧的增强方法拿到 2-3 倍吞吐。按论文汇总，object detection 上它的吞吐平均比 Nemo 高 12 倍、比 NeuroScaler 高 2.1 倍；semantic segmentation 上分别高 11 倍和 1.9 倍。在 RTX4090 或 A100 上，它在 1 秒时延目标下可以以约 91% 精度服务 10 路 object-detection 流，总计 300 fps；如果把精度约束收紧到 95%，也还能支撑 6 路流。

组件级分析同样很有说服力。仅靠 execution planning，就能把吞吐从逐帧 SR 的 95 fps 提高到 111 fps。若只加入 MB prediction 而不做 region-aware packing，吞吐并不会继续提升，因为把无关区域置零并不会减少增强时延。一旦启用 region-aware enhancer，吞吐会跳到 179 fps，完整系统最终达到 300 fps。predictor 在 CPU 上比 DDS 风格的 RoI 选择快 60 倍以上，在 GPU 上也快 12 倍以上，而 temporal reuse 还能进一步把它的吞吐翻倍。packing policy 的 occupy ratio 达到 75%，比替代方案最高多 13%；cross-stream MB selection 相比均匀分配多拿到 8-12% 精度，相比固定阈值策略也多 2-3%。这些证据共同支持了论文的中心论点：真正起作用的不是“少做一些增强”，而是细粒度选择加全局调度。

## 创新性与影响

相对于 _Yeo et al. (SIGCOMM '22)_ 的 NeuroScaler 和 _Yeo et al. (MobiCom '20)_ 的 Nemo，这篇论文的真正创新在于把优化单位从“被采样的整帧”换成“按重要性排序的 macroblock”。相对于 _Du et al. (SIGCOMM '20)_ 的 DDS，它也不只是做一般性的 RoI 选择，而是在估计“增强后最会影响 analytical accuracy 的区域”，并把这个估计做到了足够轻，可以在线运行。

因此，这篇论文对支持用户自带模型的 edge video analytics 平台很有价值。它把 task-aware metric、符合 enhancement model 行为的 packing 机制，以及覆盖整条流水线的 runtime planner 组合在了一起。它也为后续 smart camera、edge GPU scheduler 和 analytics-specific video preprocessing 研究提供了一个很具体的结论：合适的增强粒度既不是整帧，也不是面向人类视觉的通用 RoI。

## 局限性

这个系统并不是即插即用的。每一种下游 analytical task 都需要离线生成自己的 importance labels，并针对对应模型单独微调一个 MobileSeg predictor，因为 importance metric 依赖下游模型本身。论文说微调在 8 张 RTX3090 上只要大约 4 分钟，但这仍然是生产系统需要承担的运维成本。

此外，这个方法的收益建立在“重要区域足够稀疏”之上。如果大多数像素都重要，或者 enhancement 的收益分布得很广而不是集中在小区域里，那么 region-based packing 的优势就会明显缩小。实验也只覆盖了 object detection、semantic segmentation 和一种 super-resolution 模型家族，因此对其他视觉任务的证据仍然是间接的。最后，运行时仍然需要按设备做 profiling，并完成 residual extraction 与 GPU-side stitching 等较重的系统集成；论文报告在新设备上做 planning 需要 1-3 分钟，而视频流集合变化时初始化还需要 0.6-2 秒。

## 相关工作

- _Du et al. (SIGCOMM '20)_ - DDS 选择的是降低卸载成本的 region of interest，而 RegenHance 预测的是“增强后最能提升 analytical accuracy 的 macroblock”，并把选择器做到足够轻量以支持实时运行。
- _Yeo et al. (MobiCom '20)_ - Nemo 选择性增强 anchor frame 并复用增强收益，RegenHance 则指出复用增强内容会伤害推理精度，因此只复用 importance prediction，而不复用增强结果本身。
- _Yeo et al. (SIGCOMM '22)_ - NeuroScaler 在整帧粒度上扩展 neural video enhancement，RegenHance 则把优化对象下沉到跨流 MB region，并把它与资源规划绑定在一起。
- _Lu et al. (SenSys '22)_ - Turbo 利用 GPU 空闲时隙做增强，而 RegenHance 直接重构了增强粒度，并显式平衡 decoder、selector、enhancer 和 inference 四个阶段。

## 我的笔记

<!-- 留空；由人工补充 -->
