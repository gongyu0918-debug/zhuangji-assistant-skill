# 需求路由

先识别用途，再分配预算。用户有明确偏好时优先；否则按默认路由。

软件名不是触发条件本身。ComfyUI、SD、PS、PR、AE、Blender、UE、CAD、本地 agent 等词，只有和配电脑、装机、DIY、升级、预算、配置、硬件需求、性能瓶颈、卡顿或跑不动同时出现时，才进入硬件路线；纯安装、教程、插件、命令、报错、工作流或软件使用问题不使用本 skill。

## 口语化需求理解

用户常用装机圈表达 → 路由参数映射：

| 用户说 | 含义 | 路由参数 |
|--------|------|---------|
| 黑色海景房 | 黑色 + 展示型机箱(玻璃侧透) + 审美向水冷权重 + 读取风扇位 | color=black, case_type=showcase, cooler_preference=liquid_when_aesthetic, read_fan_mounts=true |
| 白色海景房 | 白色 + 展示型机箱 + 白色配件 + 审美向水冷/RGB 权重 + 读取风扇位 | color=white, case_type=showcase, cooler_preference=liquid_when_aesthetic, read_fan_mounts=true |
| 无光 / 不要灯 | 不花预算在RGB/灯效上 | rgb=false |
| 纯性能不要颜值 | 性能优先，压外观预算 | aesthetics=false |
| 水冷 / 360水冷 | 用水冷散热 | cooler_type=liquid, radiator=360 |
| 小机箱 / ITX | 紧凑型，MATX/ITX | form_factor=MATX/ITX |
| 低U高显 | CPU够用，显卡拉满 | routing=low_cpu_high_gpu |
| 2K / 4K | 分辨率目标，影响显卡档位 | resolution=2K/4K |
| 能跑多少帧 / 跑满 240Hz、360Hz、500Hz / 1K 500帧 | 游戏帧率参考需求 | read=game-performance.md, run=query_game_fps.py |
| 多开 / 挂机 | CPU核心+内存容量优先 | routing=multitask |
| Intel 还是 AMD / 办公选什么 / 内存要多大 / 风冷能不能压 / 电源要多大 | 硬件选择或原理问答 | routing=hardware_qa, mode=reference |
| 三角洲 / 吃鸡 / CS2 / GO / 瓦 | 热门 FPS / 电竞网游，高帧和 1% low 优先 | routing=fps, cpu_priority=x3d |
| 直播 / 推流 / OBS / 录制 | 需要硬件编码和稳定后台 | routing=streaming, cpu_priority=intel_igpu |
| 为本地 AI 编程/终端 agent 工作流配电脑 / 给 Codex、Claude Code、opencode、OpenClaw、Hermes 配电脑 / 多 agent 并发主机 | 本地终端/IDE agent、项目索引、缓存、测试工具链和可能的本地模型带来的硬件负载 | routing=local_agent, priority=ram_ssd_cpu |
| ComfyUI / SD / Stable Diffusion / 文生图 / 文生视频 | 本地生成式 AI，吃 NVIDIA CUDA、显存、SSD 和内存 | routing=local_ai_image_video, gpu_priority=nvidia_vram |
| PS / Photoshop / Lightroom / 修图 / 摄影后期 | 图片后期，CPU/内存/SSD 优先，中端显卡足够 | routing=photo_editing |
| PR / Premiere / 剪辑 / 视频剪辑 / 达芬奇 / DaVinci | 视频剪辑/调色，按分辨率、编码、特效和显存分流 | routing=video_editing |
| AE / After Effects / 动效 / 合成 | 动效合成，CPU/内存/缓存 SSD 优先，3D 再提高 GPU | routing=motion_graphics |
| Blender / C4D / 3D建模 / 渲染 | 建模、动画、GPU/CPU 渲染分流 | routing=3d_workstation |
| UE / Unreal / Unity / 游戏开发 | 引擎开发，CPU 编译、GPU 视口、内存和 SSD 均衡 | routing=game_dev |
| CAD / AutoCAD / SolidWorks / 建模绘图 | 按 2D/3D/装配规模分流 | routing=cad, ask_software=true |

## 默认路由

本节只做场景识别和轻量映射；具体取舍规则读取 `scenarios.md`。

| 用途 | scenario_id | 备注 |
|------|-------------|------|
| 硬件选择问答 | hardware_qa | 按场景直接解释 CPU/内存/散热/电源/主板等取舍，不强行输出整机 |
| 3A / 单机大作 | gaming_3a | 低U高显路线 |
| 网游 / 日常游戏 | online_gaming | CPU、显卡、内存均衡 |
| 三角洲 / PUBG / CS2 / 无畏契约 / P社策略 | fps_esports | 高帧、1% low、X3D 路线 |
| 直播 / 推流 / 录制 | streaming | Intel 核显、NVENC、编码路线 |
| 本地 agent 硬件配置 | local_agent | 只在用户明确为本地 AI 编程/终端 agent 配电脑时触发 |
| ComfyUI / SD / 文生视频 / 本地模型 | local_ai_image_video | NVIDIA/CUDA、显存、SSD、内存优先 |
| PS / Lightroom | photo_editing | 图片后期 |
| PR / 达芬奇 / 视频剪辑 | video_editing | 编解码、显存、I/O、缓存盘 |
| AE | motion_graphics | CPU、内存、缓存盘 |
| Blender / 3D / 渲染 | 3d_workstation | GPU/CPU 渲染分流 |
| UE / Unity / 游戏开发 | game_dev | 编译、Shader、视口、SSD |
| CAD / 建模绘图 | cad | 先区分 2D、3D、装配和认证需求 |

用户问具体帧率或跑满刷新率时，读取 `game-performance.md` 并运行 `query_game_fps.py`；未收录游戏或硬件组合不要编 FPS。

## 预算阶梯 (2026 中文市场)

| 预算 | 典型配置 | 注意 |
|------|---------|------|
| 4000 | i5-12400F/12100F + Arc B570/B580/RTX5050, H610/B760 D4 + DDR4 | 只承诺 1080p 入门；按实时总价选择显卡和主板，可用 16GB 内存或 500/512GB TLC SSD 临时压价 |
| 5000 | i5-12400F/13400F + RTX5060, B760 D4 + DDR4 32GB | 主流入门，优先 Intel D4 平台 |
| 6000 | i5-13400F/14400F + RTX5060, B760 D4 + DDR4 32GB | 首先考虑 Intel + D4；RTX5060Ti 8GB 作为行情允许或加预算升级项，AM5/7500F 只在用户看重后续平台时说明取舍 |
| 6500-7500 FPS | R5 5500X3D/R7 5700X3D/R7 5800X3D + B550 + DDR4 3600 + RTX5060/5060Ti | 仅热门 FPS 低价例外路线；必须比较 Intel D4/AM5，不采用二手/99新 |
| 7000 | i5-13400F/14400F/14600KF + RTX5060Ti, B760 D4/D5 | 2K入门3A，仍可用 Intel D4 保性价比 |
| 8000 | i5-14600KF/R5 9600X + RTX5060Ti/RTX5070 | 2K高画质；纯游戏若 RTX5060Ti 16GB 价格接近 RTX5070，优先 RTX5060Ti 8GB 压预算或加钱上 RTX5070 |
| 10000 | i5-14600KF + RTX5070 | 4K入门, 需16pin电源 |
| 12000 | R7-9700X + RTX5070/RX9070XT | 2K高刷 |
| 15000 | R7-9800X3D + RTX5070，或 R7-9700X + RTX5070Ti | 按 FPS/高刷或 3A 显卡优先分流；更高组合必须先实算总价 |
| 16000 | R7-9800X3D + RTX5080 | 游戏优先，保电源/散热/机箱风道 |
| 20000 | R7-9800X3D + RTX5080高规格 | 4K高端，不默认为纯游戏上 9950X3D |
| 25000+ | R7-9800X3D/9950X3D + RTX5090D/RTX5090 | RTX5090、RTX5090D 和 RTX5090D V2 分开比价；按纯游戏或生产力分流 |
| 130000+ | RTX PRO 6000 Blackwell 96GB + 128GB/192GB+ 内存 + 4TB+ SSD | 仅本地大模型/LLM、超大显存工作站或明确商用认证需求；普通游戏/ComfyUI 不默认上 |

低于4000元不硬出完整游戏新主机，建议提高预算、走新品办公入门/核显过渡，或按旧机升级模式只列新品升级件。

## 选件优先级

先满足用途和预算，再看外观。不要把每个品类的最低价候选直接拼成整机。

1. 优先选择数据完整的配件: 有 `price_cny`/`price_status`/`price_date`，并且关键兼容字段不为空。
2. 避开硬件范围外的老平台和老规格: DDR3、120/128GB SATA SSD、Intel 11代及更早、RTX 40/RX 7000 等不作为新装机首选。AM4 只保留 X3D + B550 + DDR4 的低预算 FPS 例外路线，不作为普通新装机默认平台。
3. 最终整机报价应尽量贴近用户预算: 常规目标为预算的 92%-102%；低预算可到 90%，但必须说明取舍。
4. 首版总价超过预算 5% 时，先回查主板、机箱、散热和风扇等非核心溢价；能在不破坏容量、供电、兼容和场景底线时，应压回预算附近。仍无法闭合时，明确给出"可用方案"和"压预算方案"的差异，不要假装刚好卡进预算。
5. 查询候选时按品类分开跑，通常用 `--limit 50` 起步；高预算或白色/海景房等强约束场景用更大的 limit 后二次筛选。CPU、显卡、内存和 SSD 低于可信行情日低价地板时不作默认方案；显卡、内存、SSD 还可按同规格/同定位分布过滤明显低价。CPU 不按同型号中位数离群算法删除，只按日低价地板、具体型号、代际、盒装/散片口径和同价位性能比较。
6. 中高端装机查询显卡、主板、系统盘/生产力 SSD 和内存候选时用 `--sort tier`: 显卡按芯片等级优先（如 RTX 5070 优先于 RTX 5060Ti），主板按芯片组等级优先（B760/B650 优先于 H610/A620），SSD/内存按公开采用率信号、规格完整度和关键参数优先。SSD 若只要求 1TB/2TB，不要被 4TB 顶级盘首屏带偏；先贴合用户容量，再比较 PCIe 代际、TLC、缓存、保修和价格。
7. 候选收窄按依赖顺序做，不要每类各取最低价后拼单:
   - 选主板时用已选 CPU 的 socket/供电需求过滤；选 CPU 时反向核对已选主板 socket。
   - 选内存时用主板 DDR 代际、可支持频率、槽位和容量上限过滤；用户需要 64GB/96GB/128GB 或进入生产力/本地 AI 路线时用 `--min-capacity ... --max-capacity ... --sort tier` 收窄；输出必须写清容量、频率和时序。
   - 选电源时用已选整机功耗加余量过滤，不只看显卡推荐瓦数。
   - 选机箱时用主板版型、显卡限长、散热限高/冷排位和电源规格过滤；显卡限长建议留 20-30mm 以上余量，前置冷排、厚风扇、转接线或静音机箱留更大余量。
   - 最后再用 `check_compatibility.py --strict --require-complete` 做全单校验。返回待复核状态时不能写成完整通过，应换字段完整候选或列人工复核项。

## 预算配平参考

这些是软约束，用来避免低价候选把整机拉偏，不是固定模板。

| 预算 | 配平重点 |
|------|---------|
| 4000 | 只承诺 1080p 入门游戏；优先 Intel D4 + 16GB 双通道，显卡从 Arc B570/B580、RTX5050 或同价位候选按实际总价比较。1TB TLC 无法闭合时可降到 500/512GB TLC，并明确后续扩容；必须保留机箱、电源和散热预算。 |
| 5000 | 优先 6 核 CPU + B760 D4；按整机实算在 DDR4 16/32GB、500GB/1TB TLC 和 Arc B580/RTX5050/RTX5060 间取舍。RTX5060 只有不牺牲电源、机箱和 SSD 底线时采用，否则给加预算升级项。 |
| 6000 | 默认先试 Intel 12/13/14 代 + B760 D4 + DDR4 32GB + 1TB TLC，把显卡目标放在 RTX5060/同档；RTX5060Ti 8GB 作为行情允许或超预算升级项，不把 16GB 版当主流默认。闭合不了时给“贴预算方案”和“加预算升级方案”两档。 |
| 7000 | 2K 3A 优先显卡和 32GB 内存；Intel D4 仍是性价比优先项；整机小计不要在未含机箱时就贴满 7000。 |
| 8000 | 白色/海景房有外观、水冷和风扇溢价，优先 Intel D4 + RTX5060Ti 8GB/同档闭合整机；AM5 9600X 作为性能或升级性方案，若与白色整机底线冲突则单列加预算方案。7500F 只作为预算受限取舍。 |
| 10000 | RTX 5070/同档显卡优先，电源必须留 16pin/12V-2x6 余量。 |
| 12000 | 游戏+生产力优先 8 核 CPU、32GB 起步、2TB SSD；重度剪辑提示 64GB 可能超预算。 |
| 15000 | 当前地板下先在“9800X3D + RTX5070”和“9700X/同档 CPU + RTX5070Ti”之间按用途二选一；32GB DDR5-6000 低延迟、2TB TLC、850W ATX 3.x 金牌和合格散热不降级。9800X3D + RTX5070Ti 只有全单实算能闭合或用户接受超预算时采用。 |
| 20000+ | 9800X3D + RTX 5080 高规格为纯游戏默认方向；RTX 5080/5090 档优先 1000W ATX 3.x 电源，生产力/直播剪辑再考虑 9950X3D、64GB 内存和更大 SSD。 |

4000/6000 低预算、8000 白色海景房、RTX5060Ti 8G/16G、ROG 全家桶、本地 AI/ComfyUI、RTX PRO 工作站等场景细则见 `scenarios.md`。

## 后续读取

- 已确认要输出具体型号、完整配置、升级方案、配置补全或搭配检查时，继续读取 `selection-policy.md`。
- 只做意图路由、纯方向问答或硬件知识解释时，不加载完整选件策略；按需读取 `hardware-faq.md`。
- 具体用途仍读取 `scenarios.md`，价格和兼容字段分别读取 `pricing.md`、`compatibility.md`。
