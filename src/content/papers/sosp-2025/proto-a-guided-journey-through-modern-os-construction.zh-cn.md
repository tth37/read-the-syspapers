---
title: "Proto: A Guided Journey through Modern OS Construction"
oneline: "Proto 把 OS 教学变成基于真实 Raspberry Pi 硬件的五阶段应用驱动构建路径，只在需要时加入文件、线程、多核、媒体与桌面机制。"
authors:
  - "Wonkyo Choe"
  - "Rongxiang Wang"
  - "Afsara Benazir"
  - "Felix Xiaozhu Lin"
affiliations:
  - "University of Virginia"
conference: sosp-2025
doi_url: "https://doi.org/10.1145/3731569.3764811"
code_url: "https://github.com/fxlin/uva-os-main"
tags:
  - kernel
  - scheduling
  - memory
  - filesystems
  - hardware
category: embedded-os-and-security
reading_status: read
star: false
written_by: "gpt-5.4 (codex)"
summary_date: 2026-04-18
---

## TL;DR

Proto 认为，instructional OS 要想既有教学性又真正吸引学生，关键不是继续围绕孤立子系统出题，而是让学生在真实 ARM 硬件上沿着一串可运行应用把系统逐步做出来。它把完整系统拆成五个彼此自洽的 prototype，从 bare-metal 图形一路走到支持 DOOM、视频、音乐和桌面的 multicore OS，同时性能仍足以在 Raspberry Pi 3 上真正演示和使用。

## 问题背景

传统 instructional OS 往往把“覆盖 OS 概念”放在第一位，但它们和学生真正想构建、想展示给别人看的程序之间常常有明显距离。headless shell、简化文件系统和若干 toy utility 确实能教 abstraction，可它们很难消解学生对 systems work 的直觉印象：复杂、枯燥、看不见成果，而且一旦出错就极其挫败。论文认为这在今天更突出，因为 OS 课越来越像 elective，学生未必缺能力，更可能缺的是投入这门课的动机。

反过来，如果直接拿 Linux 或 Android 教学，又会遇到另一种失败模式：系统很真实，但代码体量太大、抽象层太多，学生无法体验从零构建整套系统。Proto 想要的中间路线是：代码规模仍能被一个学期掌控，但里程碑必须是情绪上可感知、展示上有说服力的成果，例如旋转 donut、Mario、音乐播放、DOOM，以及能在便携 commodity hardware 上运行的 desktop。

## 核心洞察

这篇论文最重要的主张是，应用应该充当 OS 设计的 dependency oracle。也就是说，课程和系统都不应先罗列“标准子系统清单”再给每个子系统找作业，而应先选定一串目标应用，再反推每个应用真正需要的 minimum viable mechanism。这样做能让每个 prototype 都自成一体，让每个抽象都有肉眼可见的理由，也避免为了“课程完整性”而无节制堆功能。

这个方法之所以有效，是因为作者挑选的应用能把依赖关系暴露成非常具体的失败模式。图形输出需要 framebuffer 和 timer；Mario 逼出 user/kernel separation 与 page table；音乐播放逼出 asynchronous I/O、DMA 和 synchronization；DOOM 与 blockchain miner 则自然要求 nonblocking I/O、threads、multicore 和 window manager。incremental prototype 因而不只是教学脚手架，而是控制复杂度且不牺牲现实感的核心方法。

## 设计

Proto 的完整系统是一个 ARMv8 monolithic kernel，整体结构接近 xv6：kernel 运行在 EL1，user program 运行在 EL0，进程拥有独立地址空间，系统提供 28 个 syscall，并通过 procfs/devfs 风格接口暴露设备与进程信息；存储则采用 ramdisk 加 FAT32 的组合。真正关键的设计动作，是作者先把这套完整系统做出来，再把它拆成五个仍可独立运行的 snapshot。

Prototype 1 是 bare-metal I/O：单应用、单核、没有 privilege separation，只有 framebuffer、timer interrupt 和 polling UART。它的教学重点不是“先把终端打出来”，而是让图形从第一步就成为一等公民，使最早的成果已经足够可展示。Prototype 2 加入 multitasking 和简单 scheduling，让多个 donut 以不同节奏并发旋转。Prototype 3 再引入 user/kernel separation、virtual memory、类似 fork/exec 的 task management，以及对 framebuffer 的直接映射，从而让 userspace 的 Mario 能在自己的地址空间里运行。

Prototype 4 开始让系统摆脱 toy OS 的味道。它把 xv6 的简易文件系统移植到 ramdisk 上，引入 file syscall、framebuffer/audio/keyboard 的 device file、通过移植 bare-metal USB stack 支持 USB keyboard，并用 DMA 驱动音频输出。这个阶段的 Mario event loop 还被刻意组织成基于 IPC 的结构，好让 students 直观看到 asynchronous input 是如何进入系统设计的。Prototype 5 再补上 richer app 所需的重型机制：SD card 上的 FatFS、小型 polling SD driver、nonblocking I/O、`clone(CLONE_VM)` 风格线程、semaphore 与用户态同步原语、在 Pi 3 四核上扩展的调度，以及一个作为 kernel thread 运行的紧凑 window manager，用来合成 surface 并向焦点窗口分发输入。

文中有两个设计选择尤其能说明 Proto 的取向。第一，作者反复选择那些能让现有库容易移植的简单 UNIX-like interface，即便它们未必是最“优雅”的理论设计。第二，论文对真实硬件上的 self-hosted debugging 投入很大，包括 ARM debug exception、stack unwinder、event tracing 和 GPIO 触发的 panic button，因为他们明确把“能在 QEMU 之外活下来”视为系统目标的一部分。

## 实验评估

评估分成两半：系统是否真的可用，以及这种设计是否真的有教学价值。先看系统侧。完整 prototype 的 kernel 大约 33K SLoC，但 kernel core 仍低于 10K SLoC，规模上仍落在 instructional OS 可接受的区间。microbenchmark 给出的开销也不夸张：一次 syscall 约 3.4 微秒，单向 IPC 约 21 微秒；在同一台 Pi 3 上，大多数延迟与 xv6 接近，也大致落在 Linux 和 FreeBSD 的 0.5x 到 2x 范围内。更关键的是应用结果：Proto 可以把 DOOM 跑到 61.8 FPS，把 480p 视频跑到 26.7 FPS，而不同软件结构下的 Mario 版本则落在约 72 到 115 FPS。手持平台上的功耗约为 shell 空闲时 3W、游戏或媒体负载下约 4W，对应大约 3.7 小时和 2.6 小时的电池续航。

这些结果与论文的“可演示、可使用”主张基本一致。作者使用同一硬件、同一编译器配置和同一套应用源码对比 Linux/FreeBSD，使得吞吐比较即便不是全面胜出，也至少是可信的；Proto 输给 production OS 的主要是 `fork()` 和文件 I/O，这和它故意保持简化的实现一致。较弱的一半在教学证据：2025 年春季课程中，59 名学生里有 48 人完成问卷，结果显示大多数学生认可四条设计原则，且有 64% 的学生主动尝试真实硬件。这能支持“动机更强”的叙事，但终究仍是单门课程、单次开课、以自我报告为主的证据。

## 创新性与影响

相对 xv6、Pintos 这类经典 teaching OS，Proto 改变的不是某个 kernel algorithm，而是课程与系统共同设计的基本单位：从“完成一个子系统”转向“解锁一个应用里程碑”。相对基于 Linux 或 Android 的教学方式，它又坚持让学生拥有整套系统，而不是只在 production codebase 上做局部修改。论文的真正新意，因此是把 OS architecture、硬件目标和 lab progression 一起设计成一条在一个学期内可理解、可展示的“现代 OS 构建路径”。

这类贡献是有价值的。对教育者而言，可复用的恰恰是这套 decomposition 本身；对系统研究者而言，论文提醒我们，在 systems education 里，“是否可展示、是否可玩、是否能让人愿意拿给别人看”并不是表面包装，而是学生理解 abstraction boundary 的一部分。

## 局限性

Proto 对“现代 OS”做了明确取舍。它没有实现 crash consistency、networking、pthreads、signals 和 HDMI audio；原因要么是这些能力缺少足够有说服力的应用驱动，要么是实现成本会压垮课程节奏。即便已经纳入系统的部分，也常带有明显简化：SD driver 用 polling 而不是 DMA，FatFS 通过 pseudo-inode 适配进现有接口，window manager 则放在 kernel 内部，以避开跨进程图形 IPC 的复杂性。

教学评估的说服力也弱于论文整体叙述。文中没有和 xv6 课程或 Linux 课程做 controlled comparison，没有长期 retention study，也没有证明同一套 prototype 顺序能无缝迁移到别的学校或别的硬件平台。论文引用的学生反馈本身也揭示了代价：真实硬件的开发环境会带来额外摩擦，作业压力不小，而 breadth-first 的设计天然牺牲了对单个 subsystem 的深入挖掘。

## 相关工作

- _Hovemeyer et al. (SIGCSE '04)_ - GeekOS 也让学生扩展一套 bare-metal OS，但 Proto 把课程推进的单位改成越来越丰富的图形化应用和真实设备演示。
- _Pfaff et al. (SIGCSE '09)_ - Pintos 同样采用顺序式小型 OS lab，但它的里程碑是经典子系统；Proto 的里程碑则是迫使这些子系统出现的 end-user app。
- _Andrus and Nieh (SIGCSE '12)_ - 基于 Android 的教学从 production software 获得现实感，而 Proto 则把系统压到学生仍能“拥有整机”的规模。
- _Gebhard et al. (SIGCSE '24)_ - 在 bare-metal RISC-V 上教授 Embedded Xinu 与 Proto 一样重视真实硬件，但 Proto 把 media-rich app、USB、FAT32 和 windowed interaction 放到了主要的激励循环里。

## 我的笔记

<!-- 留空；由人工补充 -->
