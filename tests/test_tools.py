import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/modbus-sitemap-tw/scripts"))
sys.path.insert(0, str(ROOT / "skills/modbus-unknown-device-discovery/scripts"))
import sitemap_to_tagmap as st  # noqa: E402
import decode_candidates as dc  # noqa: E402


def rows(text):
    p = Path(tempfile.mkdtemp()) / "t.csv"
    p.write_text(text, encoding="utf-8")
    return st.read_csv(p)


class SitemapTests(unittest.TestCase):
    def test_example_passes(self):
        r = st.read_csv(ROOT / "skills/modbus-sitemap-tw/examples/示範位置表.csv")
        tags, errors, notes = st.convert(r)
        self.assertEqual(errors, [])
        self.assertEqual(tags["溫度"], {"table": "input", "address": 0, "dtype": "int16", "scale": 0.1,
                                       "unit": "°C", "description": "示範設備 DEMO-TH1（虛構）"})
        self.assertEqual(tags["累積電量"]["wordorder"], "little")
        self.assertAlmostEqual(tags["濕度"]["scale"], 0.1)
        self.assertEqual(tags["通訊逾時設定"]["address"], 100)

    def test_reference_addresses(self):
        for raw, table, addr in [("40001", "holding", 0), ("400001", "holding", 0), ("465536", "holding", 65535),
                                 ("300010", "input", 9), ("10001", "discrete", 0)]:
            self.assertEqual(st.parse_address(raw, None, "auto"), (addr, table))
        with self.assertRaises(ValueError):
            st.parse_address("465537", None, "auto")
        self.assertEqual(st.parse_address("0x1000", "holding", "auto"), (4096, None))

    def test_mixed_addresses_stop(self):
        r = rows("名稱,位址,功能碼\na,40001,FC03\nb,5,FC03\n")
        tags, errors, _ = st.convert(r)
        self.assertTrue(errors and "不一致" in errors[0])
        tags, errors, _ = st.convert(r, "zero")
        self.assertEqual(errors, [])
        self.assertEqual(tags["a"]["address"], 40001)

    def test_prefix_conflict(self):
        _, errors, _ = st.convert(rows("名稱,位址,功能碼\na,40001,FC04\n"))
        self.assertTrue(any("前綴" in e for e in errors))

    def test_scale_forms_and_zero(self):
        self.assertAlmostEqual(st.parse_number("1/100"), 0.01)
        self.assertAlmostEqual(st.parse_number("×0.01"), 0.01)
        self.assertAlmostEqual(st.parse_number("1e-2"), 0.01)
        _, errors, _ = st.convert(rows("名稱,位址,功能碼,型別,倍率\na,0,FC03,uint16,0\n"))
        self.assertTrue(any("不可為 0" in e for e in errors))

    def test_overlap_and_coil(self):
        _, errors, _ = st.convert(rows("名稱,位址,功能碼,型別\na,0,FC03,float32\nb,1,FC03,uint16\n"))
        self.assertTrue(any("重疊" in e for e in errors))
        _, errors, _ = st.convert(rows("名稱,位址,功能碼,型別\nc,0,FC01,uint16\n"))
        self.assertTrue(any("coil" in e for e in errors))

    def test_notes(self):
        _, _, notes = st.convert(rows("名稱,位址,功能碼,型別\na,0,FC03,float32\n"))
        self.assertTrue(any("字序" in n for n in notes))
        self.assertTrue(any("單位" in n for n in notes))

    def test_fullwidth_header(self):
        r = rows("名稱,位址,功能碼\nａ,０,ＦＣ０３\n")
        tags, errors, _ = st.convert(r)
        self.assertEqual(errors, [])
        self.assertEqual(tags["a"]["address"], 0)


class DecodeTests(unittest.TestCase):
    def test_example(self):
        data = dc.load(ROOT / "skills/modbus-unknown-device-discovery/examples/示範掃描結果.csv")
        out = {(r["fc"], r["address"]): r for r in dc.analyse(data)}
        self.assertEqual(out[(4, 0)]["changed"], "是")
        self.assertIn("uint16×0.1=25.3", out[(4, 0)]["candidates"])
        self.assertIn("float32[ABCD]@10-11", out[(4, 10)]["candidates"])
        self.assertIn("邊界值", out[(4, 21)]["reason"])
        self.assertTrue(all(r["status"] == "候選（未驗證）" for r in out.values()))

    def test_rejects_write_fc(self):
        p = Path(tempfile.mkdtemp()) / "w.csv"
        p.write_text("fc,address,sample1,sample2\n6,0,1,1\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            dc.load(p)

    def test_word_orders(self):
        self.assertEqual(dc.words_to_bytes(0x1234, 0x5678, "CDAB"), bytes([0x56, 0x78, 0x12, 0x34]))
        self.assertEqual(dc.words_to_bytes(0x1234, 0x5678, "BADC"), bytes([0x34, 0x12, 0x78, 0x56]))


if __name__ == "__main__":
    unittest.main()
