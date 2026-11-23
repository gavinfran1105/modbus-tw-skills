#!/usr/bin/env python3
"""台灣常見的 Modbus 位置表（CSV）→ 檢核 → tag map JSON。

只用 Python 標準函式庫，不連網路、不連任何設備。

用法：
    python sitemap_to_tagmap.py 位置表.csv -o 設備.tags.json
    python sitemap_to_tagmap.py 位置表.csv --check          # 只檢核，不輸出
    python sitemap_to_tagmap.py 位置表.csv --address-mode zero

CSV 欄位（標題不分大小寫、全形半形，中英文都收）：
    必填：tag（名稱）、address（位址）
    選填：table（功能碼／區塊）、dtype（型別）、byteorder、wordorder（字序）、
          scale（倍率）、offset、unit（單位）、count、description（說明）、
          slave_id（站號）、writable（讀寫）、note（備註）

位址寫法（--address-mode）：
    auto       預設。40001／400001 這類 5、6 位數寫法視為參考位址（換成 0 起算），
               其他數字視為 0 起算。同一份表若兩種寫法混用，整份不輸出，
               請改用 reference 或 zero 明確指定。
    reference  全部數字都當參考位址（40001 → holding 0；30010 → input 9）。
    zero       全部數字都當 0 起算的封包位址。
    0x 開頭的十六進位一律是封包位址。

輸出格式相容 IndustriAgents/MODBUS-MCP 的 REGISTER_MAP_FILE。
任何一列有錯誤就整份不輸出（exit code 1），並列出所有錯誤。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

DTYPES = {"int16", "uint16", "int32", "uint32", "float32", "int64", "uint64", "float64"}
DTYPE_ALIASES = {
    "u16": "uint16", "uint": "uint16", "word": "uint16", "unsigned": "uint16",
    "i16": "int16", "int": "int16", "short": "int16", "signed": "int16",
    "u32": "uint32", "udint": "uint32", "dword": "uint32", "ulong": "uint32",
    "i32": "int32", "dint": "int32", "long": "int32",
    "f32": "float32", "float": "float32", "real": "float32",
    "u64": "uint64", "i64": "int64", "f64": "float64", "double": "float64", "lreal": "float64",
}
ORDERS = {"big", "little"}
# 32 位元常見寫法 → (byteorder, wordorder)
ORDER_ALIASES = {
    "abcd": ("big", "big"), "cdab": ("big", "little"),
    "badc": ("little", "big"), "dcba": ("little", "little"),
}

HEADER_ALIASES = {
    "tag": {"tag", "name", "點位", "點位名稱", "名稱", "tag名稱", "項目", "參數名稱"},
    "table": {"table", "fc", "function", "function_code", "功能碼", "暫存器類型", "區塊", "類型"},
    "address": {"address", "addr", "register", "位址", "地址", "暫存器", "暫存器位址", "通訊位址"},
    "dtype": {"dtype", "datatype", "data_type", "type", "型別", "資料型別", "資料型態", "格式"},
    "byteorder": {"byteorder", "byte_order", "位元組序"},
    "wordorder": {"wordorder", "word_order", "字組序", "字序", "字組順序", "排列"},
    "scale": {"scale", "倍率", "resolution", "係數", "比例"},
    "offset": {"offset", "偏移"},
    "unit": {"unit", "單位"},
    "count": {"count", "數量", "長度"},
    "description": {"description", "desc", "描述", "說明"},
    "slave_id": {"slave_id", "unit_id", "unitid", "站號", "slave", "設備位址"},
    "writable": {"writable", "rw", "access", "可寫", "讀寫", "屬性"},
    "note": {"note", "備註"},
}

TABLE_ALIASES = {
    "holding": "holding", "hr": "holding", "4x": "holding", "fc03": "holding", "03": "holding", "3": "holding",
    "input": "input", "ir": "input", "3x": "input", "fc04": "input", "04": "input", "4": "input",
    "coil": "coil", "coils": "coil", "0x": "coil", "fc01": "coil", "01": "coil", "1": "coil",
    "discrete": "discrete", "di": "discrete", "1x": "discrete", "fc02": "discrete", "02": "discrete", "2": "discrete",
}
PREFIX_TABLE = {"4": "holding", "3": "input", "1": "discrete", "0": "coil"}


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


def norm_header(h: str) -> str | None:
    k = nfkc(h).lower().replace(" ", "_")
    for canon, names in HEADER_ALIASES.items():
        if k in names:
            return canon
    return None


def parse_table(raw: str) -> str | None:
    return TABLE_ALIASES.get(nfkc(raw).lower().replace(" ", ""))


def parse_number(raw: str) -> float:
    """接受 0.01、1e-2、×0.01、x0.01、1/100、/100。"""
    s = nfkc(raw).lower().replace("×", "").replace(" ", "")
    if s.startswith("x") or s.startswith("*"):
        s = s[1:]
    if "/" in s:
        a, b = s.split("/", 1)
        return (float(a) if a else 1.0) / float(b)
    return float(s)


def is_reference(s: str) -> bool:
    return bool(re.fullmatch(r"[0134]\d{4,5}", s))


def parse_address(raw: str, table: str | None, mode: str) -> tuple[int, str | None]:
    """回傳 (0 起算位址, 由參考寫法推出的 table 或 None)。"""
    s = nfkc(raw).lower()
    if re.fullmatch(r"0x[0-9a-f]+", s):
        return int(s, 16), None
    if not re.fullmatch(r"\d+", s):
        raise ValueError(f"位址看不懂：{raw!r}")
    if mode == "zero":
        return int(s), None
    if mode == "reference" and not is_reference(s):
        raise ValueError(f"reference 模式下位址 {raw!r} 不是 5／6 位數參考位址")
    if is_reference(s):
        t = PREFIX_TABLE[s[0]]
        n = int(s[1:]) - 1
        if n < 0 or n > 65535:
            raise ValueError(f"參考位址 {raw!r} 超出範圍（例如 465537 不合法）")
        if table is not None and table != t:
            raise ValueError(f"位址 {raw!r} 的前綴是 {t}，但功能碼欄寫 {table}")
        return n, t
    return int(s), None


def truthy(v: str) -> bool:
    return nfkc(v).lower() in {"1", "true", "yes", "y", "是", "rw", "w", "r/w", "可", "讀寫"}


class RowError(Exception):
    pass


def convert_row(row: dict[str, str], notes: list[str], where: str, mode: str) -> dict:
    table = None
    if nfkc(row.get("table", "")):
        table = parse_table(row["table"])
        if table is None:
            raise RowError(f"功能碼／區塊看不懂 {row['table']!r}（用 holding/input/coil/discrete、4x/3x/0x/1x 或 FC03/FC04/FC01/FC02）")
    try:
        addr, t_from_addr = parse_address(row.get("address", ""), table, mode)
    except ValueError as e:
        raise RowError(str(e))
    table = table or t_from_addr
    if table is None:
        raise RowError("沒有功能碼，位址寫法也推不出來")
    tag: dict = {"table": table, "address": addr}

    count = nfkc(row.get("count", ""))
    if count:
        if not count.isdigit() or int(count) < 1:
            raise RowError("count 要是正整數")
        if int(count) != 1:
            tag["count"] = int(count)

    sid = nfkc(row.get("slave_id", ""))
    if sid:
        if not sid.isdigit() or not 0 <= int(sid) <= 247:
            raise RowError("站號要是 0–247")
        tag["slave_id"] = int(sid)

    dtype = nfkc(row.get("dtype", "")).lower()
    dtype = DTYPE_ALIASES.get(dtype, dtype)
    scale = nfkc(row.get("scale", ""))
    offset = nfkc(row.get("offset", ""))
    bo = nfkc(row.get("byteorder", "")).lower()
    wo = nfkc(row.get("wordorder", "")).lower()
    if wo in ORDER_ALIASES:
        bo2, wo = ORDER_ALIASES[wo]
        bo = bo or bo2

    if table in ("coil", "discrete"):
        if dtype in ("bool", "bit", "布林"):
            dtype = ""
        if any([dtype, scale, offset, bo, wo]):
            raise RowError("coil/discrete 不能有型別、倍率、offset 或字序")
    else:
        if dtype and dtype not in DTYPES:
            raise RowError(f"型別 {dtype!r} 不支援（{', '.join(sorted(DTYPES))}）")
        if (scale or offset) and not dtype:
            dtype = "uint16"
            notes.append(f"{where}：有倍率但沒型別，已補 uint16，請確認是否為有號數（負溫度要用 int16）")
        if dtype:
            tag["dtype"] = dtype
            if dtype.endswith(("32", "64")) and not wo:
                notes.append(f"{where}：{dtype} 沒填字序，預設 big（ABCD）；不同廠牌常用 CDAB，請對照手冊或實機讀值")
        for key, val in (("byteorder", bo), ("wordorder", wo)):
            if val:
                if val not in ORDERS:
                    raise RowError(f"{key} 只能是 big/little 或 ABCD/CDAB/BADC/DCBA")
                tag[key] = val
        for key, val in (("scale", scale), ("offset", offset)):
            if val:
                try:
                    f = parse_number(val)
                except (ValueError, ZeroDivisionError):
                    raise RowError(f"{key} 不是數字 {val!r}")
                if key == "scale" and f == 0:
                    raise RowError("倍率不可為 0")
                tag[key] = f

    span = tag.get("count", 1)
    if tag.get("dtype"):
        span *= {"16": 1, "32": 2, "64": 4}[re.search(r"(16|32|64)", tag["dtype"]).group(1)]
    if addr + span - 1 > 65535:
        raise RowError("位址超過 65535")
    tag["_span"] = span

    unit = nfkc(row.get("unit", ""))
    if unit:
        tag["unit"] = unit
    elif table in ("holding", "input"):
        notes.append(f"{where}：單位空白，請確認是否真的沒有單位")
    desc = (row.get("description") or "").strip()
    if row.get("writable") and truthy(row["writable"]):
        desc = (desc + " " if desc else "") + "[可寫]"
    note = (row.get("note") or "").strip()
    if note:
        desc = (desc + "；" if desc else "") + note
    if desc:
        tag["description"] = desc
    return tag


def detect_mixed(rows: list[dict[str, str]]) -> bool:
    kinds = set()
    for r in rows:
        s = nfkc(r.get("address", "")).lower()
        if not s or s.startswith("0x"):
            continue
        if re.fullmatch(r"\d+", s):
            kinds.add("ref" if is_reference(s) else "zero")
    return kinds == {"ref", "zero"}


def convert(rows: list[dict[str, str]], mode: str = "auto") -> tuple[dict, list[str], list[str]]:
    tags: dict[str, dict] = {}
    errors: list[str] = []
    notes: list[str] = []
    if mode == "auto" and detect_mixed(rows):
        errors.append("位址寫法不一致：同一份表同時有 40001 這類參考位址和 0 起算位址。"
                      "請用 --address-mode reference 或 --address-mode zero 明確指定，避免整份差 1。")
        return {}, errors, notes
    for i, row in enumerate(rows, start=2):
        name = nfkc(row.get("tag", ""))
        if not name:
            if any(nfkc(v) for v in row.values()):
                errors.append(f"第 {i} 列：沒有名稱")
            continue
        where = f"第 {i} 列 {name}"
        if name in tags:
            errors.append(f"{where}：名稱重複")
            continue
        try:
            tags[name] = convert_row(row, notes, where, mode)
        except RowError as e:
            errors.append(f"{where}：{e}")
    # 重疊檢查（同站號、同區塊）
    used: dict[tuple, str] = {}
    for name, t in tags.items():
        for a in range(t["address"], t["address"] + t["_span"]):
            k = (t.get("slave_id"), t["table"], a)
            if k in used:
                errors.append(f"{name}：位址 {a} 與 {used[k]} 重疊")
                break
            used[k] = name
    for t in tags.values():
        t.pop("_span", None)
    return tags, errors, notes


def read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    if len(raw) > 20 * 1024 * 1024:
        raise SystemExit("檔案超過 20 MiB，請拆檔")
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("CSV 編碼看不懂（試過 UTF-8、CP950、Big5），請另存為 UTF-8")
    reader = csv.reader(text.splitlines())
    header = next(reader, None)
    if not header:
        raise SystemExit("CSV 是空的")
    canon = [norm_header(h) for h in header]
    if "tag" not in canon or "address" not in canon:
        raise SystemExit(f"找不到必要欄位（名稱、位址），讀到的標題：{header}")
    out = []
    for r in reader:
        d: dict[str, str] = {}
        for k, v in zip(canon, r):
            if k and k not in d:
                d[k] = v
        out.append(d)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Modbus 位置表 CSV → 檢核 → tag map JSON（離線，不連設備）")
    ap.add_argument("csv", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="輸出檔（預設與 CSV 同名 .tags.json）")
    ap.add_argument("--address-mode", choices=["auto", "reference", "zero"], default="auto")
    ap.add_argument("--check", action="store_true", help="只檢核，不輸出檔案")
    a = ap.parse_args(argv)
    rows = read_csv(a.csv)
    tags, errors, notes = convert(rows, a.address_mode)
    for n in notes:
        print("提醒：" + n)
    if errors:
        print(f"有 {len(errors)} 個錯誤，沒有輸出：", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
        return 1
    if a.check:
        print(f"檢核通過：{len(tags)} 個點位（未輸出檔案）")
        return 0
    out = a.output or a.csv.with_suffix(".tags.json")
    out.write_text(json.dumps(tags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完成：{len(tags)} 個點位 → {out}")
    print("轉完請先用模擬器或實機唯讀試讀，和設備面板數值比對後再上線。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
