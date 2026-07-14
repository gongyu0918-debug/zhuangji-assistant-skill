#!/usr/bin/env python3
"""主库结构校验 — 验证 components.yaml 和 cases.yaml 的基本完整性。

用法:
  python validate_library.py
"""

import re
import sys
from datetime import date
from pathlib import Path

import yaml

from component_inference import (
    enrich_item,
    infer_cooler_type,
    infer_capacity_gb,
    infer_gpu_vram,
    infer_memory_capacity_gb,
    infer_memory_module_count,
)

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
SOURCE_BACKED_PRICE_STATUSES = {"scraped", "verified_manual", "channel_quote"}
SOURCE_ID_PATTERN = re.compile(
    r"(^|-)mhc(-|$)|-(?:cpu|主板|显卡|内存|硬盘|电源|散热|机箱)-\d+-\d+-",
    re.IGNORECASE,
)
VALID_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9\u4e00-\u9fff]+)+$")
FAN_ACCESSORY_RE = re.compile(r"(?:控制器|集线器|遥控器|HUB)\s*$", re.IGNORECASE)
BLACK_VARIANT_RE = re.compile(r"黑(?:色|款|版|\s|$)", re.IGNORECASE)
WHITE_VARIANT_RE = re.compile(r"白(?:色|款|版|\s|$)", re.IGNORECASE)

COVERAGE_FIELDS = {
    "gpus": ["length_mm", "requires_16pin_psu"],
    "motherboards": ["m2_slots", "sata_ports", "memory_freq_max"],
    "memory": ["timing"],
    "storage": ["pcie_generation", "dram_cache", "dram_cache_mb"],
    "coolers": ["type", "radiator_mm", "rgb"],
    "psus": ["wattage_w", "form_factor", "length_mm", "modular", "native_16pin_gpu_power"],
    "fans": [
        "size_mm", "color", "rgb", "blade_direction", "is_linkable",
        "has_screen", "fan_type", "default_recommend", "pack_count",
    ],
    "cases": [
        "gpu_length_mm", "cpu_cooler_height_mm", "radiator_support", "fan_mounts",
        "psu_length_mm", "psu_length_recommended_mm",
    ],
    "displays": ["resolution", "size_inch", "refresh_rate_hz"],
}

CPU_AIR_COOLER_RE = re.compile(
    r"(热管|单塔|双塔|下压|CPU\s*散热|CPU风冷|内存散热器|阿萨辛|大霜塔|冰立方|玄冰)",
    re.IGNORECASE,
)
VALID_FAN_TYPES = {"case_fan", "radiator_fan_pack", "aio_frame", "accessory"}
VALID_BLADE_DIRECTIONS = {"normal", "reverse"}
VALID_GPU_MEMORY_TYPES = {
    "GDDR5", "GDDR5X", "GDDR6", "GDDR6X", "GDDR7", "GDDR7 ECC",
    "HBM2", "HBM2E", "HBM3", "HBM3E",
}


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


def _explicit_display_size_inch(item):
    """Read an explicit Chinese inch token without guessing from model codes."""
    match = re.search(r"(?<!\d)(\d{2}(?:\.\d+)?)\s*(?:英寸|寸)", str(item.get("model", "")))
    return float(match.group(1)) if match else None


def _explicit_display_refresh_hz(item):
    """Read the native-resolution refresh token without merging dual-mode rates."""
    values = [
        int(value)
        for value in re.findall(r"(?<!\d)(\d{2,4})\s*HZ", str(item.get("model", "")), re.IGNORECASE)
        if 20 <= int(value) <= 1000
    ]
    model = str(item.get("model", ""))
    if ("双模" in model or len(set(values)) > 1) and values:
        return values[0]
    return max(values) if values else None


MOTHERBOARD_CHIPSET_TOKENS = (
    "X870E", "X670E", "B650E", "B850", "X870", "X670", "B650", "A620", "A820",
    "Z890", "Z790", "Z690", "B860", "B760", "B660", "H810", "H610",
)


def _explicit_motherboard_chipset(item):
    """Infer the longest chipset token explicitly present in model or id."""
    text = str(item.get("model") or item.get("id") or "").upper()
    return next((token for token in MOTHERBOARD_CHIPSET_TOKENS if token in text), None)


def _canonical_motherboard_chipset(value):
    chipset = str(value or "").upper().replace(" ", "")
    if chipset.endswith("M") and chipset[:-1] in MOTHERBOARD_CHIPSET_TOKENS:
        return chipset[:-1]
    return chipset


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


def _check_cpu_vendor_consistency(item):
    item_id = str(item.get("id", ""))
    brand = str(item.get("brand", "")).upper()
    model = str(item.get("model", "")).upper()
    platform = str(item.get("platform", "")).upper()
    socket = str(item.get("socket", "")).upper()
    text = f"{brand} {model} {platform} {socket} {item_id.upper()}"
    if "RYZEN" in text or "AMD" in model or socket.startswith("AM"):
        valid_id = item_id.startswith("cpu-amd-") or item_id.startswith("demo-cpu-amd-")
        if brand != "AMD" or platform != "AMD" or not socket.startswith("AM") or not valid_id:
            return "AMD/Ryzen CPU must use AMD brand/platform/socket/id prefix"
    intel_tokens = ("INTEL", "CORE I", "CORE ULTRA", "PENTIUM", "CELERON")
    if any(token in text for token in intel_tokens) or socket.startswith("LGA"):
        valid_id = item_id.startswith("cpu-intel-") or item_id.startswith("demo-cpu-intel-")
        if brand != "INTEL" or platform != "INTEL" or not socket.startswith("LGA") or not valid_id:
            return "Intel CPU must use Intel brand/platform/socket/id prefix"
    return None


def _valid_iso_date(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_price(section, item, errors, warnings):
    item_id = item.get("id", "<no-id>")
    price_status = item.get("price_status", "")
    price_cny = item.get("price_cny")
    price_date = item.get("price_date")
    if price_status and price_status not in VALID_PRICE_STATUSES:
        errors.append(f"{section}.{item_id}: invalid price_status '{price_status}'")
    if price_cny is not None and (
        isinstance(price_cny, bool)
        or not isinstance(price_cny, (int, float))
        or price_cny <= 0
    ):
        errors.append(f"{section}.{item_id}: price_cny must be a positive number")
    if price_status == "needs_market_quote" and price_cny is not None:
        errors.append(f"{section}.{item_id}: needs_market_quote must not have price_cny")
    if price_status in SOURCE_BACKED_PRICE_STATUSES and price_cny is None:
        errors.append(f"{section}.{item_id}: source-backed price_status requires price_cny")
    if price_cny is not None and not _valid_iso_date(price_date):
        errors.append(f"{section}.{item_id}: invalid or missing price_date={price_date}")
    elif price_date and not _valid_iso_date(price_date):
        warnings.append(f"{section}.{item_id}: invalid price_date={price_date}")


def _register_id(section, item_id, seen_ids, errors):
    if not item_id or item_id == "<no-id>":
        errors.append(f"{section}: missing id")
        return
    if not VALID_ID_PATTERN.fullmatch(str(item_id)):
        errors.append(f"{section}.{item_id}: invalid id shape; use a stable category-model id")
    previous = seen_ids.get(item_id)
    if previous:
        errors.append(f"duplicate id {item_id}: {previous} and {section}")
    else:
        seen_ids[item_id] = section


def main():
    errors = []
    warnings = []
    notes = []
    counts = {}
    coverage_rows = []
    seen_ids = {}

    # Load components.yaml
    comp_path = DATA / "components.yaml"
    if not comp_path.exists():
        print(f"FAIL: {comp_path} not found")
        return 1

    with comp_path.open("r", encoding="utf-8") as f:
        lib = yaml.safe_load(f) or {}

    metadata_date = (lib.get("metadata") or {}).get("price_date")
    if metadata_date and not _valid_iso_date(str(metadata_date)):
        errors.append(f"components.metadata.price_date invalid: {metadata_date}")

    for section in REQUIRED_SECTIONS:
        raw_items = lib.get(section)
        if not isinstance(raw_items, list) or not raw_items:
            errors.append(f"{section}: missing or empty section")
        items = raw_items if isinstance(raw_items, list) else []
        counts[section] = len(items)
        required = REQUIRED_FIELDS.get(section, set())

        for item in items:
            item_id = item.get("id", "<no-id>")
            _register_id(section, item_id, seen_ids, errors)
            if _id_not_normalized(item_id):
                errors.append(f"{section}.{item_id}: imported id was not normalized")
            missing = required - set(item.keys())
            if missing:
                errors.append(f"{section}.{item_id}: missing fields {missing}")

            _validate_price(section, item, errors, warnings)
            if section == "cpus":
                consistency_error = _check_cpu_vendor_consistency(item)
                if consistency_error:
                    errors.append(f"{section}.{item_id}: {consistency_error}")
            if section == "motherboards":
                explicit_chipset = _explicit_motherboard_chipset(item)
                chipset = _canonical_motherboard_chipset(item.get("chipset"))
                if explicit_chipset and chipset and explicit_chipset != chipset:
                    errors.append(
                        f"{section}.{item_id}: chipset={chipset} conflicts with model token {explicit_chipset}"
                    )
                memory_freq_max = item.get("memory_freq_max")
                if memory_freq_max not in (None, ""):
                    if isinstance(memory_freq_max, bool) or not isinstance(memory_freq_max, int) or not 1600 <= memory_freq_max <= 12000:
                        errors.append(f"{section}.{item_id}: invalid memory_freq_max={memory_freq_max}")
            if section == "gpus" and item.get("length_mm"):
                try:
                    gpu_length = int(item.get("length_mm"))
                    if gpu_length > 450 or gpu_length < 120:
                        errors.append(f"{section}.{item_id}: impossible length_mm={item.get('length_mm')}")
                except (TypeError, ValueError):
                    errors.append(f"{section}.{item_id}: invalid length_mm={item.get('length_mm')}")
            if section == "gpus":
                memory_type = str(item.get("memory_type") or "").strip().upper()
                if memory_type and memory_type not in VALID_GPU_MEMORY_TYPES:
                    errors.append(f"{section}.{item_id}: invalid memory_type={item.get('memory_type')}")
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
                connectors = item.get("power_connectors") or []
                if "16pin" in connectors and "6pin" in connectors:
                    errors.append(
                        f"{section}.{item_id}: impossible mixed 16pin and 6pin connector data"
                    )
            if section == "memory":
                inferred_capacity = infer_memory_capacity_gb(item)
                inferred_modules = infer_memory_module_count(item)
                if inferred_capacity and item.get("capacity_gb") != inferred_capacity:
                    errors.append(
                        f"{section}.{item_id}: capacity_gb={item.get('capacity_gb')} "
                        f"conflicts with model-inferred {inferred_capacity}GB"
                    )
                if inferred_modules and item.get("module_count") not in (None, inferred_modules):
                    errors.append(
                        f"{section}.{item_id}: module_count={item.get('module_count')} "
                        f"conflicts with model-inferred {inferred_modules}"
                    )
                timing = item.get("timing")
                if timing and not re.fullmatch(r"C(?:1[0-9]|[2-7][0-9]|80)", str(timing).upper()):
                    errors.append(f"{section}.{item_id}: invalid timing={timing}")
            if section == "storage":
                inferred_capacity = infer_capacity_gb(item)
                raw_capacity_tb = item.get("capacity_tb")
                if inferred_capacity and raw_capacity_tb:
                    try:
                        raw_capacity_gb = float(raw_capacity_tb) * 1024
                    except (TypeError, ValueError):
                        errors.append(f"{section}.{item_id}: invalid capacity_tb={raw_capacity_tb}")
                        raw_capacity_gb = float(inferred_capacity)
                    tolerance_gb = max(32.0, float(inferred_capacity) * 0.10)
                    if abs(raw_capacity_gb - float(inferred_capacity)) > tolerance_gb:
                        errors.append(
                            f"{section}.{item_id}: capacity_tb={raw_capacity_tb} "
                            f"conflicts with model-inferred {inferred_capacity}GB"
                        )
                if "dram_cache" in item and not isinstance(item.get("dram_cache"), bool):
                    errors.append(f"{section}.{item_id}: invalid dram_cache={item.get('dram_cache')}")
                if item.get("dram_cache_mb") not in (None, ""):
                    dram_cache_mb = item.get("dram_cache_mb")
                    if isinstance(dram_cache_mb, bool) or not isinstance(dram_cache_mb, int) or not 1 <= dram_cache_mb <= 32768:
                        errors.append(f"{section}.{item_id}: invalid dram_cache_mb={dram_cache_mb}")
                    if item.get("dram_cache") is not True:
                        errors.append(f"{section}.{item_id}: dram_cache_mb requires dram_cache=true")
            if section == "coolers":
                inferred_type = infer_cooler_type(item)
                raw_type = str(item.get("type") or "").lower()
                if inferred_type == "liquid" and raw_type not in {"liquid", "water", "水冷"}:
                    errors.append(f"{section}.{item_id}: type={item.get('type')} conflicts with model-inferred liquid cooler")
            if section == "psus" and item.get("length_mm") not in (None, ""):
                length_mm = item.get("length_mm")
                if isinstance(length_mm, bool) or not isinstance(length_mm, int) or not 80 <= length_mm <= 300:
                    errors.append(f"{section}.{item_id}: invalid length_mm={length_mm}")
            if section == "psus" and item.get("form_factor") not in (None, ""):
                if item.get("form_factor") not in {"ATX", "SFX", "SFX-L", "FLEX", "TFX"}:
                    errors.append(f"{section}.{item_id}: invalid form_factor={item.get('form_factor')}")
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
                accessory = bool(FAN_ACCESSORY_RE.search(str(item.get("model", "")).strip()))
                if accessory and item.get("fan_type") != "accessory":
                    errors.append(f"{section}.{item_id}: accessory-only variant classified as fan")
                if item.get("fan_type") == "accessory" and item.get("default_recommend") is not False:
                    errors.append(f"{section}.{item_id}: accessory must not be default_recommend")
                model = str(item.get("model", ""))
                explicit_black = bool(BLACK_VARIANT_RE.search(model))
                explicit_white = bool(WHITE_VARIANT_RE.search(model))
                mixed_color_label = "黑白" in model or "白黑" in model
                if not mixed_color_label and explicit_black != explicit_white:
                    expected_color = "black" if explicit_black else "white"
                    if str(item.get("color") or "").lower() != expected_color:
                        errors.append(
                            f"{section}.{item_id}: color={item.get('color')} "
                            f"conflicts with explicit {expected_color} model token"
                        )
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
    if not isinstance(case_items, list) or not case_items:
        errors.append("cases: missing or empty section")
        case_items = []
    counts["cases"] = len(case_items)

    case_metadata_date = (cases.get("metadata") or {}).get("cutoff_date")
    if case_metadata_date and not _valid_iso_date(str(case_metadata_date)):
        errors.append(f"cases.metadata.cutoff_date invalid: {case_metadata_date}")

    for case in case_items:
        case_id = case.get("id", "<no-id>")
        _register_id("cases", case_id, seen_ids, errors)
        if _id_not_normalized(case_id):
            errors.append(f"cases.{case_id}: imported id was not normalized")
        _validate_price("cases", case, errors, warnings)
        if not case.get("brand"):
            errors.append(f"cases.{case_id}: missing brand")
        if not case.get("motherboard_support"):
            warnings.append(f"cases.{case_id}: no motherboard_support")
        if not case.get("gpu_length_mm"):
            warnings.append(f"cases.{case_id}: no gpu_length_mm")
        if not _valid_fan_mounts(case.get("fan_mounts")):
            errors.append(f"cases.{case_id}: invalid fan_mounts={case.get('fan_mounts')}")
        if case.get("psu_length_mm") not in (None, ""):
            psu_length_mm = case.get("psu_length_mm")
            if isinstance(psu_length_mm, bool) or not isinstance(psu_length_mm, int) or not 80 <= psu_length_mm <= 500:
                errors.append(f"cases.{case_id}: invalid psu_length_mm={psu_length_mm}")
        if case.get("psu_length_recommended_mm") not in (None, ""):
            recommended_mm = case.get("psu_length_recommended_mm")
            if isinstance(recommended_mm, bool) or not isinstance(recommended_mm, int) or not 80 <= recommended_mm <= 500:
                errors.append(f"cases.{case_id}: invalid psu_length_recommended_mm={recommended_mm}")
            elif case.get("psu_length_mm") and recommended_mm > case.get("psu_length_mm"):
                errors.append(
                    f"cases.{case_id}: psu_length_recommended_mm={recommended_mm} "
                    f"exceeds psu_length_mm={case.get('psu_length_mm')}"
                )
        if "psu_length_condition" in case and not str(case.get("psu_length_condition") or "").strip():
            errors.append(f"cases.{case_id}: empty psu_length_condition")
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
        display_metadata_date = (displays.get("metadata") or {}).get("price_date")
        if display_metadata_date and not _valid_iso_date(str(display_metadata_date)):
            errors.append(f"displays.metadata.price_date invalid: {display_metadata_date}")
        for item in display_items:
            item_id = item.get("id", "<no-id>")
            _register_id("displays", item_id, seen_ids, errors)
            missing = {"id", "model", "resolution"} - set(item.keys())
            if missing:
                errors.append(f"displays.{item_id}: missing fields {missing}")
            if not item.get("brand"):
                missing_display_brand.append(item_id)
            _validate_price("displays", item, errors, warnings)
            price_status = item.get("price_status", "")
            if price_status != "needs_market_quote" and item.get("price_cny") is None:
                missing_display_prices.append(item_id)
            if not item.get("refresh_rate_hz"):
                missing_display_refresh.append(item_id)
            refresh_hz = _parse_int(item.get("refresh_rate_hz"))
            if refresh_hz and (refresh_hz < 30 or refresh_hz > 1000):
                errors.append(f"displays.{item_id}: implausible refresh_rate_hz={refresh_hz}")
            explicit_refresh = _explicit_display_refresh_hz(item)
            if explicit_refresh and refresh_hz and explicit_refresh != refresh_hz:
                errors.append(
                    f"displays.{item_id}: refresh_rate_hz={refresh_hz} "
                    f"conflicts with explicit model token {explicit_refresh}"
                )
            explicit_size = _explicit_display_size_inch(item)
            if explicit_size and item.get("size_inch"):
                if abs(float(item.get("size_inch")) - explicit_size) > 0.6:
                    errors.append(
                        f"displays.{item_id}: size_inch={item.get('size_inch')} "
                        f"conflicts with explicit model token {explicit_size}"
                    )
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
            if row.get("source_type") == "public_fps_prediction" and row.get("confidence") == "high":
                errors.append(f"{prefix}: public prediction confidence must not be high")
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
