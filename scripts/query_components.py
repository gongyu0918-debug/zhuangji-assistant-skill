#!/usr/bin/env python3
"""配件查询工具 — 按品类、预算、平台、颜色筛选配件。

渐进式披露: 默认只返回 summary (id+model+price)，用 --detail 看完整属性。

用法:
  python query_components.py --category gpu --budget 5000
  python query_components.py --category cpu --platform intel --limit 5
  python query_components.py --category case --color white --summary
  python query_components.py --category all --budget 8000 --json
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from component_inference import enrich_item

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CATEGORIES = {
    "cpu": "cpus",
    "mb": "motherboards",
    "memory": "memory",
    "storage": "storage",
    "gpu": "gpus",
    "cooler": "coolers",
    "psu": "psus",
    "case": "cases",  # from cases.yaml
}

DISPLAY_NAMES = {
    "cpu": "CPU",
    "mb": "主板",
    "memory": "内存",
    "storage": "硬盘",
    "gpu": "显卡",
    "cooler": "散热",
    "psu": "电源",
    "case": "机箱",
}

# Summary fields per category — minimal fields needed for first-pass narrowing.
SUMMARY_BASE_FIELDS = ["id", "brand", "model", "price_cny", "price_status", "price_date"]
SUMMARY_FIELDS_BY_CATEGORY = {
    "cpu": SUMMARY_BASE_FIELDS + ["platform", "socket", "cores", "threads", "power_w"],
    "mb": SUMMARY_BASE_FIELDS + [
        "platform", "socket", "chipset", "memory_generations", "memory_slots",
        "memory_freq_max", "m2_slots", "sata_ports", "form_factor", "color",
    ],
    "memory": SUMMARY_BASE_FIELDS + [
        "generation", "capacity_gb", "module_count", "frequency_mt", "timing", "color", "rgb",
    ],
    "storage": SUMMARY_BASE_FIELDS + [
        "capacity_tb", "capacity_gb", "form_factor", "interface", "pcie_generation", "storage_type", "series",
    ],
    "gpu": SUMMARY_BASE_FIELDS + [
        "chip", "gpu_vendor", "vram_gb", "memory_type", "length_mm", "power_w",
        "power_connectors", "requires_16pin_psu", "color", "rgb",
    ],
    "cooler": SUMMARY_BASE_FIELDS + ["type", "height_mm", "radiator_mm", "color", "rgb"],
    "psu": SUMMARY_BASE_FIELDS + [
        "wattage_w", "form_factor", "efficiency", "modular", "native_16pin_gpu_power", "color",
    ],
}

COLOR_ALIASES = {
    "white": {"white", "白", "白色"},
    "black": {"black", "黑", "黑色"},
}

RGB_TERMS = ("ARGB", "RGB", "幻彩", "炫彩", "彩色", "彩光", "灯效", "灯光", "发光")
NO_RGB_TERMS = ("无光", "不发光")

# 以下排序只按芯片/芯片组定位辅助筛选，不包含品牌优劣判断。
# 若后续加入品牌/系列候选池权重，应仅基于公开电商销量、装机采用率、
# 渠道覆盖和规格完整度等可观察信号，并保持非品牌倾向、非品牌贬损。
GPU_TIERS = (
    ("RTX5090D", 8), ("RTX5090", 8),
    ("RTX5080", 7),
    ("RTX5070TI", 6),
    ("RTX5070", 5), ("RX9070XT", 5),
    ("RTX5060TI", 4),
    ("RX9070GRE", 3), ("RX9070", 3),
    ("RTX5060", 2), ("ARCB580", 2), ("A770", 2), ("RX9060XT", 2), ("RTX3060TI", 2),
    ("RTX5050", 1), ("ARCB570", 1), ("A750", 1),
)

MOTHERBOARD_TIERS = (
    ("Z890", 70), ("X870", 70),
    ("Z790", 65), ("X670", 65),
    ("B860", 55), ("B850", 55),
    ("B760", 50), ("B650", 50),
    ("H810", 10), ("H610", 10), ("A820", 10), ("A620", 10),
)


def load_components():
    """Load components.yaml."""
    with (DATA / "components.yaml").open("r", encoding="utf-8") as f:
        lib = yaml.safe_load(f)
    for section, items in list(lib.items()):
        if isinstance(items, list):
            lib[section] = [enrich_item(section, item) for item in items]
    return lib


def load_cases():
    """Load cases.yaml."""
    with (DATA / "cases.yaml").open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_color(value):
    """Normalize common Chinese/English color names."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    for normalized, aliases in COLOR_ALIASES.items():
        if text in aliases:
            return normalized
    return text


def compact_text(value):
    """Normalize model/spec text for simple scope checks."""
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def parse_rated_wattage(item):
    """Prefer rated wattage in the model text over noisy imported fields."""
    text = str(item.get("model", ""))
    match = re.search(r"额定\s*(\d{3,4})\s*W", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{3,4})\s*W", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return int(item.get("wattage_w") or 0)


def color_matches(item, requested):
    """Return whether an item matches the requested color."""
    requested = normalize_color(requested)
    raw_colors = item.get("colors")
    if raw_colors is None:
        raw_colors = item.get("color", "")
    if not isinstance(raw_colors, list):
        raw_colors = [raw_colors]
    normalized = {normalize_color(c) for c in raw_colors if c}
    model_text = str(item.get("model", "")).lower()
    if normalized:
        if (requested == "white" and requested in normalized
                and ("白牌" in model_text or "白金牌" in model_text)
                and not actual_white_in_model(model_text)):
            return False
        return requested in normalized
    if requested == "white":
        model_text = model_text.replace("白牌", "")
    aliases = COLOR_ALIASES.get(requested, {requested})
    return any(alias.lower() in model_text for alias in aliases)


def actual_white_in_model(model_text):
    """Treat PSU efficiency words like 白牌/白金牌 as not being chassis color."""
    cleaned = str(model_text or "").lower().replace("白金牌", "").replace("白牌", "")
    return "white" in cleaned or "白" in cleaned or "雪" in cleaned


def rgb_matches(item, requested):
    """Return whether an item matches the requested RGB preference."""
    if requested is None:
        return True
    model_text = str(item.get("model", "")).upper()
    explicit = item.get("rgb")
    has_no_rgb_text = any(term.upper() in model_text for term in NO_RGB_TERMS)
    has_rgb_text = any(term.upper() in model_text for term in RGB_TERMS)
    if requested is True:
        return bool(explicit) or (has_rgb_text and not has_no_rgb_text)
    if explicit or (has_rgb_text and not has_no_rgb_text):
        return False
    return True


def in_current_scope(section, item):
    """Filter out legacy/irrelevant parts unless caller explicitly opts in."""
    model = compact_text(" ".join(str(item.get(k, "")) for k in ("brand", "model", "chip", "gpu_vendor")))
    socket = compact_text(item.get("socket"))

    if section == "cpus":
        if "CELERON" in model or "PENTIUM" in model or "XEON" in model or "至强" in str(item.get("model", "")):
            return False
        if "RYZEN" in model:
            return socket in {"AM5", "SOCKETAM5"}
        if "COREULTRA" in model or "ULTRA" in model:
            return socket in {"LGA1851", "1851"} or any(term in model for term in ("245", "250", "265", "270", "285"))
        return any(f"COREI{tier}1{gen}" in model or f"I{tier}1{gen}" in model
                   for tier in "3579" for gen in "234")

    if section == "motherboards":
        memory = " ".join(str(v) for v in item.get("memory_generations", []))
        return socket in {"LGA1700", "1700", "LGA1851", "1851", "AM5", "SOCKETAM5"} and "DDR3" not in memory.upper()

    if section == "memory":
        return str(item.get("generation", "")).upper() in {"DDR4", "DDR5"} and int(item.get("capacity_gb") or 0) >= 16

    if section == "storage":
        form = str(item.get("form_factor", "")).upper()
        interface = str(item.get("interface", "")).upper()
        generation = item.get("pcie_generation") or 0
        return (
            "M.2" in form
            and ("PCIE" in interface or "NVME" in interface or int(generation or 0) >= 4)
            and int(generation or 0) >= 4
            and float(item.get("capacity_tb") or 0) >= 1
        )

    if section == "gpus":
        return any(term in model for term in (
            "RTX50", "RTX5050", "RTX5060", "RTX5070", "RTX5080", "RTX5090",
            "RTX3060TI", "RX9060", "RX9070", "ARCB570", "ARCB580",
        ))

    if section == "coolers":
        height = item.get("height_mm") or 0
        radiator = item.get("radiator_mm") or 0
        price = item.get("price_cny") or 0
        return (bool(radiator) or float(height or 0) >= 120) and int(price or 0) >= 50

    if section == "psus":
        return parse_rated_wattage(item) >= 450

    return True


def _matches_socket(item, requested):
    item_socket = compact_text(item.get("socket"))
    wanted = compact_text(requested)
    return not wanted or wanted in item_socket or item_socket in wanted


def _matches_memory_gen(section, item, requested):
    wanted = str(requested or "").upper()
    if not wanted:
        return True
    if section == "motherboards":
        return wanted in [str(g).upper() for g in item.get("memory_generations", [])]
    if section == "memory":
        return wanted == str(item.get("generation", "")).upper()
    return True


def _normalize_form_factor(ff):
    text = compact_text(ff)
    mapping = {"MICROATX": "MATX", "M-ATX": "MATX", "MINIITX": "ITX"}
    return mapping.get(text, text)


def _matches_form_factor(section, item, requested):
    wanted = _normalize_form_factor(requested)
    if not wanted:
        return True
    if section == "motherboards":
        return _normalize_form_factor(item.get("form_factor")) == wanted
    if section == "cases":
        supported = [_normalize_form_factor(v) for v in item.get("motherboard_support", [])]
        return wanted in supported
    return True


def _matches_max_length(section, item, max_length):
    if not max_length:
        return True
    if section == "gpus":
        length = item.get("length_mm") or 0
        return bool(length) and length <= max_length
    if section == "cases":
        limit = item.get("gpu_length_mm") or 0
        return bool(limit) and limit >= max_length
    return True


def query(category=None, budget=None, platform=None, color=None,
          rgb=None, limit=20, has_price_only=True, showcase=None,
          include_legacy=False, sort="asc", socket=None, chipset=None,
          memory_gen=None, form_factor=None, max_length=None):
    """查询配件。返回匹配的配件列表。"""
    results = []

    if category == "case":
        # Query cases.yaml
        cases_data = load_cases()
        for item in cases_data.get("cases", []):
            if has_price_only and item.get("price_status") == "needs_market_quote":
                continue
            if not include_legacy and not item.get("motherboard_support"):
                continue
            if budget and item.get("price_cny") and item["price_cny"] > budget:
                continue
            if not _matches_form_factor("cases", item, form_factor):
                continue
            if not _matches_max_length("cases", item, max_length):
                continue
            if color and not color_matches(item, color):
                continue
            if showcase is True:
                case_type = str(item.get("is_showcase", False))
                if case_type != "True" and not item.get("is_showcase"):
                    continue
            results.append(_summarize_case(item))
        results.sort(key=lambda x: (x.get("price_cny") is None, x.get("price_cny") or 0, x.get("id", "")))
        return results[:limit]

    # Query components.yaml
    lib = load_components()
    categories_to_search = [CATEGORIES[category]] if category and category in CATEGORIES \
        else [v for k, v in CATEGORIES.items() if k != "case"]

    for sec in categories_to_search:
        for item in lib.get(sec, []):
            if has_price_only and item.get("price_status") == "needs_market_quote":
                continue
            if not include_legacy and not in_current_scope(sec, item):
                continue
            if budget and item.get("price_cny") and item["price_cny"] > budget:
                continue
            if platform:
                item_platform = item.get("platform", "").lower()
                if item_platform and platform.lower() not in item_platform:
                    continue
            if socket and sec in ("cpus", "motherboards") and not _matches_socket(item, socket):
                continue
            if chipset and sec == "motherboards" and compact_text(chipset) not in compact_text(item.get("chipset")):
                continue
            if memory_gen and not _matches_memory_gen(sec, item, memory_gen):
                continue
            if form_factor and not _matches_form_factor(sec, item, form_factor):
                continue
            if not _matches_max_length(sec, item, max_length):
                continue
            if color and not color_matches(item, color):
                continue
            if not rgb_matches(item, rgb):
                continue

            results.append(item)

    if sort == "tier":
        results.sort(key=lambda x: _tier_sort_key(category, x))
    elif sort in ("desc", "price-desc"):
        results.sort(key=lambda x: x.get("price_cny") or 0, reverse=True)
    else:
        results.sort(key=lambda x: x.get("price_cny") or 0)
    return results[:limit]


def _gpu_tier(item):
    """Return GPU chip tier rank (higher = better). 0 for non-GPU or unknown."""
    chip = compact_text(" ".join(str(item.get(k, "")) for k in ("chip", "model", "id")))
    for key, tier in GPU_TIERS:
        if key in chip:
            return tier
    return 0


def _motherboard_tier(item):
    """Return motherboard chipset tier rank (higher = better)."""
    text = compact_text(" ".join(str(item.get(k, "")) for k in ("chipset", "model", "id")))
    for key, tier in MOTHERBOARD_TIERS:
        if key in text:
            return tier
    return 0


def _tier_sort_key(category, item):
    """Category-aware tier sort used by the progressive query helper."""
    price = item.get("price_cny") or 0
    if category == "gpu":
        return (-_gpu_tier(item), price)
    if category == "mb":
        return (-_motherboard_tier(item), price)
    return (0, price)


def query_all(budget=None, platform=None, color=None, rgb=None, limit=5,
              has_price_only=True, include_legacy=False, sort="asc", socket=None,
              chipset=None, memory_gen=None, form_factor=None, max_length=None):
    """Return candidates grouped by category for smoke/progressive disclosure."""
    grouped = {}
    for category in CATEGORIES:
        grouped[category] = query(
            category=category,
            budget=budget,
            platform=platform,
            color=color,
            rgb=rgb,
            limit=limit,
            has_price_only=has_price_only,
            include_legacy=include_legacy,
            sort=sort,
            socket=socket,
            chipset=chipset,
            memory_gen=memory_gen,
            form_factor=form_factor,
            max_length=max_length,
        )
    return grouped


def _summarize_case(case):
    """Extract summary fields from a case record."""
    return {
        "id": case.get("id", ""),
        "brand": case.get("brand", ""),
        "model": case.get("model", ""),
        "price_cny": case.get("price_cny"),
        "price_status": case.get("price_status"),
        "price_date": case.get("price_date"),
        "colors": case.get("colors", case.get("color", "")),
        "motherboard_support": case.get("motherboard_support", []),
        "gpu_length_mm": case.get("gpu_length_mm", 0),
        "cpu_cooler_height_mm": case.get("cpu_cooler_height_mm", 0),
        "radiator_support": case.get("radiator_support", []),
        "psu_support": case.get("psu_support", ["ATX"]),
        "is_showcase": case.get("is_showcase", False),
    }


def summarize(item, category=None):
    """Extract only summary fields for progressive disclosure."""
    fields = SUMMARY_FIELDS_BY_CATEGORY.get(category, SUMMARY_BASE_FIELDS)
    return {k: item.get(k) for k in fields if item.get(k) is not None}


def display_extra(category, item):
    """Keep plain-text summaries compact while exposing the key routing field."""
    if category == "mb" and item.get("chipset"):
        return f"chipset={item.get('chipset')}"
    if category == "gpu" and item.get("chip"):
        return f"chip={item.get('chip')}"
    if category == "psu" and item.get("wattage_w"):
        connector = " native16pin" if item.get("native_16pin_gpu_power") else ""
        return f"{item.get('wattage_w')}W{connector}"
    if category == "memory" and item.get("frequency_mt"):
        timing = f" {item.get('timing')}" if item.get("timing") else ""
        return f"{item.get('generation','')} {item.get('frequency_mt')}MT/s{timing}"
    if category == "storage" and item.get("capacity_tb"):
        return f"{item.get('capacity_tb')}TB {item.get('interface','')}"
    if category == "cooler":
        if item.get("type") == "liquid" and item.get("radiator_mm"):
            return f"liquid {item.get('radiator_mm')}mm"
        if item.get("height_mm"):
            return f"{item.get('type','air')} {item.get('height_mm')}mm"
    return ""


def main():
    parser = argparse.ArgumentParser(description="配件查询工具 (渐进式披露)")
    parser.add_argument("--category", choices=list(CATEGORIES.keys()) + ["all"],
                        default="all", help="配件品类")
    parser.add_argument("--budget", type=int, help="单品价格上限 (元)，不是整机预算")
    parser.add_argument("--platform", help="平台过滤 (intel/amd)")
    parser.add_argument("--socket", help="CPU/主板 socket 过滤 (LGA1700/AM5/LGA1851)")
    parser.add_argument("--chipset", help="主板芯片组过滤 (B760/B850/X870/Z890 等)")
    parser.add_argument("--memory-gen", help="内存代际过滤 (DDR4/DDR5)，作用于主板和内存")
    parser.add_argument("--form-factor", help="主板/机箱版型过滤 (ATX/M-ATX/ITX)")
    parser.add_argument("--max-length", type=int,
                        help="显卡长度上限；查询机箱时表示需要容纳的显卡长度 (mm)")
    parser.add_argument("--color", help="颜色过滤 (black/white)")
    parser.add_argument("--rgb", choices=["yes", "no"], help="RGB 过滤")
    parser.add_argument("--showcase", action="store_true", help="只返回海景房机箱")
    parser.add_argument("--sort", choices=["asc", "desc", "tier"], default="asc",
                        help="排序: asc=价格升序(默认), desc=价格降序, tier=显卡芯片/主板芯片组等级优先,同等级按价格升序")
    parser.add_argument("--limit", type=int, default=20, help="最大返回数")
    parser.add_argument("--detail", action="store_true", help="返回完整属性 (默认只返回摘要)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--include-legacy", action="store_true", help="包含旧平台/非当前推荐范围条目")
    args = parser.parse_args()

    if args.category == "all":
        grouped = query_all(
            budget=args.budget,
            platform=args.platform,
            color=args.color,
            rgb=(True if args.rgb == "yes" else False) if args.rgb else None,
            limit=args.limit,
            include_legacy=args.include_legacy,
            sort=args.sort,
            socket=args.socket,
            chipset=args.chipset,
            memory_gen=args.memory_gen,
            form_factor=args.form_factor,
            max_length=args.max_length,
        )
        if not args.detail:
            output = {
                category: (items if category == "case" else [summarize(r, category) for r in items])
                for category, items in grouped.items()
            }
        else:
            output = grouped

        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            total = sum(len(items) for items in output.values())
            print(f"查询结果: {total} 条，按品类分组" + (" (摘要模式, 用 --detail 看完整属性)" if not args.detail else ""))
            for category, items in output.items():
                print(f"[{DISPLAY_NAMES.get(category, category)}] {len(items)} 条")
                for r in items:
                    price = f"¥{r.get('price_cny','')}" if r.get("price_cny") else "待补价"
                    color = r.get("colors", r.get("color", ""))
                    showcase_tag = " [海景房]" if r.get("is_showcase") else ""
                    extra = display_extra(category, r)
                    print(f"  {r.get('id',''):45s} {r.get('brand',''):10s} {r.get('model',''):35s} {price:>8s} {color} {extra} {showcase_tag}")
        return

    results = query(
        category=args.category,
        budget=args.budget,
        platform=args.platform,
        color=args.color,
        rgb=(True if args.rgb == "yes" else False) if args.rgb else None,
        limit=args.limit,
        showcase=args.showcase if args.category == "case" else None,
        include_legacy=args.include_legacy,
        sort=args.sort,
        socket=args.socket,
        chipset=args.chipset,
        memory_gen=args.memory_gen,
        form_factor=args.form_factor,
        max_length=args.max_length,
    )

    # Progressive disclosure: summary by default, detail only with --detail
    if not args.detail:
        if args.category == "case":
            output = results  # cases already summarized
        else:
            output = [summarize(r, args.category) for r in results]
    else:
        output = results

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"查询结果: {len(output)} 条" + (" (摘要模式, 用 --detail 看完整属性)" if not args.detail else ""))
        for r in output:
            if args.category == "case" or not args.detail:
                price = f"¥{r.get('price_cny','')}" if r.get("price_cny") else ""
                color = r.get("colors", r.get("color", ""))
                showcase_tag = " [海景房]" if r.get("is_showcase") else ""
                extra = display_extra(args.category, r)
                print(f"  {r.get('id',''):45s} {r.get('brand',''):10s} {r.get('model',''):35s} {price:>8s} {color} {extra} {showcase_tag}")
            else:
                price = f"¥{r['price_cny']}" if r.get("price_cny") else "待补价"
                print(f"  {r['id']:45s} {r.get('brand',''):12s} {r.get('model',''):40s} {price:>8s}")


if __name__ == "__main__":
    main()
