#!/usr/bin/env python3
"""装机兼容性检查引擎。

用法:
  python check_compatibility.py --cpu cpu-intel-i5-14400f --mb mb-asus-b760m-k-d4 \
    --mem mem-ddr4-3200-16-kingston-beast --gpu gpu-gigabyte-rtx5070-windforce-oc \
    --psu psu-msi-a750gl-pcie5 --case case-jonsbo-d31-mesh-black --cooler cooler-tr-pa120se
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import yaml

from component_inference import enrich_item, infer_native_16pin_psu, infer_requires_16pin_gpu

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class CompatibilityChecker:
    """装机兼容性检查引擎。

    检查 12 类基础兼容性: CPU↔主板, 内存↔主板(代际/数量/容量),
    显卡↔机箱, 硬盘↔主板, 电源↔功耗, 散热↔机箱, 机箱↔主板, 机箱↔电源。
    """

    # 机箱版型向下兼容表
    FORM_FACTOR_MAP = {
        "EATX": ["EATX", "ATX", "MATX", "ITX"],
        "ATX":  ["ATX", "MATX", "ITX"],
        "MATX": ["MATX", "ITX"],
        "M-ATX": ["MATX", "ITX"],
        "Mini-ITX": ["ITX"],
        "ITX": ["ITX"],
    }

    RADIATOR_SIZE_COMPATIBILITY = {
        120: {120},
        140: {140},
        240: {120, 240},
        280: {140, 280},
        360: {120, 240, 360},
        420: {140, 280, 420},
    }

    def _parse_num(self, val, default=0):
        """从字符串/数字中提取数值。"""
        if isinstance(val, (int, float)):
            return val if not (isinstance(val, float) and math.isnan(val)) else default
        if isinstance(val, str):
            cleaned = re.sub(r"[^\d.-]", "", val)
            try:
                return float(cleaned) if "." in cleaned else int(cleaned)
            except (ValueError, TypeError):
                return default
        return default

    def _parse_rated_wattage(self, psu):
        """Prefer the rated wattage in PSU model text over noisy imported fields."""
        if not psu:
            return 0
        model = str(psu.get("model", ""))
        match = re.search(r"额定\s*(\d{3,4})\s*W", model, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"(\d{3,4})\s*W", model, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return self._parse_num(psu.get("wattage_w", 0))

    def _normalize(self, val):
        """移除非字母数字字符并转大写，用于接口/尺寸比较。"""
        if not val:
            return ""
        return re.sub(r"[^0-9a-zA-Z]", "", str(val)).upper()

    def _normalize_socket_list(self, val):
        """Normalize socket strings while preserving multi-socket separators."""
        if not val:
            return []
        parts = re.split(r"[/,|]", str(val))
        normalized = []
        for part in parts:
            socket = self._normalize(part)
            if socket.startswith("SOCKET"):
                socket = socket[len("SOCKET"):]
            if socket:
                normalized.append(socket)
        return normalized

    def _normalize_form_factor(self, ff):
        """标准化版型名称用于比较。"""
        if not ff:
            return ""
        ff = ff.upper().replace("-", "").replace("_", "").replace(" ", "")
        mapping = {"MATX": "MATX", "MINIITX": "ITX", "MICROATX": "MATX",
                   "EATX": "EATX", "ATX": "ATX"}
        return mapping.get(ff, ff)

    def _cpu_has_integrated_graphics(self, cpu):
        """Conservatively infer whether the CPU can provide display output."""
        if not cpu:
            return False
        explicit = cpu.get("integrated_graphics")
        if explicit is None:
            explicit = cpu.get("has_integrated_graphics")
        if explicit is not None:
            if isinstance(explicit, bool):
                return explicit
            text = str(explicit).strip().lower()
            if text in ("true", "yes", "y", "1", "有", "核显", "集显"):
                return True
            if text in ("false", "no", "n", "0", "无", "none", "no igpu"):
                return False

        model = str(cpu.get("model", ""))
        brand = str(cpu.get("brand", ""))
        text = f"{brand} {model}".upper()
        compact = self._normalize(text)

        if "INTEL" in text or "CORE" in text or compact.startswith(("I3", "I5", "I7", "I9", "U5", "U7", "U9")):
            # Intel desktop F/KF suffix SKUs normally disable integrated graphics.
            if re.search(r"\b(?:I[3579]|CORE\s+ULTRA\s+[579]|U[579])[-\s]?\d{3,5}[A-Z]*F\b", text):
                return False
            if re.search(r"\b\d{3,5}[A-Z]*F\b", text):
                return False
            return True

        if "AMD" in text or "RYZEN" in text:
            # Ryzen G/GT APUs and mainstream AM5 Ryzen 7000/8000/9000 non-F SKUs have display output.
            if re.search(r"\b\d{4,5}F\b", text):
                return False
            if re.search(r"\b\d{4,5}(?:G|GE|GT)\b", text):
                return True
            match = re.search(r"\b(?:RYZEN\s+\d\s*)?(\d{4,5})(?:X3D|X)?\b", text)
            if match:
                number = int(match.group(1))
                return number >= 7000
        return False

    # --- 12 类基础检查函数 ---

    def check_cpu_motherboard(self, cpu, mb):
        """检查 CPU 和主板兼容性: socket 接口匹配。"""
        if not cpu or not mb:
            return {"type": "msg", "msg": f"缺少必要组件{('主板' if cpu else 'CPU')}"}
        cpu_sockets = self._normalize_socket_list(cpu.get("socket", ""))
        mb_sockets = self._normalize_socket_list(mb.get("socket", ""))
        if not cpu_sockets or not mb_sockets:
            return {"type": "msg", "msg": "CPU或主板缺少接口信息，需下单前复核"}
        if not set(cpu_sockets).intersection(mb_sockets):
            return {"type": "error",
                    "msg": f"接口不兼容，CPU【{cpu.get('socket')}】，主板【{mb.get('socket')}】"}
        return {"type": "success", "msg": f"CPU和主板接口兼容【{mb.get('socket')}】"}

    def check_memory_motherboard(self, memory_list, mb):
        """检查内存与主板兼容性: DDR 代际 + 频率。"""
        if not mb:
            return [{"type": "msg", "msg": "缺少必要组件主板"}]
        if not memory_list:
            return [{"type": "msg", "msg": "缺少必要组件内存"}]
        results = []
        for i, mem in enumerate(memory_list):
            label = str(i + 1) if len(memory_list) > 1 else ""
            mem_gen = mem.get("generation", "")
            mb_gens = mb.get("memory_generations", [])
            if not mem_gen or not mb_gens:
                results.append({"type": "msg", "msg": f"内存{label}缺少接口信息"})
                continue
            if mem_gen not in mb_gens:
                results.append({"type": "error",
                    "msg": f"主板和内存{label}接口不兼容，主板支持【{'/'.join(mb_gens)}】，内存【{mem_gen}】"})
                continue
            mem_freq = self._parse_num(mem.get("frequency_mt", 0))
            mb_freq = self._parse_num(mb.get("memory_freq_max", 0))
            if mem_freq and not mb_freq:
                results.append({"type": "skipped",
                    "msg": f"主板缺少内存最高频率字段，未检查内存{label}频率【{mem_freq}MHz】的XMP/EXPO/QVL条件",
                    "review_required": False})
            elif mem_freq and mb_freq and mem_freq > mb_freq:
                results.append({"type": "warn",
                    "msg": f"内存{label}频率【{mem_freq}MHz】超过主板支持【{mb_freq}MHz】，可能不稳定"})
            else:
                results.append({"type": "success", "msg": f"主板和内存{label}接口兼容【{mem_gen}】"})
        return results

    def check_memory_slots(self, memory_list, mb):
        """检查内存数量 vs 主板插槽数。"""
        if not mb:
            return {"type": "msg", "msg": "缺少必要组件主板"}
        if not memory_list:
            return {}
        total_sticks = sum(self._parse_num(m.get("module_count", 1)) for m in memory_list)
        mb_slots = self._parse_num(mb.get("memory_slots", 0))
        if not total_sticks or not mb_slots:
            return {}
        if total_sticks > mb_slots:
            return {"type": "error",
                "msg": f"内存数量过多，已选【{total_sticks}条】，主板插槽数量【{mb_slots}个】"}
        return {"type": "success", "msg": "内存插槽数量充足"}

    def check_memory_capacity(self, memory_list, mb):
        """检查内存总容量 vs 主板最大容量。"""
        if not mb:
            return {"type": "msg", "msg": "缺少必要组件主板"}
        if not memory_list:
            return {}
        total_gb = sum(self._parse_num(m.get("capacity_gb", 0)) for m in memory_list)
        max_gb = self._parse_num(mb.get("memory_max_gb", 0))
        if not total_gb or not max_gb:
            return {}
        if total_gb > max_gb:
            return {"type": "error",
                "msg": f"内存总容量【{total_gb}GB】超过主板最大支持【{max_gb}GB】"}
        return {"type": "success", "msg": "内存容量在主板支持范围内"}

    def check_gpu_case(self, gpu, case, index=""):
        """检查显卡长度 vs 机箱显卡限长。"""
        if not gpu:
            return {}
        if not case:
            return {"type": "msg", "msg": "缺少必要组件机箱"}
        gpu_len = self._parse_num(gpu.get("length_mm", 0))
        case_limit = self._parse_num(case.get("gpu_length_mm", 0))
        if not gpu_len or not case_limit:
            return {}
        if gpu_len > case_limit:
            return {"type": "error",
                "msg": f"显卡{index}长度【{gpu_len}mm】超过机箱限制【{case_limit}mm】"}
        return {"type": "success", "msg": f"显卡{index}长度在机箱限制内"}

    def check_storage_motherboard(self, storage_list, mb):
        """检查硬盘接口 vs 主板接口。"""
        if not storage_list:
            return {"type": "msg", "msg": "缺少必要组件硬盘"}
        if not mb:
            return {"type": "msg", "msg": "缺少必要组件主板"}
        m2_slots = self._parse_num(mb.get("m2_slots", 0))
        m2_count = sum(1 for s in storage_list
                       if "M.2" in s.get("form_factor", "") or "M.2" in s.get("interface", ""))
        m2_sata_count = sum(
            1 for s in storage_list
            if "M.2" in str(s.get("form_factor", ""))
            and "SATA" in str(s.get("interface", "")).upper()
        )
        if m2_count > 0 and m2_slots > 0 and m2_count > m2_slots:
            return {"type": "error",
                "msg": f"M.2硬盘数量【{m2_count}个】超过主板M.2接口数【{m2_slots}个】"}
        missing_interfaces = [
            str(index + 1)
            for index, storage in enumerate(storage_list)
            if not str(storage.get("interface") or "").strip()
        ]
        if missing_interfaces:
            return {
                "type": "msg",
                "msg": f"第{'、'.join(missing_interfaces)}块硬盘缺少接口信息，需复核M.2/NVMe/SATA类型",
            }
        if m2_sata_count:
            support_value = (
                mb.get("m2_sata_slots")
                or mb.get("m2_sata_support")
                or mb.get("sata_m2_slots")
            )
            if support_value in (True, "true", "yes", "支持"):
                support_slots = m2_sata_count
            else:
                support_slots = self._parse_num(support_value)
            if support_slots:
                if m2_sata_count > support_slots:
                    return {"type": "error",
                        "msg": f"M.2 SATA硬盘数量【{m2_sata_count}个】超过主板M.2 SATA支持数【{support_slots}个】"}
            else:
                return {"type": "warn",
                    "msg": "M.2 SATA硬盘需复核主板M.2插槽是否支持SATA模式；多数新主板M.2仅支持PCIe/NVMe"}
        if m2_count > 0 and not m2_slots:
            return {"type": "msg", "msg": "主板缺少M.2接口数量信息，需下单前复核"}
        return {"type": "success", "msg": "硬盘接口兼容"}

    def check_sata_ports(self, storage_list, mb):
        """检查 SATA 设备数 vs 主板 SATA 口数。"""
        if not storage_list:
            return {"type": "skipped", "msg": "未选择硬盘，跳过SATA接口检查", "review_required": False}
        if not mb:
            return {"type": "msg", "msg": "缺少必要组件主板"}
        if any(not str(storage.get("interface") or "").strip() for storage in storage_list):
            return {
                "type": "skipped",
                "msg": "硬盘接口信息不足，SATA数量由硬盘接口复核项覆盖",
                "review_required": False,
            }
        sata_count = sum(1 for s in storage_list
                         if "SATA" in s.get("interface", "") and "M.2" not in s.get("form_factor", ""))
        sata_ports = self._parse_num(mb.get("sata_ports", 0))
        if not sata_count:
            return {"type": "success", "msg": "未使用SATA设备，无需占用主板SATA接口"}
        if not sata_ports:
            return {"type": "msg", "msg": "主板缺少SATA接口数量信息，需下单前复核"}
        if sata_count > sata_ports:
            return {"type": "error",
                "msg": f"SATA设备【{sata_count}个】超过主板SATA口【{sata_ports}个】"}
        return {"type": "success", "msg": "SATA接口数量充足"}

    def check_psu_power(self, psu, cpu, gpu_list, extra_w=50):
        """检查电源功率是否满足整机功耗。

        余量公式: recommended = ceil((cpu_w + gpu_w + extra) * 1.35)
        extra_w 默认 50W (主板+内存+硬盘+风扇)。
        """
        if not psu:
            return {"type": "msg", "msg": "缺少必要组件电源"}
        psu_w = self._parse_rated_wattage(psu)
        cpu_w = self._parse_num(cpu.get("power_w", 0)) if cpu else 0
        gpu_powers = [self._parse_num(g.get("power_w", 0)) for g in (gpu_list or [])]
        gpu_w = sum(gpu_powers)
        if not psu_w:
            return {"type": "msg", "msg": "电源缺少功率信息"}
        if cpu and not cpu_w:
            return {"type": "msg", "msg": "CPU缺少功耗信息，电源功率需人工复核"}
        if gpu_list and any(not value for value in gpu_powers):
            missing = [str(index + 1) for index, value in enumerate(gpu_powers) if not value]
            return {"type": "msg", "msg": f"第{'、'.join(missing)}张显卡缺少功耗信息，电源功率需人工复核"}
        recommended = math.ceil((cpu_w + gpu_w + extra_w) * 1.35)
        if psu_w < recommended:
            return {"type": "error",
                "msg": f"电源功率【{psu_w}W】不足，建议≥{recommended}W (CPU {cpu_w}W + GPU {gpu_w}W + 其他 {extra_w}W ×1.35)"}
        margin = psu_w - recommended
        if margin < 50:
            return {"type": "warn",
                "msg": f"电源功率【{psu_w}W】刚好够用，建议功率≥{recommended + 50}W留更多余量"}
        return {"type": "success",
            "msg": f"电源功率【{psu_w}W】充足，推荐功率{recommended}W，余量{margin}W"}

    def check_gpu_power_connector(self, gpu, psu):
        """检查显卡供电接口兼容性。"""
        if not gpu or not psu:
            return {}
        connector_value = gpu.get("power_connectors")
        if connector_value in (None, "", []) and gpu.get("requires_16pin_psu") is None:
            return {"type": "msg", "msg": "显卡缺少供电接口信息，需下单前复核线材"}
        requires_16pin = infer_requires_16pin_gpu(gpu)
        native_16pin = infer_native_16pin_psu(psu)
        if requires_16pin and native_16pin is True:
            return {"type": "success", "msg": "显卡16pin供电与电源原生接口匹配"}
        if requires_16pin and native_16pin is False:
            return {"type": "warn",
                "msg": "显卡需要16pin供电，当前电源未标明原生16pin接口，需复核线材；无原生线材时可使用转接线"}
        if requires_16pin:
            return {"type": "msg",
                "msg": "显卡需要16pin供电，电源缺少原生接口字段，需下单前复核线材；无原生线材时可使用转接线"}
        return {"type": "success", "msg": "显卡未声明16pin供电需求"}

    def check_cooler_case(self, cooler, case):
        """检查散热器与机箱兼容性: 风冷高度/水冷冷排 vs 机箱限制。"""
        if not cooler:
            return {"type": "msg", "msg": "缺少必要组件散热"}
        if not case:
            return {"type": "msg", "msg": "缺少必要组件机箱"}
        cooler = enrich_item("coolers", cooler)
        cooler_type = cooler.get("type", "air")
        if cooler_type == "air":
            cooler_height = self._parse_num(cooler.get("height_mm", 0))
            case_limit = self._parse_num(case.get("cpu_cooler_height_mm", 0))
            if cooler_height and case_limit:
                if cooler_height > case_limit:
                    return {"type": "error",
                        "msg": f"风冷高度【{cooler_height}mm】超过机箱限制【{case_limit}mm】"}
                return {"type": "success", "msg": "风冷高度在机箱限制内"}
        elif cooler_type in ("liquid", "water", "水冷"):
            radiator = cooler.get("radiator_mm", "")
            rad_support = case.get("radiator_support", [])
            if radiator and rad_support:
                requested = int(self._parse_num(radiator))
                listed_sizes = {
                    int(size)
                    for value in rad_support
                    for size in re.findall(r"(?<!\d)(120|140|240|280|360|420)(?!\d)", str(value))
                }
                supported = any(
                    requested in self.RADIATOR_SIZE_COMPATIBILITY.get(size, {size})
                    for size in listed_sizes
                )
                if not supported:
                    return {"type": "error",
                        "msg": f"冷排【{radiator}】不在机箱支持范围【{rad_support}】"}
                return {"type": "success", "msg": "冷排在机箱支持范围内"}
        return {}

    def check_case_motherboard(self, case, mb):
        """检查机箱是否支持主板版型。

        逻辑: 机箱支持列表中的每种版型，通过 FORM_FACTOR_MAP 向下兼容
        更小的版型。如果主板版型出现在任何机箱支持版型的兼容列表中，
        则机箱可以装下该主板。
        """
        if not case:
            return {"type": "msg", "msg": "缺少必要组件机箱"}
        if not mb:
            return {"type": "msg", "msg": "缺少必要组件主板"}
        mb_ff = mb.get("form_factor", "")
        case_support = case.get("motherboard_support", [])
        ff_normalized = self._normalize_form_factor(mb_ff)
        support_normalized = [self._normalize_form_factor(s) for s in case_support]
        # 直接匹配
        if ff_normalized in support_normalized:
            return {"type": "success", "msg": f"机箱支持{mb_ff}版型"}
        # 向下兼容: 机箱支持的每种版型可以兼容更小的主板版型
        for case_ff in support_normalized:
            compatible_list = self.FORM_FACTOR_MAP.get(case_ff, [])
            if ff_normalized in compatible_list:
                return {"type": "success", "msg": f"机箱支持{mb_ff}版型(通过{case_ff}向下兼容)"}
        return {"type": "error",
            "msg": f"机箱与主板版型不匹配，机箱支持【{'/'.join(case_support)}】，主板【{mb_ff}】"}

    def check_case_psu(self, case, psu):
        """检查机箱电源位 vs 电源尺寸。"""
        if not case:
            return {"type": "msg", "msg": "缺少必要组件机箱"}
        if not psu:
            return {}
        case_model = str(case.get("model", ""))
        case_psu_support = [self._normalize(s) for s in case.get("psu_support", ["ATX"])]
        model_special = any(
            term in case_model.upper()
            for term in ("ITX", "MINI", "SFX", "NAS", "HTPC", "卧式", "小型", "紧凑")
        )
        small_psu_forms = ("SFX", "SFXL", "TFX", "FLEX")
        small_psu_only = "ATX" not in case_psu_support and any(s in small_psu_forms for s in case_psu_support)
        motherboard_support = [self._normalize(s) for s in case.get("motherboard_support", [])]
        compact_hybrid = (
            bool(motherboard_support)
            and "ATX" not in motherboard_support
            and any(s in small_psu_forms for s in case_psu_support)
        )
        special_case = model_special or small_psu_only or compact_hybrid
        psu_size = self._normalize(psu.get("form_factor"))
        if not psu_size:
            return {"type": "skipped",
                "msg": "电源缺少规格字段，普通机箱虽通常使用ATX电源，仍需确认实际为ATX/SFX/SFX-L/FLEX及限长/限高"}
        if not case_psu_support:
            return {"type": "msg", "msg": "机箱缺少电源规格支持信息，需下单前复核"}

        if "ATX" in case_psu_support and not special_case and psu_size in small_psu_forms:
            return {"type": "error",
                "msg": "普通ATX/MATX机箱默认不使用SFX/SFX-L/FLEX/TFX小电源；若明确复用小电源，需单独确认转接支架、线材长度和电源限长/限高"}

        psu_len = self._parse_num(psu.get("length_mm", 0))
        case_limit = self._parse_num(
            case.get("psu_length_mm", 0) or case.get("psu_max_length_mm", 0) or case.get("psu_clearance_mm", 0)
        )
        recommended_limit = self._parse_num(case.get("psu_length_recommended_mm", 0))
        length_condition = str(case.get("psu_length_condition") or "").strip()
        if psu_size in case_psu_support:
            if special_case and (not case_limit or not psu_len):
                return {"type": "skipped",
                    "msg": "小机箱或特殊电源位缺少机箱电源限长或电源长度字段，需下单前复核限长/限高、转接支架、线材弯折和硬盘笼空间"}
            if case_limit and psu_len and psu_len > case_limit:
                return {"type": "error",
                    "msg": f"电源长度【{psu_len}mm】超过机箱电源位限制【{case_limit}mm】"}
            if recommended_limit and psu_len and psu_len > recommended_limit:
                condition_text = length_condition.rstrip("。；，,; ")
                detail = f"；{condition_text}" if condition_text else ""
                return {"type": "warn",
                    "msg": f"电源长度【{psu_len}mm】未超过物理上限【{case_limit}mm】，但超过保守建议【{recommended_limit}mm】{detail}，需按冷排、显卡、硬盘笼和线材布局复核"}
            if length_condition and case_limit and psu_len and not recommended_limit:
                return {"type": "warn",
                    "msg": f"电源长度【{psu_len}mm】未超过物理上限【{case_limit}mm】，但该上限存在布局条件；{length_condition}，需复核实际安装组合"}
            if case_limit and psu_len and case_limit - psu_len < 20:
                return {"type": "warn",
                    "msg": f"电源长度【{psu_len}mm】接近机箱电源位限制【{case_limit}mm】，需复核线材弯折、限高和硬盘笼空间"}
            if case_limit and not psu_len and special_case:
                return {"type": "msg",
                    "msg": f"机箱电源位限制【{case_limit}mm】，电源缺少长度字段，需下单前复核限长/限高和线材空间"}
            return {"type": "success", "msg": "机箱和电源规格匹配"}
        return {"type": "error",
            "msg": f"机箱和电源规格不匹配，机箱支持【{case.get('psu_support')}】，电源【{psu.get('form_factor', psu_size)}】"}

    # --- 主入口 ---

    def _skipped(self, msg, review_required=True):
        return {"type": "skipped", "msg": msg, "review_required": review_required}

    def _add_check(self, checks, name, result, skipped_msg="无可检查项", skipped_review_required=True):
        checks.append((name, result or self._skipped(skipped_msg, skipped_review_required)))

    def check_all(self, build, strict=False, missing_ids=None):
        """检查完整配置的兼容性。

        Args:
            build: dict with keys: cpu, motherboard, memory (list),
                   storage (list), gpu (list), psu, cooler, case
            strict: final-build mode. Missing core parts become errors.
            missing_ids: IDs passed by the caller but not found in the library.
        Returns:
            Compatibility and evidence completeness are reported separately.
            ``overall`` keeps the legacy pass/warn/fail contract.
        """
        cpu = build.get("cpu")
        mb = build.get("motherboard")
        mem = build.get("memory", [])
        storage = build.get("storage", [])
        gpus = build.get("gpu", [])
        psu = build.get("psu")
        cooler = build.get("cooler")
        case = build.get("case")
        checks = []
        for missing_id in (missing_ids or []):
            checks.append(("ID校验", {"type": "error", "msg": f"未找到配件ID: {missing_id}"}))
        if strict:
            required = [
                ("CPU", cpu),
                ("主板", mb),
                ("内存", mem),
                ("硬盘", storage),
                ("电源", psu),
                ("散热", cooler),
                ("机箱", case),
            ]
            for label, value in required:
                if value is None or value == []:
                    checks.append(("完整性", {"type": "error", "msg": f"严格模式缺少{label}"}))
            if not gpus and not self._cpu_has_integrated_graphics(cpu):
                checks.append(("完整性", {"type": "error", "msg": "严格模式缺少独显，且CPU未确认带核显"}))
        self._add_check(checks, "CPU↔主板", self.check_cpu_motherboard(cpu, mb))
        if not gpus and self._cpu_has_integrated_graphics(cpu):
            self._add_check(checks, "显示输出", {"type": "success", "msg": "未选择独显，CPU可提供核显显示输出"})
        mem_results = self.check_memory_motherboard(mem, mb)
        for r in mem_results:
            self._add_check(checks, "内存↔主板", r)
        self._add_check(checks, "内存插槽数", self.check_memory_slots(mem, mb), "未检查内存插槽数量")
        self._add_check(checks, "内存容量", self.check_memory_capacity(mem, mb), "未检查内存容量上限")
        for i, gpu in enumerate(gpus):
            self._add_check(checks, "显卡↔机箱", self.check_gpu_case(gpu, case, str(i+1) if len(gpus)>1 else ""))
        if not gpus:
            self._add_check(
                checks,
                "显卡↔机箱",
                {},
                "未选择显卡，跳过显卡机箱限长检查",
                skipped_review_required=False,
            )
        self._add_check(checks, "硬盘↔主板", self.check_storage_motherboard(storage, mb))
        self._add_check(checks, "SATA接口", self.check_sata_ports(storage, mb), "没有SATA设备或缺少SATA信息")
        self._add_check(checks, "电源功率", self.check_psu_power(psu, cpu, gpus))
        for i, gpu in enumerate(gpus):
            label = f"显卡{i+1}供电" if len(gpus) > 1 else "显卡供电"
            self._add_check(checks, label, self.check_gpu_power_connector(gpu, psu), "显卡未声明特殊供电需求")
        if not gpus:
            self._add_check(
                checks,
                "显卡供电",
                {},
                "未选择显卡，跳过显卡供电检查",
                skipped_review_required=False,
            )
        self._add_check(checks, "散热↔机箱", self.check_cooler_case(cooler, case))
        self._add_check(checks, "机箱↔主板", self.check_case_motherboard(case, mb))
        self._add_check(checks, "机箱↔电源", self.check_case_psu(case, psu), "未检查机箱电源尺寸")
        severity = {"error": 0, "warn": 0, "success": 0, "msg": 0, "skipped": 0}
        for _, r in checks:
            t = r.get("type", "")
            severity[t] = severity.get(t, 0) + 1
        if severity["error"] > 0:
            overall = "fail"
        elif severity["warn"] > 0:
            overall = "warn"
        else:
            overall = "pass"
        review_count = sum(
            1
            for _, check in checks
            if check.get("type") in ("warn", "msg")
            or (check.get("type") == "skipped" and check.get("review_required", True))
        )
        compatible = severity["error"] == 0
        review_required = review_count > 0
        complete = compatible and not review_required
        status = "incompatible" if not compatible else ("needs_review" if review_required else "complete")
        return {
            "overall": overall,
            "status": status,
            "compatible": compatible,
            "complete": complete,
            "review_required": review_required,
            "review_count": review_count,
            "checks": checks,
            "severity": severity,
        }


def load_components():
    """加载 components.yaml 和 cases.yaml。"""
    by_id = {}
    components_path = DATA / "components.yaml"
    if components_path.exists():
        with components_path.open("r", encoding="utf-8") as f:
            lib = yaml.safe_load(f) or {}
        for section in ["cpus", "motherboards", "memory", "storage", "gpus", "coolers", "psus"]:
            for item in lib.get(section, []):
                by_id[item["id"]] = enrich_item(section, item)
    cases_path = DATA / "cases.yaml"
    if cases_path.exists():
        with cases_path.open("r", encoding="utf-8") as f:
            cases = yaml.safe_load(f) or {}
        for item in cases.get("cases", []):
            by_id[item["id"]] = item
    return by_id


def main():
    parser = argparse.ArgumentParser(
        description="装机兼容性检查 — 12 类基础兼容性检查")
    parser.add_argument("--cpu", help="CPU ID")
    parser.add_argument("--mb", help="主板 ID")
    parser.add_argument("--mem", action="append", help="内存 ID (可多次指定)")
    parser.add_argument("--storage", action="append", help="硬盘 ID (可多次指定)")
    parser.add_argument("--gpu", action="append", help="显卡 ID (可多次指定)")
    parser.add_argument("--psu", help="电源 ID")
    parser.add_argument("--cooler", help="散热 ID")
    parser.add_argument("--case", help="机箱 ID")
    parser.add_argument("--strict", action="store_true", help="严格模式: 最终整机必须包含核心配件")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="完整度门禁: 有警告、待复核信息或需复核的跳过项时返回退出码2",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    by_id = load_components()
    missing_ids = []

    def get(id_str):
        if not id_str:
            return None
        item = by_id.get(id_str)
        if item is None:
            missing_ids.append(id_str)
        return item

    def get_list(id_list):
        items = []
        for id_str in id_list or []:
            item = get(id_str)
            if item is not None:
                items.append(item)
        return items

    build = {
        "cpu": get(args.cpu),
        "motherboard": get(args.mb),
        "memory": get_list(args.mem),
        "storage": get_list(args.storage),
        "gpu": get_list(args.gpu),
        "psu": get(args.psu),
        "cooler": get(args.cooler),
        "case": get(args.case),
    }

    checker = CompatibilityChecker()
    result = checker.check_all(build, strict=args.strict, missing_ids=missing_ids)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"兼容性检查结果: {result['overall'].upper()}")
        print(f"检查完整度: {result['status'].upper()}")
        print(f"  错误: {result['severity']['error']}, "
              f"警告: {result['severity']['warn']}, "
              f"通过: {result['severity']['success']}, "
              f"跳过: {result['severity'].get('skipped', 0)}")
        print()
        for name, check in result["checks"]:
            if check.get("type"):
                icon = {"error": "❌", "warn": "⚠️", "success": "✅", "msg": "ℹ️", "skipped": "↷"}.get(check["type"], "  ")
                print(f"  {icon} {name}: {check['msg']}")
    if result["overall"] == "fail":
        return 1
    if args.require_complete and not result["complete"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
