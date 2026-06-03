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


if __name__ == "__main__":
    unittest.main(verbosity=2)
