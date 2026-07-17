# DIY装机助手

`DIY装机助手` 是一个面向中文硬件市场的 Codex / OpenAI Skill，用于根据预算、用途、色系和机箱偏好生成台式机配置单，并通过本地脚本做兼容性检查。

- Skill slug: `zhuangji-assistant-skill`
- 展示名称: `DIY装机助手`
- 当前版本: `0.0.21`
- 许可证: MIT
- 价格参考日期: 以所选条目 `price_date` 为准；整包参考日期运行时读取数据文件 metadata
- 价格来源说明: 数据来自网络公开信息整理，仅供预算参考，不代表实时成交价或可下单价格。

## 能做什么

- 识别常见短需求，例如“预算 5000 主玩 3A 不要颜值”“预算 8000 白色海景房 主玩 3A”。
- 按 CPU、主板、内存、硬盘、显卡、电源、散热、机箱逐类查询候选。
- 生成整机总价、预算差额、取舍说明和下单前复核点。
- 使用 `scripts/check_compatibility.py --strict --require-complete` 检查接口、内存、显卡限长、电源余量、散热限高和机箱版型，并区分硬不兼容与字段待复核。

## 价格提示

Skill 默认使用离线库中的网络价格参考。

每次输出配置报告时，Agent 都应提醒：

```markdown
价格参考日期: 以各行 price_date 为准；全单日期一致时可写统一日期，整包参考日期读取数据文件 metadata。
价格来自网络公开信息整理，仅供预算参考，实际购买前请复核实时价格、库存和具体型号后缀。
```

## 候选池与品牌中立说明

Skill 中的“热门采用 / 常见装机 / 新兴特色”候选池，只是基于网络公开价格、销量、装机采用率、渠道覆盖、规格透明度和数据完整度等公开信号做排序辅助。它不代表项目作者对任何品牌的商业倾向、背书或贬损，也不构成购买引导。

本 Skill 的输出只用于 DIY 知识科普和配置选择参考。最终购买仍应结合实时价格、库存、保修、售后、具体型号后缀、颜色版本、尺寸和个人偏好自行复核。所有品牌名称和商标归各自权利人所有。

## 使用方式

安装到支持 Skill 的环境后，可以直接描述预算和用途：

```markdown
预算 5000，主玩 3A，不要颜值
预算 8000，白色海景房，主玩 3A
预算 12000，黑色无光，主玩 3A
```

如果手动运行脚本，可在 Skill 根目录执行：

```bash
python scripts/query_components.py --category gpu --budget 5000 --sort tier --limit 20
python scripts/check_compatibility.py --strict --require-complete --cpu <cpu-id> --mb <mb-id> --mem <mem-id> --storage <ssd-id> --gpu <gpu-id> --psu <psu-id> --cooler <cooler-id> --case <case-id>
python scripts/validate_library.py
```

## 文件结构

```text
.
├── SKILL.md
├── LICENSE
├── agents/openai.yaml
├── data/
│   ├── components.yaml
│   ├── cases.yaml
│   ├── displays.yaml
│   ├── game_fps.yaml
│   └── price_floors.yaml
├── references/
│   ├── routing.md
│   ├── selection-policy.md
│   ├── workflows.md
│   ├── scenarios.md
│   ├── hardware-faq.md
│   ├── game-performance.md
│   ├── pricing.md
│   ├── compatibility.md
│   └── hardware-scope.md
└── scripts/
    ├── component_inference.py
    ├── query_components.py
    ├── query_game_fps.py
    ├── check_compatibility.py
    └── validate_library.py
```

## 发布边界

本仓库只包含通用 Codex / OpenAI Skill 发布所需文件。`agents/openai.yaml` 是 Codex / OpenAI Skill 的展示元数据，不作为 ClawHub 元数据使用。非运行资料、内部记录和测试过程文件不包含在本发布包中。ClawHub 发布使用单独的 OpenClaw 风格发布目录，二者的元数据和说明面保持分离。

## 免责声明

硬件价格和库存变化很快。本 Skill 输出的是基于离线库中 `price_date` 和当前库 metadata 整理的网络公开信息预算参考，不构成购买承诺。下单前请核对实时价格、库存、保修、具体型号后缀、颜色版本、尺寸和供电接口。
