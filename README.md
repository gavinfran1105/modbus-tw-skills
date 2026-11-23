# modbus-tw-skills

給 Claude Code、Codex 與其他支援 [Agent Skills](https://agentskills.io)（SKILL.md）的 AI 使用的 Modbus 技能包，以**台灣現場**常見的中文位置表為主。

| skill | 用途 |
|---|---|
| [`modbus-sitemap-tw`](skills/modbus-sitemap-tw/SKILL.md) | 中文位置表（位址／名稱／型別／倍率／功能碼／單位）解析、檢核、轉 tag map；40001 與 0 起算換算、ABCD／CDAB 字序、倍率寫法、重疊檢查、逐點確認流程 |
| [`modbus-unknown-device-discovery`](skills/modbus-unknown-device-discovery/SKILL.md) | 沒有手冊的設備：唯讀（FC03／FC04）探索規則，離線產生解碼候選、倍率候選、用途推測與信心 |

## 特色

- 中英文、全形半形欄位名稱都認得；CSV 支援 UTF-8、CP950、Big5。
- 位址寫法混用時停下來要你指定，不會默默整份差 1。
- 所有結果都是「候選」，上線前要逐點確認，並保留來源方便對照手冊。
- 只用 Python 標準函式庫，不連設備、不連網路（見 [SECURITY.md](SECURITY.md)）。
- 輸出相容 [IndustriAgents/MODBUS-MCP](https://github.com/IndustriAgents/MODBUS-MCP) 的 tag map。

## 安裝

把 `skills/` 底下的資料夾複製到你的 agent skill 目錄：

- Claude Code：`~/.claude/skills/`
- Codex：`~/.agents/skills/`

或使用 [Skills CLI](https://github.com/vercel-labs/skills)：`npx skills add <你的帳號>/modbus-tw-skills`

## 快速試用

```bash
python skills/modbus-sitemap-tw/scripts/sitemap_to_tagmap.py skills/modbus-sitemap-tw/examples/示範位置表.csv --check
python skills/modbus-unknown-device-discovery/scripts/decode_candidates.py skills/modbus-unknown-device-discovery/examples/示範掃描結果.csv
python -m unittest discover -s tests
```

## English

Agent skills for Modbus register maps in the format commonly used in Taiwan (Traditional Chinese column names). Parses and validates vendor register maps, converts 4xxxx/3xxxx reference addresses to zero-based PDU addresses, handles word order (ABCD/CDAB/BADC/DCBA) and scale notation, and defines a point-by-point confirmation workflow. A second skill covers read-only discovery of undocumented devices and offline decoding of candidates. Standard-library Python only; no device or network access.

## 授權

MIT
