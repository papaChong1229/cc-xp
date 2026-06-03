#!/usr/bin/env python3
"""xp-statusline.py 的單元測試（v0.1.1 行為）。

跑法：python3 test_xp_statusline.py
覆蓋兩個 v0.1.1 更新：
  1. 非破壞性包裝：wrapped_line1 執行原 statusLine、防遞迴、無設定回 None。
  2. 顯示：cc-xp 只輸出兩行（去掉 ctx/5hr/weekly）、xp 行括號數字自動換 K/M/B。
"""

import importlib.util
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location("xp_statusline",
                                               os.path.join(_HERE, "xp-statusline.py"))
xp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(xp)


def _state():
    return xp.new_state()


def _equipped():
    return dict(xp.DEFAULT_EQUIPPED)


class HumanizeTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(xp.humanize(999), "999")
        self.assertEqual(xp.humanize(1_000), "1K")
        self.assertEqual(xp.humanize(1_500), "1.5K")
        self.assertEqual(xp.humanize(1_200_000), "1.2M")
        self.assertEqual(xp.humanize(4_900_000_000), "4.9B")

    def test_no_trailing_zero(self):
        self.assertEqual(xp.humanize(2_000_000), "2M")


def _state_buff():
    """events 狀態：有靈力 + 霊格(参) + 一個生效中的 buff。"""
    import time
    st = xp.new_state()
    st["rei"] = 49
    st["rei_earned_total"] = 5200          # ≥5000 → 霊格 参
    st["active_buff"] = {"id": "reimyaku", "name": "霊脈活性", "icon": "🌀",
                         "mult": 1.2, "expires_at": time.time() + 27 * 60}
    return st


class RenderLinesTest(unittest.TestCase):
    def test_title_line_has_no_meta(self):
        # 標題行（第一條 cc-xp 行）：稱號/Lv/⬩ 在、ctx/5hr/weekly 不在。
        title = xp.render_xp_lines(5_000_000_000, _equipped(), False, _state())[0]
        self.assertIn("Lv.", title)
        self.assertIn("⬩", title)
        for token in ("ctx", "5hr", "weekly"):
            self.assertNotIn(token, title)

    def test_xp_line_humanized_units(self):
        # progress/span 為大數時，括號內應出現單位且不含原本的長逗號數字。
        xp_line = xp.render_xp_lines(5_000_000_000, _equipped(), False, _state())[1]
        inside = xp_line[xp_line.rindex("(") + 1: xp_line.rindex(")")]
        self.assertNotRegex(inside, r"\d,\d{3},\d{3}")
        self.assertRegex(inside, r"[KMB]")

    def test_events_off_two_lines_only(self):
        result = xp.render_xp_lines(123_456, _equipped(), False, _state())
        self.assertEqual(len(result), 2)

    def test_events_on_no_buff_two_lines(self):
        # events 開但無 buff → 仍兩行；靈力併在 xp 行，無獨立 buff 行。
        result = xp.render_xp_lines(5_000_000_000, _equipped(), True, _state())
        self.assertEqual(len(result), 2)
        self.assertIn("靈", result[1])

    def test_buff_on_its_own_line(self):
        # 有 buff → 三行；第三行是 buff，靈〔参〕併在 xp 行尾（A2）。
        result = xp.render_xp_lines(5_000_000_000, _equipped(), True, _state_buff())
        self.assertEqual(len(result), 3)
        self.assertIn("靈", result[1])
        self.assertIn("〔参〕", result[1])      # A2：霊格融進靈
        self.assertNotIn("霊脈活性", result[1])  # buff 不在 xp 行
        self.assertIn("霊脈活性", result[2])      # buff 自成一行
        self.assertIn("1.2x", result[2])


class WrappedLine1Test(unittest.TestCase):
    def test_no_config_returns_none(self):
        self.assertIsNone(xp.wrapped_line1("{}", {}))
        self.assertIsNone(xp.wrapped_line1("{}", {"wrapped_statusline": "notdict"}))

    def test_runs_command_and_captures_stdout(self):
        cfg = {"wrapped_statusline": {"type": "command", "command": "printf 'hello-orig'"}}
        self.assertEqual(xp.wrapped_line1("{}", cfg), "hello-orig")

    def test_recursion_guard(self):
        # 原指令若指向 cc-xp 自己 → 不執行，回 None（避免無限遞迴）。
        cfg = {"wrapped_statusline": {"command": 'python3 "/x/xp-statusline.py"'}}
        self.assertIsNone(xp.wrapped_line1("{}", cfg))

    def test_failing_command_returns_none(self):
        cfg = {"wrapped_statusline": {"command": "exit 3"}}
        self.assertIsNone(xp.wrapped_line1("{}", cfg))

    def test_empty_output_returns_none(self):
        cfg = {"wrapped_statusline": {"command": "true"}}
        self.assertIsNone(xp.wrapped_line1("{}", cfg))

    def test_stdin_passed_through(self):
        cfg = {"wrapped_statusline": {"command": "cat"}}
        self.assertEqual(xp.wrapped_line1("PIPED", cfg), "PIPED")

    def test_multiline_original_preserved(self):
        # 原本就是多行的 statusline → 內部換行原樣保留（append 後排版才正常）。
        cfg = {"wrapped_statusline": {"command": "printf 'A\\nB'"}}
        self.assertEqual(xp.wrapped_line1("{}", cfg), "A\nB")

    def test_trailing_newlines_stripped(self):
        # 結尾換行去掉，避免 join 後多出空行；但內部換行保留。
        cfg = {"wrapped_statusline": {"command": "printf 'A\\nB\\n\\n'"}}
        self.assertEqual(xp.wrapped_line1("{}", cfg), "A\nB")


def _proc(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


# ccusage daily --json 的最小可解析輸出（頂層 totals）。
_OK_JSON = json.dumps({"totals": {"totalTokens": 1234}})


class CcusageRunnersTest(unittest.TestCase):
    def test_orders_global_bun_npx(self):
        # 三種都在 → 依偏好排序：全域 > bun x > npx。
        def fake_which(name, path=None):
            return {"ccusage": "/g/ccusage", "bun": "/b/bun", "npx": "/n/npx"}.get(name)
        with mock.patch("shutil.which", side_effect=fake_which):
            runners = xp.ccusage_runners()
        self.assertEqual(runners,
                         [["/g/ccusage"], ["/b/bun", "x", "ccusage"], ["/n/npx", "--yes", "ccusage"]])

    def test_none_when_nothing_found(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(xp.ccusage_runners(), [])

    def test_only_bun(self):
        def fake_which(name, path=None):
            return "/b/bun" if name == "bun" else None
        with mock.patch("shutil.which", side_effect=fake_which):
            self.assertEqual(xp.ccusage_runners(), [["/b/bun", "x", "ccusage"]])


class FetchFallbackTest(unittest.TestCase):
    def setUp(self):
        # 隔離終生 ledger：fetch_lifetime_tokens 會更新它，避免讀到機器上真實
        # ~/.claude/statusline/xp-ledger.json 污染這裡的 1234 斷言。
        for p in (mock.patch.object(xp, "load_ledger", return_value=xp.new_ledger()),
                  mock.patch.object(xp, "save_ledger")):
            p.start()
            self.addCleanup(p.stop)

    def test_falls_through_to_second_runner_when_first_fails(self):
        # 核心回歸：全域 ccusage 被偵測到但執行失敗（rc!=0），仍退到 bun x 取到值。
        with mock.patch.object(xp, "ccusage_runners",
                               return_value=[["/g/ccusage"], ["/b/bun", "x", "ccusage"]]):
            def fake_run(cmd, **kw):
                return _proc(1, "") if cmd[0] == "/g/ccusage" else _proc(0, _OK_JSON)
            with mock.patch("subprocess.run", side_effect=fake_run):
                self.assertEqual(xp.fetch_lifetime_tokens(30), 1234)

    def test_flag_fallback_when_breakdown_rejected(self):
        # 舊版 ccusage：帶 --breakdown 失敗，plain daily --json 成功。
        with mock.patch.object(xp, "ccusage_runners", return_value=[["/g/ccusage"]]):
            def fake_run(cmd, **kw):
                return _proc(0, _OK_JSON) if "--breakdown" not in cmd else _proc(1, "")
            with mock.patch("subprocess.run", side_effect=fake_run):
                self.assertEqual(xp.fetch_lifetime_tokens(30), 1234)

    def test_none_when_no_runner(self):
        with mock.patch.object(xp, "ccusage_runners", return_value=[]):
            self.assertIsNone(xp.fetch_lifetime_tokens(30))

    def test_returns_none_when_all_fail(self):
        with mock.patch.object(xp, "ccusage_runners", return_value=[["/g/ccusage"]]):
            with mock.patch("subprocess.run", return_value=_proc(1, "")):
                self.assertIsNone(xp.fetch_lifetime_tokens(30))


class CcusageCheckTest(unittest.TestCase):
    def test_check_silent_when_runner_present(self):
        import io
        from contextlib import redirect_stdout
        with mock.patch.object(xp, "ccusage_runners", return_value=[["/g/ccusage"]]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                xp.cmd_ccusage_check()
            self.assertEqual(buf.getvalue().strip(), "")

    def test_check_hints_when_no_runner(self):
        import io
        from contextlib import redirect_stdout
        with mock.patch.object(xp, "ccusage_runners", return_value=[]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                xp.cmd_ccusage_check()
            self.assertIn("ccusage", buf.getvalue())


# ─────────────────────────── 終生 ledger（持久化）───────────────────────────

# ccusage daily --breakdown 真實形狀：日期鍵是 "period"，per-period modelBreakdowns
# （含非 claude，應被濾）。
_DAILY_BREAKDOWN = {
    "daily": [
        {"period": "2025-06-01", "modelBreakdowns": [
            {"modelName": "claude-opus-4", "inputTokens": 100, "outputTokens": 50,
             "cacheCreationTokens": 10, "cacheReadTokens": 40},
            {"modelName": "gpt-5", "inputTokens": 999, "outputTokens": 999,
             "cacheCreationTokens": 0, "cacheReadTokens": 0}]},
        {"period": "2025-06-02", "modelBreakdowns": [
            {"modelName": "claude-sonnet-4", "inputTokens": 200, "outputTokens": 100,
             "cacheCreationTokens": 0, "cacheReadTokens": 0}]},
    ]
}
# 舊版 ccusage 無 breakdown：只有 per-period totalTokens。
_DAILY_PLAIN = {"daily": [
    {"period": "2025-06-01", "totalTokens": 300},
    {"period": "2025-06-02", "totalTokens": 700}]}


class LedgerTest(unittest.TestCase):
    def test_new_ledger_empty(self):
        led = xp.new_ledger()
        self.assertEqual(xp.ledger_total(led), 0)
        self.assertEqual(led["days"], {})

    def test_total_sums_days(self):
        led = {"version": 1, "days": {"2025-06-01": 100, "2025-06-02": 250}}
        self.assertEqual(xp.ledger_total(led), 350)

    def test_total_ignores_nonnumeric(self):
        led = {"version": 1, "days": {"a": 100, "b": "x"}}
        self.assertEqual(xp.ledger_total(led), 100)

    def test_merge_adds_new_days(self):
        led = xp.new_ledger()
        xp.merge_daily_into_ledger(led, {"2025-06-01": 100, "2025-06-02": 200})
        self.assertEqual(xp.ledger_total(led), 300)

    def test_merge_grows_same_day(self):
        led = {"version": 1, "days": {"2025-06-02": 200}}
        xp.merge_daily_into_ledger(led, {"2025-06-02": 350})
        self.assertEqual(led["days"]["2025-06-02"], 350)

    def test_merge_keeps_larger_when_shrunk(self):
        # 半刪的天：ccusage 回更小值 → 不蓋掉已記錄大值（max 語意）。
        led = {"version": 1, "days": {"2025-06-02": 350}}
        xp.merge_daily_into_ledger(led, {"2025-06-02": 10})
        self.assertEqual(led["days"]["2025-06-02"], 350)


class LedgerIoTest(unittest.TestCase):
    def test_save_load_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(xp, "LEDGER_PATH", os.path.join(d, "xp-ledger.json")):
                led = {"version": 1, "days": {"2025-06-01": 123}}
                xp.save_ledger(led)
                self.assertEqual(xp.load_ledger(), led)

    def test_load_missing_returns_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(xp, "LEDGER_PATH", os.path.join(d, "nope.json")):
                self.assertEqual(xp.load_ledger(), xp.new_ledger())

    def test_load_corrupt_returns_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            with mock.patch.object(xp, "LEDGER_PATH", path):
                self.assertEqual(xp.load_ledger(), xp.new_ledger())


class ExtractDailyTest(unittest.TestCase):
    def test_claude_only_per_date(self):
        # 06-01: 100+50+10+40=200（gpt 濾掉）; 06-02: 200+100=300。
        self.assertEqual(xp._extract_daily_tokens(_DAILY_BREAKDOWN),
                         {"2025-06-01": 200, "2025-06-02": 300})

    def test_consistent_with_flat_total(self):
        # per-date 總和應等於 _extract_total_tokens（同 CLAUDE_ONLY 邏輯）。
        self.assertEqual(sum(xp._extract_daily_tokens(_DAILY_BREAKDOWN).values()),
                         xp._extract_total_tokens(_DAILY_BREAKDOWN))

    def test_fallback_to_totaltokens_when_no_breakdown(self):
        self.assertEqual(xp._extract_daily_tokens(_DAILY_PLAIN),
                         {"2025-06-01": 300, "2025-06-02": 700})

    def test_empty_when_no_rows(self):
        self.assertEqual(xp._extract_daily_tokens({"totals": {"totalTokens": 5}}), {})

    def test_back_compat_date_key(self):
        # 舊版若用 "date" 而非 "period" 仍要能解析。
        data = {"daily": [{"date": "2025-06-01", "totalTokens": 42}]}
        self.assertEqual(xp._extract_daily_tokens(data), {"2025-06-01": 42})

    def test_same_period_rows_take_max(self):
        # 同一 period 出現多列（agent 拆列）→ 取 max，不相加重複計。
        data = {"daily": [
            {"period": "2025-06-01", "modelBreakdowns": [
                {"modelName": "claude-a", "inputTokens": 300, "outputTokens": 0,
                 "cacheCreationTokens": 0, "cacheReadTokens": 0}]},
            {"period": "2025-06-01", "modelBreakdowns": [
                {"modelName": "claude-a", "inputTokens": 120, "outputTokens": 0,
                 "cacheCreationTokens": 0, "cacheReadTokens": 0}]}]}
        self.assertEqual(xp._extract_daily_tokens(data), {"2025-06-01": 300})


class FetchLedgerIntegrationTest(unittest.TestCase):
    """fetch_lifetime_tokens 端到端：更新 ledger 並回傳抗刪除的終生量。"""

    def _run_with(self, json_obj):
        def fake_run(cmd, **kw):
            return _proc(0, json.dumps(json_obj))
        with mock.patch.object(xp, "ccusage_runners", return_value=[["/g/ccusage"]]):
            with mock.patch("subprocess.run", side_effect=fake_run):
                return xp.fetch_lifetime_tokens(30)

    def test_durable_total_survives_transcript_deletion(self):
        # 核心回歸：舊 transcript 被刪、ccusage 縮水，終生量仍不退。
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(xp, "LEDGER_PATH", os.path.join(d, "xp-ledger.json")):
                self.assertEqual(self._run_with(_DAILY_BREAKDOWN), 500)
                shrunk = {"daily": [_DAILY_BREAKDOWN["daily"][1]]}  # 只剩 06-02（300）
                self.assertEqual(self._run_with(shrunk), 500)       # ledger 保 06-01

    def test_ledger_grows_when_today_increases(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(xp, "LEDGER_PATH", os.path.join(d, "xp-ledger.json")):
                self.assertEqual(self._run_with(_DAILY_BREAKDOWN), 500)
                grown = {"daily": [
                    _DAILY_BREAKDOWN["daily"][0],  # 06-01: 200
                    {"period": "2025-06-02", "modelBreakdowns": [
                        {"modelName": "claude-x", "inputTokens": 400, "outputTokens": 100,
                         "cacheCreationTokens": 0, "cacheReadTokens": 0}]}]}  # 06-02: 500
                self.assertEqual(self._run_with(grown), 700)

    def test_empty_ledger_falls_back_to_flat_total(self):
        # ccusage 只回頂層 totals（無 daily 列）→ ledger 不動 → 退回 flat。
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(xp, "LEDGER_PATH", os.path.join(d, "xp-ledger.json")):
                self.assertEqual(self._run_with({"totals": {"totalTokens": 1234}}), 1234)


if __name__ == "__main__":
    unittest.main(verbosity=2)
