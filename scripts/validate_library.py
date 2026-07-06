#!/usr/bin/env python3
"""主库结构校验 — 验证 components.yaml 和 cases.yaml 的基本完整性。

用法:
  python validate_library.py
"""

import re
import sys
from pathlib import Path

import yaml

from component_inference import enrich_item, infer_cooler_type, infer_gpu_vram

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

REQUIRED_SECTIONS = ["cpus", "motherboards", "memory", "storage", "gpus", "coolers", "psus", "fans"]

REQUIRED_FIELDS = {
    "cpus": {"id", "brand", "model", "platform", "socket"},
    "motherboards": {"id", "brand", "model", "socket", "memory_generations", "form_factor"},
    "memory": {"id", "brand", "model", "generation", "capacity_gb"},
    "storage": {"id", "brand", "model", "capacity_tb", "form_factor"},
    "gpus": {"id", "brand", "model"},
    "coolers": {"id", "brand", "model", "type"},
    "psus": {"id", "brand", "model", "wattage_w"},
    "fans": {"id", "brand", "model", "fan_type", "default_recommend"},
}

# Fields that trigger warning (not error) when missing.
# Motherboard M.2/SATA omissions are tracked separately as non-blocking notes:
# current mainstream boards usually have at least one M.2 slot, and SATA is
# only critical for multi-drive / editing / workstation workflows.
WARN_FIELDS = {
    "cpus": {"power_w"},
    "gpus": {"power_w", "length_mm"},
    "motherboards": {"color", "memory_freq_max"},
    "psus": {"length_mm"},
}

NOTE_FIELDS = {
    "motherboards": {"m2_slots", "sata_ports"},
}

VALID_PRICE_STATUSES = {"scraped", "verified_manual", "channel_quote", "needs_market_quote"}
SOURCE_ID_PATTERN = re.compile(
    r"(^|-)mhc(-|$)|-(?:cpu|主板|显卡|内存|硬盘|电源|散热|机箱)-\d+-\d+-",
    re.IGNORECASE,
)

COVERAGE_FIELDS = {
    "gpus": ["length_mm", "requires_16pin_psu"],
    "motherboards": ["m2_slots", "sata_ports", "memory_freq_max"],
    "memory": ["timing"],
    "storage": ["pcie_generation"],
    "coolers": ["type", "radiator_mm", "rgb"],
    "psus": ["wattage_w", "form_factor", "length_mm", "modular", "native_16pin_gpu_power"],
    "fans": [
        "size_mm", "color", "rgb", "blade_direction", "is_linkable",
        "has_screen", "fan_type", "default_recommend", "pack_count",
    ],
    "cases": ["gpu_length_mm", "cpu_cooler_height_mm", "radiator_support", "fan_mounts", "psu_length_mm"],
    "displays": ["resolution", "size_inch", "refresh_rate_hz"],
}

CPU_AIR_COOLER_RE = re.compile(
    r"(热管|单塔|双塔|下压|CPU\s*散热|CPU风冷|内存散热器|阿萨辛|大霜塔|冰立方|玄冰)",
    re.IGNORECASE,
)
VALID_FAN_TYPES = {"case_fan", "radiator_fan_pack", "aio_frame"}
VALID_BLADE_DIRECTIONS = {"normal", "reverse"}


def _parse_int(value, default=0):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.-]", "", value)
        if cleaned in ("", "-", ".", "-."):
            return default
        try:
            return int(float(cleaned))
        except ValueError:
            return default
    return default


def _valid_fan_mounts(value):
    if value in (None, "", [], {}):
        return True
    text = str(value).upper().strip().replace("×", "X")
    if re.fullmatch(r"\d{1,2}", text):
        return 1 <= int(text) <= 20
    if re.fullmatch(r"\d{2,3}(?:\.\d+)?\s*(?:MM|CM)", text):
        return False
    if re.search(r"\d{1,2}\s*个(?:以上)?", text):
        return True
    if re.search(r"\d{1,2}\s*X\s*(?:120|140|200)", text):
        return True
    if re.search(r"(?:120|140|160|200)\s*MM?\s*(?:风扇|FAN)", text):
        return True
    if re.search(r"风扇|FAN|TOP|FRONT|REAR|BOTTOM|SIDE|前|顶|后|底|侧", text):
        return True
    return not bool(re.fullmatch(r"\d+(?:\.\d+)?\s*(?:MM|CM)?", text))


def _id_not_normalized(item_id):
    text = str(item_id)
    return text.startswith("cat-") or "--" in text or bool(SOURCE_ID_PATTERN.search(text))


def main():
    errors = []
    warnings = []
    notes = []
    counts = {}
    coverage_rows = []

    # Load components.yaml
    comp_path = DATA / "components.yaml"
    if not comp_path.exists():
        print(f"FAIL: {comp_path} not found")
        return 1

    with comp_path.open("r", encoding="utf-8") as f:
        lib = yaml.safe_load(f) or {}

    for section in REQUIRED_SECTIONS:
        items = lib.get(section, [])
        counts[section] = len(items)
        required = REQUIRED_FIELDS.get(section, set())

        for item in items:
            item_id = item.get("id", "<no-id>")
            if _id_not_normalized(item_id):
                errors.append(f"{section}.{item_id}: imported id was not normalized")
            missing = required - set(item.keys())
            if missing:
                errors.append(f"{section}.{item_id}: missing fields {missing}")

            price_status = item.get("price_status", "")
            if price_status and price_status not in VALID_PRICE_STATUSES:
                errors.append(f"{section}.{item_id}: invalid price_status '{price_status}'")

            price_cny = item.get("price_cny")
            if price_status == "needs_market_quote" and price_cny is not None:
                warnings.append(f"{section}.{item_id}: needs_market_quote but has price_cny={price_cny}")
            if price_status != "needs_market_quote" and price_cny is None:
                warnings.append(f"{section}.{item_id}: has price_status={price_status} but price_cny is None")
            if section == "gpus" and item.get("length_mm"):
                try:
                    gpu_length = int(item.get("length_mm"))
                    if gpu_length > 450 or gpu_length < 120:
                        errors.append(f"{section}.{item_id}: impossible length_mm={item.get('length_mm')}")
                except (TypeError, ValueError):
                    errors.append(f"{section}.{item_id}: invalid length_mm={item.get('length_mm')}")
            if section == "gpus":
                inferred_vram = infer_gpu_vram(item)
                current_vram = item.get("vram_gb")
                if inferred_vram and current_vram:
                    try:
                        if int(current_vram) != int(inferred_vram):
                            errors.append(
                                f"{section}.{item_id}: vram_gb={current_vram} conflicts with model token {inferred_vram}GB"
                            )
                    except (TypeError, ValueError):
                        errors.append(f"{section}.{item_id}: invalid vram_gb={current_vram}")
            if section == "coolers":
                inferred_type = infer_cooler_type(item)
                raw_type = str(item.get("type") or "").lower()
                if inferred_type == "liquid" and raw_type not in {"liquid", "water", "水冷"}:
                    errors.append(f"{section}.{item_id}: type={item.get('type')} conflicts with model-inferred liquid cooler")
            if section == "fans":
                if CPU_AIR_COOLER_RE.search(str(item.get("model", ""))):
                    errors.append(f"{section}.{item_id}: CPU/memory cooler classified as fan")
                if item.get("fan_type") not in VALID_FAN_TYPES:
                    errors.append(f"{section}.{item_id}: invalid fan_type={item.get('fan_type')}")
                if item.get("blade_direction") and item.get("blade_direction") not in VALID_BLADE_DIRECTIONS:
                    errors.append(f"{section}.{item_id}: invalid blade_direction={item.get('blade_direction')}")
                if item.get("has_screen") and item.get("rgb") is not True:
                    errors.append(f"{section}.{item_id}: screen fan must be rgb=true")
                if item.get("fan_type") == "aio_frame" and item.get("default_recommend") is not False:
                    errors.append(f"{section}.{item_id}: aio_frame must not be default_recommend")
                if item.get("size_mm"):
                    size_mm = _parse_int(item.get("size_mm"))
                    if size_mm < 80 or size_mm > 220:
                        errors.append(f"{section}.{item_id}: invalid size_mm={item.get('size_mm')}")

        for field in sorted(WARN_FIELDS.get(section, set())):
            missing_items = [item.get("id", "<no-id>") for item in items if not item.get(field)]
            if missing_items:
                sample = ", ".join(missing_items[:5])
                warnings.append(
                    f"{section}: {len(missing_items)}/{len(items)} missing or empty {field}"
                    + (f" (sample: {sample})" if sample else "")
                )
        for field in sorted(NOTE_FIELDS.get(section, set())):
            missing_items = [item.get("id", "<no-id>") for item in items if not item.get(field)]
            if missing_items:
                sample = ", ".join(missing_items[:5])
                notes.append(
                    f"{section}: {len(missing_items)}/{len(items)} missing or empty {field}"
                    + (f" (sample: {sample})" if sample else "")
                )
        coverage_rows.extend(_coverage_rows(section, items))

    # Load cases.yaml
    cases_path = DATA / "cases.yaml"
    if not cases_path.exists():
        print(f"FAIL: {cases_path} not found")
        return 1

    with cases_path.open("r", encoding="utf-8") as f:
        cases = yaml.safe_load(f) or {}

    case_items = cases.get("cases", [])
    counts["cases"] = len(case_items)

    for case in case_items:
        case_id = case.get("id", "<no-id>")
        if _id_not_normalized(case_id):
            errors.append(f"cases.{case_id}: imported id was not normalized")
        price_status = case.get("price_status", "")
        if price_status and price_status not in VALID_PRICE_STATUSES:
            errors.append(f"cases.{case_id}: invalid price_status '{price_status}'")
        if not case.get("brand"):
            errors.append(f"cases.{case_id}: missing brand")
        if not case.get("motherboard_support"):
            warnings.append(f"cases.{case_id}: no motherboard_support")
        if not case.get("gpu_length_mm"):
            warnings.append(f"cases.{case_id}: no gpu_length_mm")
        if not _valid_fan_mounts(case.get("fan_mounts")):
            errors.append(f"cases.{case_id}: invalid fan_mounts={case.get('fan_mounts')}")
    missing_case_prices = [case.get("id", "<no-id>") for case in case_items if case.get("price_cny") is None]
    if missing_case_prices:
        sample = ", ".join(missing_case_prices[:5])
        warnings.append(
            f"cases: {len(missing_case_prices)}/{len(case_items)} missing price_cny"
            + (f" (sample: {sample})" if sample else "")
        )
    coverage_rows.extend(_coverage_rows("cases", case_items))

    displays_path = DATA / "displays.yaml"
    if displays_path.exists():
        with displays_path.open("r", encoding="utf-8") as f:
            displays = yaml.safe_load(f) or {}
        display_items = displays.get("displays", [])
        counts["displays"] = len(display_items)
        missing_display_prices = []
        missing_display_refresh = []
        missing_display_brand = []
        for item in display_items:
            item_id = item.get("id", "<no-id>")
            missing = {"id", "model", "resolution"} - set(item.keys())
            if missing:
                errors.append(f"displays.{item_id}: missing fields {missing}")
            if not item.get("brand"):
                missing_display_brand.append(item_id)
            price_status = item.get("price_status", "")
            if price_status and price_status not in VALID_PRICE_STATUSES:
                errors.append(f"displays.{item_id}: invalid price_status '{price_status}'")
            if price_status != "needs_market_quote" and item.get("price_cny") is None:
                missing_display_prices.append(item_id)
            if not item.get("refresh_rate_hz"):
                missing_display_refresh.append(item_id)
        if missing_display_prices:
            sample = ", ".join(missing_display_prices[:5])
            warnings.append(
                f"displays: {len(missing_display_prices)}/{len(display_items)} missing price_cny"
                + (f" (sample: {sample})" if sample else "")
            )
        if missing_display_refresh:
            sample = ", ".join(missing_display_refresh[:5])
            warnings.append(
                f"displays: {len(missing_display_refresh)}/{len(display_items)} missing refresh_rate_hz"
                + (f" (sample: {sample})" if sample else "")
            )
        if missing_display_brand:
            sample = ", ".join(missing_display_brand[:5])
            warnings.append(
                f"displays: {len(missing_display_brand)}/{len(display_items)} missing brand"
                + (f" (sample: {sample})" if sample else "")
            )
        coverage_rows.extend(_coverage_rows("displays", display_items))
    else:
        notes.append("displays.yaml: optional explicit monitor database missing")

    game_fps_path = DATA / "game_fps.yaml"
    if not game_fps_path.exists():
        errors.append("game_fps.yaml: missing game FPS reference table")
    else:
        with game_fps_path.open("r", encoding="utf-8") as f:
            game_fps = yaml.safe_load(f) or {}
        game_ids = {game.get("id") for game in game_fps.get("games", []) if game.get("id")}
        if not game_ids:
            errors.append("game_fps.yaml: no games")
        required_fps_fields = {
            "game", "resolution", "preset", "cpu", "gpu", "avg_fps",
            "confidence", "source_title", "source_date", "source_type",
        }
        for index, row in enumerate(game_fps.get("benchmarks", []), start=1):
            prefix = f"game_fps.benchmarks[{index}]"
            missing = required_fps_fields - set(row)
            if missing:
                errors.append(f"{prefix}: missing fields {missing}")
            if row.get("game") not in game_ids:
                errors.append(f"{prefix}: unknown game {row.get('game')}")
            if not row.get("p1_low_fps") and not row.get("fps_range"):
                errors.append(f"{prefix}: missing either p1_low_fps or fps_range")
            for field in ("avg_fps", "p1_low_fps", "fps_range", "base_fps"):
                if field not in row:
                    continue
                value = row.get(field)
                if (
                    not isinstance(value, list)
                    or len(value) != 2
                    or not all(isinstance(item, (int, float)) for item in value)
                    or value[0] <= 0
                    or value[1] < value[0]
                ):
                    errors.append(f"{prefix}: invalid {field}={value}")
        counts["game_fps_samples"] = len(game_fps.get("benchmarks", []))

    # Report
    if errors:
        print("VALIDATION FAILED")
        for e in errors:
            print(f"  ❌ {e}")
        for w in warnings:
            print(f"  ⚠️ {w}")
        return 1

    print("component library validation OK")
    print(f"sections: {', '.join(REQUIRED_SECTIONS)} + cases")
    for sec, count in counts.items():
        print(f"  {sec}: {count} items")

    status_counts = {}
    for section in REQUIRED_SECTIONS:
        for item in lib.get(section, []):
            ps = item.get("price_status", "unknown")
            status_counts[ps] = status_counts.get(ps, 0) + 1
    print(f"price status counts: {status_counts}")

    if coverage_rows:
        print("\nfield coverage (raw/effective):")
        for row in coverage_rows:
            print(f"  {row}")

    if warnings:
        print(f"\nwarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠️ {w}")
    if notes:
        print(f"\nnon-blocking notes ({len(notes)}):")
        for n in notes:
            print(f"  ℹ️ {n}")

    return 0


def _has_value(item, field):
    value = item.get(field)
    if field in {"length_mm", "gpu_length_mm", "cpu_cooler_height_mm", "height_mm"} and value == 0:
        return False
    if field == "fan_mounts" and not _valid_fan_mounts(value):
        return False
    return value not in (None, "", [], {})


def _coverage_rows(section, items):
    rows = []
    fields = COVERAGE_FIELDS.get(section, [])
    if not fields:
        return rows
    enriched_items = [enrich_item(section, item) for item in items]
    total = len(items) or 1
    for field in fields:
        raw = sum(1 for item in items if _has_value(item, field))
        effective = sum(1 for item in enriched_items if _has_value(item, field))
        if raw != total or effective != total:
            rows.append(f"{section}.{field}: raw {raw}/{total}, effective {effective}/{total}")
    return rows


if __name__ == "__main__":
    sys.exit(main())
