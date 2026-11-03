import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
CLI = SKILL / "scripts" / "grounded.py"


class GroundedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project.json"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                                capture_output=True, text=True, encoding="utf-8",
                                env={**os.environ, "PYTHONUTF8": "1"})
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result.stderr

    def init_and_import(self):
        self.run_cli("init", "--project", self.project, "--title", "自主研究")
        source = self.root / "访谈.txt"
        source.write_text("第一段：我检查资料来源。\n第二行还要核验。\n\n第二段：我有不同想法。", encoding="utf-8")
        self.run_cli("import-text", "--project", self.project, "--file", source, "--participant", "P01")
        return json.loads(self.project.read_text(encoding="utf-8"))

    def apply(self, ops, actor="model", *extra, ok=True):
        path = self.root / "ops.json"
        path.write_text(json.dumps({"ops": ops}, ensure_ascii=False), encoding="utf-8")
        return self.run_cli("apply", "--project", self.project, "--ops", path,
                            "--actor", actor, *extra, ok=ok)

    def test_import_trace_and_legacy_sample(self):
        p = self.init_and_import()
        self.assertEqual(len(p["evidence"]), 2)
        self.assertEqual(p["evidence"][0]["position"], "第 1 段，起始行 1")
        self.assertIn("第二行还要核验", p["evidence"][0]["text"])
        self.assertEqual(p["coverage"][p["evidence"][1]["id"]]["status"], "unread")
        sample = self.root / "sample.json"
        self.run_cli("sample", "--project", sample)
        self.assertTrue(self.run_cli("validate", "--project", sample)["valid"])

    def test_atomic_operations_and_human_confirmation(self):
        p = self.init_and_import()
        eid = p["evidence"][0]["id"]
        ops = [
            {"action": "upsert-category", "data": {"id": "K1", "name": "策略",
             "type": "范畴", "description": "行为", "properties": [], "evidenceIds": [eid]}},
            {"action": "upsert-code", "data": {"id": "C1", "name": "核验",
             "definition": "核验来源", "categoryId": "K1", "evidenceIds": [eid],
             "quote": "检查资料来源", "rationale": "贴近原文"}},
            {"action": "coverage", "id": eid, "data": {"status": "coded", "note": "已读"}}]
        self.apply(ops)
        before = self.project.read_bytes()
        error = self.apply([{"action": "set-code-status", "id": "C1",
                             "data": {"status": "confirmed"}}], ok=False)
        self.assertIn("用户明确核验", error)
        self.assertEqual(self.project.read_bytes(), before)
        self.apply([{"action": "set-code-status", "id": "C1", "data": {"status": "confirmed"}}],
                   "human", "--human-review")
        state = json.loads(self.project.read_text(encoding="utf-8"))
        self.assertEqual(state["codes"][0]["status"], "confirmed")
        bad = [{"action": "upsert-memo", "data": {"title": "第一条", "text": "有效"}},
               {"action": "upsert-code", "data": {"name": "伪造", "definition": "伪造",
                "evidenceIds": [eid], "quote": "这句话不在原文"}}]
        before = self.project.read_bytes()
        self.apply(bad, ok=False)
        self.assertEqual(self.project.read_bytes(), before)

    def test_backup_restore_and_export(self):
        p = self.init_and_import()
        eid = p["evidence"][0]["id"]
        self.apply([{"action": "upsert-code", "data": {"name": "=1+1", "definition": "<script>",
                     "evidenceIds": [eid], "quote": "检查资料来源", "rationale": "检查"}}])
        out = self.root / "deliverables"
        self.run_cli("export", "--project", self.project, "--out", out)
        with (out / "三级编码表.csv").open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertTrue(rows[1][1].startswith("\u200b="))
        report = (out / "研究分析报告.html").read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", report)
        self.assertNotIn("<script>", report)
        self.assertIn("flowchart LR", (out / "范畴关系图.mmd").read_text(encoding="utf-8"))
        restored = self.root / "restored.json"
        self.run_cli("restore", "--from", out / "项目备份.json", "--to", restored)
        self.assertEqual(json.loads(restored.read_text(encoding="utf-8")), json.loads(self.project.read_text(encoding="utf-8")))
        self.run_cli("restore", "--from", restored, "--to", restored, ok=False)
        self.run_cli("export", "--project", self.project, "--out", out, ok=False)

    def test_stale_hash_rejects_update(self):
        self.init_and_import()
        sha = self.run_cli("validate", "--project", self.project)["sha256"]
        self.apply([{"action": "upsert-memo", "data": {"title": "先保存", "text": "记录"}}])
        before = self.project.read_bytes()
        self.apply([{"action": "upsert-memo", "data": {"title": "过时", "text": "记录"}}],
                   "model", "--expected-sha256", sha, ok=False)
        self.assertEqual(self.project.read_bytes(), before)

    def test_windows_line_endings_and_exact_offsets(self):
        self.run_cli("init", "--project", self.project, "--title", "研究")
        source = self.root / "crlf.txt"
        raw = "首段\r\n第二行\r\n\r\n下一段"
        with source.open("w", encoding="utf-8", newline="") as f:
            f.write(raw)
        self.run_cli("import-text", "--project", self.project, "--file", source)
        p = json.loads(self.project.read_text(encoding="utf-8"))
        self.assertEqual(len(p["evidence"]), 2)
        self.assertEqual(p["sources"][0]["rawText"], raw)
        for e in p["evidence"]:
            self.assertEqual(raw[e["startChar"]:e["endChar"]], e["text"])
        self.assertEqual(p["evidence"][1]["position"], "第 2 段，起始行 4")

    def test_category_cycle_is_rejected_without_writing(self):
        self.init_and_import()
        self.apply([{"action": "upsert-category", "data": {"id": "A", "name": "A", "description": "A"}},
                    {"action": "upsert-category", "data": {"id": "B", "name": "B", "description": "B", "parentId": "A"}}])
        before = self.project.read_bytes()
        error = self.apply([{"action": "upsert-category", "id": "A", "data": {"parentId": "B"}}], ok=False)
        self.assertIn("循环", error)
        self.assertEqual(self.project.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
