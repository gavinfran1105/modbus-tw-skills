#!/usr/bin/env python3
"""未知 Modbus 設備：把唯讀掃描得到的原始暫存器值，離線產生解碼候選。

本腳本**不連任何設備**、不連網路，只讀你用其他工具（唯讀、FC03／FC04）
掃描後存下來的 CSV。

輸入 CSV（UTF-8）欄位：
    fc        3 或 4（只接受唯讀功能碼）
    address   0 起算封包位址
    sample1   第一次取樣的 16 位元原始值（0–65535，十進位或 0x 十六進位）
    sample2   第二次取樣（建議間隔數秒、現場狀態有變化時取）
    ...       可再加 sample3、sample4

用法：
    python decode_candidates.py 掃描結果.csv -o 候選.csv

輸出每一列都是「候選」，不是結論：原始值、是否變化、解碼候選、推測理由、
信心分開成欄位。請用原廠手冊或現場已知變化（例如開關負載、改變溫度）驗證。
"""
from __future__ import annotations

import argparse
import csv
import math
import struct
import sys
from pathlib import Path

SCALES = [1, 0.1, 0.01, 0.001]
ORDERS = ["ABCD", "CDAB", "BADC", "DCBA"]


def to_int(s: str) -> int:
    s = s.strip().lower()
    v = int(s, 16) if s.startswith("0x") else int(s)
    if not 0 <= v <= 0xFFFF:
        raise ValueError(f"原始值 {s} 不是 16 位元")
    return v


def words_to_bytes(w1: int, w2: int, order: str) -> bytes:
    a, b = w1 >> 8, w1 & 0xFF
    c, d = w2 >> 8, w2 & 0xFF
    m = {"A": a, "B": b, "C": c, "D": d}
    return bytes(m[ch] for ch in order)


def plausible_float(x: float) -> bool:
    return math.isfinite(x) and (x == 0 or 1e-4 <= abs(x) <= 1e7)


def load(path: Path) -> dict[tuple[int, int], list[int]]:
    data: dict[tuple[int, int], list[int]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols = [c for c in (rd.fieldnames or []) if c and c.strip().lower().startswith("sample")]
        if len(cols) < 2:
            raise SystemExit("至少要兩次取樣（sample1、sample2）才能判斷變化")
        for i, r in enumerate(rd, start=2):
            fc = int(r["fc"])
            if fc not in (3, 4):
                raise SystemExit(f"第 {i} 列：只接受唯讀功能碼 3／4，收到 {fc}")
            addr = int(r["address"])
            data[(fc, addr)] = [to_int(r[c]) for c in cols if (r.get(c) or "").strip()]
    return data


def analyse(data: dict[tuple[int, int], list[int]]) -> list[dict]:
    rows = []
    for (fc, addr), samples in sorted(data.items()):
        changed = len(set(samples)) > 1
        s0 = samples[0]
        cands, reasons = [], []
        signed = s0 - 0x10000 if s0 >= 0x8000 else s0
        if s0 == 0 and not changed:
            reasons.append("兩次都是 0：可能未使用或狀態量")
        elif not changed and s0 in (0xFFFF, 0x8000, 0x7FFF):
            reasons.append("固定為邊界值：常見於未使用位置或錯誤碼")
        for sc in SCALES:
            cands.append(f"uint16×{sc}={round(s0 * sc, 4)}")
            if s0 >= 0x8000:
                cands.append(f"int16×{sc}={round(signed * sc, 4)}")
        if s0 < 16 and not changed:
            reasons.append("小整數且不變：可能是狀態、模式或設定值")
        nxt = data.get((fc, addr + 1))
        if nxt:
            w2 = nxt[0]
            for order in ORDERS:
                b = words_to_bytes(s0, w2, order)
                fv = struct.unpack(">f", b)[0]
                if plausible_float(fv):
                    cands.append(f"float32[{order}]@{addr}-{addr+1}={fv:.6g}")
                u32 = struct.unpack(">I", b)[0]
                if u32 and u32 < 10**9:
                    cands.append(f"uint32[{order}]@{addr}-{addr+1}={u32}")
        if changed:
            reasons.append("兩次取樣有變化：較可能是即時量測值")
        conf = "中" if changed and len(cands) > 0 else "低"
        rows.append({
            "fc": fc, "address": addr,
            "raw": " / ".join(str(x) for x in samples),
            "raw_hex": " / ".join(f"0x{x:04X}" for x in samples),
            "changed": "是" if changed else "否",
            "candidates": "；".join(cands),
            "reason": "；".join(reasons) or "沒有足夠特徵",
            "confidence": conf,
            "status": "候選（未驗證）",
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="未知 Modbus 設備：原始值 → 解碼候選（離線）")
    ap.add_argument("csv", type=Path)
    ap.add_argument("-o", "--output", type=Path)
    a = ap.parse_args(argv)
    rows = analyse(load(a.csv))
    out = a.output or a.csv.with_name(a.csv.stem + ".candidates.csv")
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["fc"])
        w.writeheader()
        w.writerows(rows)
    print(f"完成：{len(rows)} 個位址 → {out}（全部是候選，請逐點驗證）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
