---
name: zhuangji-assistant-skill
description: 中文市场台式机装机配置助手。用户明确在问预算装机、装机 DIY、硬件 DIY、配电脑、配置单、整机推荐、旧机升级、配置补全、搭配检查、硬件选择问答、预算分配、兼容性或硬件搭配原理，并且目标是选购、升级或评估台式机硬件时使用。触发后可按 3A/FPS、直播推流、为本地 AI 编程/终端 agent 工作流配电脑、ComfyUI/Stable Diffusion/文生视频、PS/Lightroom、PR/达芬奇/AE 视频剪辑、Blender/3D、UE/Unity 开发、CAD/建模绘图、黑/白海景房、无光或纯性能等用途路由；单独询问软件、游戏、agent 或教程使用方法时不要触发。内置离线配件库、价格日期和程序化兼容性检查；不要凭记忆编型号、价格或兼容结论。
metadata:
  display_name: DIY装机助手
  tags: pc-build,hardware,chinese-market,compatibility
license: MIT
---

# DIY装机助手

面向中文硬件市场的台式机配置助手。核心能力是用离线配件库查候选、用脚本做兼容性检查、按预算和需求给可复核配置单。

## 工作流

1. 识别需求并按分支只读必要 reference。
   - 所有需求先读 `references/routing.md`；只有要给具体型号、完整配置、升级、补全或搭配检查时，再读 `references/selection-policy.md`。
   - 命中 3A/FPS、直播、本地 agent 硬件配置、ComfyUI、PS/剪辑/AE/Blender/UE/CAD、黑白海景房、无光、ITX、背插、水冷显卡或 RTX PRO 时，再读 `references/scenarios.md`。
   - 升级、补全或检查读 `references/workflows.md`；硬件选择和软硬件协同问答读 `references/hardware-faq.md`；游戏帧率读 `references/game-performance.md`。
   - 仅在对应口径不清楚时读取 `references/pricing.md`、`references/compatibility.md` 或 `references/hardware-scope.md`。
2. 查候选。运行 `scripts/query_components.py`，不要直接打开 `data/*.yaml`。完整配置至少分别查询 CPU、主板、内存、硬盘、显卡、散热、电源、机箱；中高端显卡、主板、SSD 和内存优先用 `--sort tier`；用户给出现有型号时用 `--model` 定位，已知库内 ID 时用 `--id` 精确定位，定位结果若缺价只用于兼容检查，不参与总价；明确 1TB/2TB 等容量时同时设置 `--min-capacity` 和 `--max-capacity`，避免更大容量挤占首屏。显示器只在用户明确要求“带显示器/推荐显示器”时用 `--category display` 或 `--category monitor` 单独查询。风扇只在海景房补风扇、水冷夹汉堡、风道/无光风扇或用户明确要风扇时用 `--category fan` 单独查询，不进入 `all`。`--budget` 是单品价格上限，不是整机预算。
3. 做兼容性。最终推荐必须运行 `scripts/check_compatibility.py --strict --require-complete`，传入所有核心配件。退出码 `1` 表示存在硬不兼容，`2` 表示未发现硬不兼容但仍有待复核字段，只有退出码 `0` 才能写完整通过；优先换字段完整的候选，确实无字段时单独列人工复核项。
4. 处理价格。离线库优先；离线库不足、价格日期超过 14 天或用户要求实时价格时，再搜索当前市场价。
   - 价格规则不清楚时读 `references/pricing.md`。
   - 机箱必须计入总价；海景房默认读取机箱 `fan_mounts` / `fan_slots_count`，再按水冷占用位预留风扇预算；风道机箱若已自带大风扇，不默认补满风扇位。
   - 养宠/防毛查询可用 `--dust-filter yes` 找候选，但只有 `dust_filter_status=verified` 才能写成已确认防尘；`needs_verification` 必须提示核实滤网位置、覆盖范围和可拆洗方式。
5. 输出配置。按用户语气决定详略；只回答方向或原理且未给具体采购型号时，不强制套整机报价表。只要给出具体采购型号或配置清单，就必须分行列出配件、参考单价、总价、预算差额、兼容性结论、取舍理由、下单前复核点、价格参考日期和“仅供参考，需复核实时价格/库存”的提醒。用户关心游戏帧率时只引用 `scripts/query_game_fps.py` 已收录样本，查不到就说未收录，不自行推算。

## 收录边界

具体硬件范围、型号后缀、显存版本和工作站卡边界见 `references/hardware-scope.md`。低预算 AM4 X3D、RTX5090D V2、RTX5060Ti 8G/16G、水冷显卡、RTX PRO 6000 等特殊路线只在用户需求或场景明确时启用。

## 硬规则

- 不编型号、不编价格、不编兼容性结果。
- 只输出人民币价格，并标注价格参考日期；缺价条目不参与总价。
- 二手、99新、翻新、矿卡、返券后不确定价和主播直播间特殊到手价不属于默认推荐范围；主播截图只作为维护端预算结构观察。
- 公开输出使用中性候选池表达，不输出品牌贬损、商业背书、维护端证据链或来源站点标识。
- 白色配置必须使用白色/白色系配件；黑色配置使用黑色或中性色；无光/纯性能需求不要为灯效和外观溢价牺牲核心性能。
- 机箱必须计入总价；海景房/好看需求必须考虑风扇预算，风扇位缺字段时只提示自行核实，不编具体数量；风道机箱缺风扇位字段时不硬推具体加装风扇。
- 显示器默认不计入整机配置和总价；用户明确要求时才单列显示器候选、参考价和“仅供参考，需按观感/接口/售后复核”的提醒。
- 面向用户不要写脚本命令、退出码、完整度门禁、内部价格状态或脚本状态词；用自然语言说明“兼容性检查完成，未发现硬不兼容”或“现有型号信息不足，仍需复核显卡限长/线材/风扇位”等具体事项。
- 配置报告中 CPU、主板、内存、硬盘、显卡、散热、电源、机箱分别成行；内存写清容量/频率/时序，硬盘写清容量/接口/颗粒或定位，显卡写清芯片和显存容量。

## 脚本

- `scripts/query_components.py`: 查询候选，默认摘要输出，`--detail` 才展开更多字段。
- `scripts/check_compatibility.py`: 11 项兼容性检查，最终配置用 `--strict --require-complete` 区分硬兼容和字段完整度。
- `scripts/query_game_fps.py`: 查询已收录游戏帧率参考样本；不做硬件倍率推算。
- `scripts/validate_library.py`: 发布前/维护时校验库结构和关键字段完整度。
