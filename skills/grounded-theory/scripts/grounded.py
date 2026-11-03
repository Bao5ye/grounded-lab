#!/usr/bin/env python3
"""Local, deterministic project operations for the grounded-theory skill.

This script performs no model or network calls. Analysis is supplied by the host.
"""
import argparse
import copy
import csv
import datetime as dt
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

SCHEMA = "grounded-lab-v1"
ARRAYS = ("sources", "evidence", "codes", "categories", "relations", "sampling", "memos", "audit")
PROJECT_KEYS = ("title", "motivation", "question", "population", "unit", "boundary", "assumptions")
STATUS = ("pending", "confirmed", "rejected")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix):
    return prefix + "-" + str(uuid.uuid4())


def fail(message):
    raise ValueError(message)


def text(value):
    if not isinstance(value, str):
        fail("文本字段必须是字符串")
    return value


def nonempty(value, field):
    value = text(value).strip()
    if not value:
        fail(field + " 不能为空")
    return value


def project_new(title):
    return {"schema": SCHEMA, "project": dict(zip(PROJECT_KEYS, [title] + [""] * 6)),
            "intentConfirmed": False, **{k: [] for k in ARRAYS},
            "core": {"selected": "", "story": "", "alternatives": [], "confirmed": False},
            "mode": "manual", "coverage": {}}


def index(items, label):
    result = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            fail(label + " 中存在缺失 ID")
        if item["id"] in result:
            fail(label + " 中存在重复 ID：" + item["id"])
        result[item["id"]] = item
    return result


def validate(data):
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        fail("不是兼容的 grounded-lab-v1 项目")
    for key in ARRAYS:
        if not isinstance(data.get(key), list):
            fail("缺少数组：" + key)
    if not isinstance(data.get("project"), dict) or any(not isinstance(data["project"].get(k), str) for k in PROJECT_KEYS):
        fail("研究意图字段不完整")
    core = data.get("core")
    if (not isinstance(core, dict) or not isinstance(core.get("selected"), str)
            or not isinstance(core.get("story"), str) or not isinstance(core.get("alternatives"), list)
            or any(not isinstance(x, str) for x in core["alternatives"])
            or not isinstance(core.get("confirmed"), bool)):
        fail("核心范畴字段不完整")
    sources = index(data["sources"], "资料")
    evidence = index(data["evidence"], "证据")
    codes = index(data["codes"], "编码")
    categories = index(data["categories"], "范畴")
    index(data["relations"], "关系")
    index(data["sampling"], "抽样")
    index(data["memos"], "备忘")
    warnings = []
    for s in sources.values():
        if any(not isinstance(s.get(k), str) for k in ("name", "kind", "participant", "date", "role", "status")):
            fail("资料字段不完整：" + s["id"])
        if not isinstance(s.get("included"), bool) or not isinstance(s.get("demo"), bool):
            fail("资料状态不完整：" + s["id"])
    for e in evidence.values():
        if any(not isinstance(e.get(k), str) for k in ("sourceId", "text", "position", "speaker")):
            fail("证据字段不完整：" + e["id"])
        if e["sourceId"] not in sources:
            fail("证据来源不存在：" + e["id"])
    for c in codes.values():
        if any(not isinstance(c.get(k), str) for k in ("name", "definition", "categoryId", "quote", "rationale", "origin")):
            fail("编码字段不完整：" + c["id"])
        ids = c.get("evidenceIds")
        if not isinstance(ids, list) or any(x not in evidence for x in ids):
            fail("编码关联的证据不存在：" + c["id"])
        if c["categoryId"] and c["categoryId"] not in categories:
            fail("编码关联的范畴不存在：" + c["id"])
        if c.get("status") not in STATUS:
            fail("编码状态无效：" + c["id"])
        if not c["quote"] or not any(c["quote"] in evidence[x]["text"] for x in ids):
            warnings.append("引文未匹配关联证据：" + c["id"])
    for c in categories.values():
        if any(not isinstance(c.get(k), str) for k in ("name", "type", "description")):
            fail("范畴字段不完整：" + c["id"])
        if not isinstance(c.get("properties"), list) or any(not isinstance(x, str) for x in c["properties"]):
            fail("范畴属性无效：" + c["id"])
        check_evidence_ids(c.get("evidenceIds"), evidence, "范畴 " + c["id"])
        if c.get("parentId") and (c["parentId"] not in categories or c["parentId"] == c["id"]):
            fail("上级范畴无效：" + c["id"])
        seen = {c["id"]}
        parent = c.get("parentId", "")
        while parent:
            if parent in seen or parent not in categories:
                fail("范畴层级存在循环或无效上级：" + c["id"])
            seen.add(parent)
            parent = categories[parent].get("parentId", "")
    for r in data["relations"]:
        if r.get("from") not in categories or r.get("to") not in categories:
            fail("关系端点不存在：" + r["id"])
        if any(not isinstance(r.get(k), str) for k in ("label", "caution")):
            fail("关系字段不完整：" + r["id"])
        check_evidence_ids(r.get("evidenceIds"), evidence, "关系 " + r["id"])
        if not r["evidenceIds"]:
            warnings.append("关系缺少直接证据：" + r["id"])
    for m in data["memos"]:
        if any(not isinstance(m.get(k), str) for k in ("title", "type", "text", "evidenceId", "date")):
            fail("备忘字段不完整：" + m["id"])
        if m["evidenceId"] and m["evidenceId"] not in evidence:
            fail("备忘证据不存在：" + m["id"])
    for task in data["sampling"]:
        if any(not isinstance(task.get(k), str) for k in ("title", "reason", "question")) or not isinstance(task.get("done"), bool):
            fail("抽样任务字段不完整：" + task["id"])
    for a in data["audit"]:
        if any(not isinstance(a.get(k), str) for k in ("time", "action", "detail")):
            fail("操作记录字段不完整")
    if "evidenceIds" in core:
        check_evidence_ids(core["evidenceIds"], evidence, "核心范畴")
    coverage = data.get("coverage", {})
    if not isinstance(coverage, dict) or any(k not in evidence or not isinstance(v, dict)
        or v.get("status") not in ("coded", "read-uncoded", "unread")
        or not isinstance(v.get("note", ""), str) for k, v in coverage.items()):
        fail("资料覆盖记录无效")
    return warnings


def check_evidence_ids(ids, evidence, label):
    if not isinstance(ids, list) or any(not isinstance(x, str) or x not in evidence for x in ids):
        fail(label + " 关联的证据不存在")


def read_project(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate(data)
    return data


def atomic_write(path, data, create=False, expected=None):
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if create:
        with dest.open("x", encoding="utf-8", newline="\n") as f:
            f.write(serialized)
        return
    if expected and digest(dest) != expected:
        fail("项目已被更改；请重新读取后再操作")
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=dest.parent, delete=False) as f:
            name = f.name
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, dest)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(p, action, detail):
    p["audit"].append({"time": now(), "action": action, "detail": detail})


def reopen(p):
    p["core"]["confirmed"] = False


def split_text(raw):
    # Split on blank lines while retaining the exact characters of each excerpt.
    result = []
    delimiters = list(re.finditer(r"\r?\n[ \t]*\r?\n(?:[ \t]*\r?\n)*", raw))
    start = 0
    ranges = []
    for match in delimiters:
        ranges.append((start, match.start()))
        start = match.end()
    ranges.append((start, len(raw)))
    for start, stop in ranges:
        paragraph = raw[start:stop]
        while paragraph:
            piece = paragraph[:1400] if len(paragraph) > 1600 else paragraph
            result.append((piece, start, start + len(piece)))
            start += len(piece)
            paragraph = paragraph[len(piece):]
    return [(v, a, b) for v, a, b in result if v.strip()]


def import_source(p, file_path, participant, role, source_name=None):
    file_path = Path(file_path)
    if file_path.suffix.lower() not in (".txt", ".md", ".csv", ".tsv"):
        fail("仅支持 UTF-8 TXT、MD、CSV、TSV 文本；其他格式请先可靠提取文本")
    if file_path.stat().st_size > 3 * 1024 * 1024:
        fail("单份资料超过 3 MB")
    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        raw = f.read()
    pieces = split_text(raw)
    if not pieces:
        fail("资料为空")
    sid = new_id("S")
    s = {"id": sid, "name": source_name or file_path.name, "kind": "导入文本",
         "participant": participant, "date": dt.date.today().isoformat(), "demo": False,
         "included": True, "role": role, "status": "已解析", "rawText": raw,
         "sourceSha256": hashlib.sha256(file_path.read_bytes()).hexdigest()}
    p["sources"].append(s)
    for number, (piece, start, end) in enumerate(pieces, 1):
        eid = new_id("E")
        line = raw.count("\n", 0, start) + 1
        p["evidence"].append({"id": eid, "sourceId": sid, "position": "第 %d 段，起始行 %d" % (number, line),
                              "speaker": participant, "text": piece, "startChar": start, "endChar": end})
        p.setdefault("coverage", {})[eid] = {"status": "unread", "note": ""}
    reopen(p)
    audit(p, "导入文本", s["name"] + "；片段 " + str(len(pieces)))
    return sid


def fields(data, required, defaults=None):
    result = dict(defaults or {})
    for k in required:
        result[k] = nonempty(data.get(k, ""), k)
    return result


def ensure_new_id(items, candidate, prefix):
    ident = candidate or new_id(prefix)
    nonempty(ident, "ID")
    if any(x["id"] == ident for x in items):
        fail("ID 已存在：" + ident)
    return ident


def get_item(items, ident, kind):
    for item in items:
        if item["id"] == ident:
            return item
    fail(kind + "不存在：" + str(ident))


def human_only(actor, reviewed):
    if actor != "human" or not reviewed:
        fail("确认状态需要用户明确核验后使用 --actor human --human-review")


def apply_op(p, op, actor, reviewed):
    action = op.get("action")
    if not isinstance(action, str):
        fail("操作缺少 action")
    d = op.get("data", {})
    if not isinstance(d, dict):
        fail("操作 data 必须是对象")
    ident = op.get("id", "")
    evidence = index(p["evidence"], "证据")
    categories = index(p["categories"], "范畴")
    result = ident
    invalidate = False
    if action == "set-intent":
        for k in PROJECT_KEYS:
            if k in d:
                p["project"][k] = text(d[k])
        p["intentConfirmed"] = bool(d.get("confirmed", False))
        if p["intentConfirmed"]:
            human_only(actor, reviewed)
        invalidate = True
        result = p["project"]["title"]
    elif action == "source-policy":
        item = get_item(p["sources"], ident, "资料")
        if "included" in d:
            if not isinstance(d["included"], bool):
                fail("included 必须为布尔值")
            if d["included"] and item["status"] != "已解析":
                fail("资料尚未解析，不能纳入分析")
            item["included"] = d["included"]
        if "role" in d:
            item["role"] = nonempty(d["role"], "role")
        invalidate = True
    elif action == "upsert-code":
        old = get_item(p["codes"], ident, "编码") if ident else None
        val = dict(old or {})
        val.update({k: d[k] for k in ("name", "definition", "categoryId", "evidenceIds", "quote", "rationale") if k in d})
        for k in ("name", "definition", "quote"):
            nonempty(val.get(k, ""), k)
        val.setdefault("categoryId", "")
        val.setdefault("rationale", "")
        check_evidence_ids(val.get("evidenceIds"), evidence, "编码")
        if not val["evidenceIds"] or not any(val["quote"] in evidence[x]["text"] for x in val["evidenceIds"]):
            fail("编码引文必须逐字匹配关联原文")
        if val["categoryId"] and val["categoryId"] not in categories:
            fail("编码范畴不存在")
        val["origin"] = ("模型建议" if actor == "model" else "研究者编码")
        val["status"] = "pending"
        if old:
            old.update(val)
        else:
            val["id"] = ensure_new_id(p["codes"], d.get("id"), "C")
            p["codes"].append(val)
        result = val["id"]
        invalidate = True
    elif action == "set-code-status":
        item = get_item(p["codes"], ident, "编码")
        status = d.get("status")
        if status not in STATUS:
            fail("编码状态应为 pending、confirmed 或 rejected")
        if status in ("confirmed", "rejected"):
            human_only(actor, reviewed)
        if status == "confirmed" and not any(item["quote"] and item["quote"] in evidence[x]["text"] for x in item["evidenceIds"]):
            fail("引文未匹配，不能确认")
        item["status"] = status
        invalidate = True
    elif action == "upsert-category":
        old = get_item(p["categories"], ident, "范畴") if ident else None
        val = dict(old or {"type": "范畴", "properties": [], "evidenceIds": [], "parentId": ""})
        val.update({k: d[k] for k in ("name", "type", "description", "properties", "evidenceIds", "parentId") if k in d})
        for k in ("name", "type", "description"):
            nonempty(val.get(k, ""), k)
        if not isinstance(val["properties"], list) or any(not isinstance(x, str) for x in val["properties"]):
            fail("properties 应为文本数组")
        check_evidence_ids(val["evidenceIds"], evidence, "范畴")
        parent = val.get("parentId", "")
        if parent and (parent not in categories or parent == ident):
            fail("上级范畴无效")
        if old:
            old.update(val)
        else:
            val["id"] = ensure_new_id(p["categories"], d.get("id"), "K")
            p["categories"].append(val)
        result = val["id"]
        invalidate = True
    elif action == "upsert-relation":
        old = get_item(p["relations"], ident, "关系") if ident else None
        val = dict(old or {"caution": "", "evidenceIds": []})
        val.update({k: d[k] for k in ("from", "to", "label", "caution", "evidenceIds") if k in d})
        for k in ("from", "to", "label"):
            nonempty(val.get(k, ""), k)
        if val["from"] not in categories or val["to"] not in categories or val["from"] == val["to"]:
            fail("关系端点必须是两个不同的范畴")
        check_evidence_ids(val["evidenceIds"], evidence, "关系")
        if old:
            old.update(val)
        else:
            val["id"] = ensure_new_id(p["relations"], d.get("id"), "R")
            p["relations"].append(val)
        result = val["id"]
        invalidate = True
    elif action == "set-core":
        c = p["core"]
        for k in ("selected", "story"):
            if k in d:
                c[k] = text(d[k])
        if "alternatives" in d:
            if not isinstance(d["alternatives"], list) or any(not isinstance(x, str) for x in d["alternatives"]):
                fail("alternatives 应为文本数组")
            c["alternatives"] = d["alternatives"]
        if c["selected"] and c["selected"] not in c["alternatives"]:
            c["alternatives"].insert(0, c["selected"])
        if "evidenceIds" in d:
            check_evidence_ids(d["evidenceIds"], evidence, "核心范畴")
            c["evidenceIds"] = d["evidenceIds"]
        invalidate = True
        result = c["selected"]
    elif action == "confirm-core":
        human_only(actor, reviewed)
        nonempty(p["core"]["selected"], "核心范畴")
        p["core"]["confirmed"] = True
        result = p["core"]["selected"]
    elif action == "upsert-memo":
        old = get_item(p["memos"], ident, "备忘") if ident else None
        val = dict(old or {"type": "比较备忘录", "evidenceId": "", "date": dt.date.today().isoformat()})
        val.update({k: d[k] for k in ("title", "type", "text", "evidenceId", "date") if k in d})
        for k in ("title", "type", "text", "date"):
            nonempty(val.get(k, ""), k)
        if val["evidenceId"] and val["evidenceId"] not in evidence:
            fail("备忘证据不存在")
        if old:
            old.update(val)
        else:
            val["id"] = ensure_new_id(p["memos"], d.get("id"), "M")
            p["memos"].append(val)
        result = val["id"]
    elif action == "upsert-sampling":
        old = get_item(p["sampling"], ident, "抽样任务") if ident else None
        val = dict(old or {"done": False})
        val.update({k: d[k] for k in ("title", "reason", "question") if k in d})
        for k in ("title", "reason", "question"):
            nonempty(val.get(k, ""), k)
        if old:
            old.update(val)
        else:
            val["id"] = ensure_new_id(p["sampling"], d.get("id"), "T")
            p["sampling"].append(val)
        result = val["id"]
    elif action == "set-sampling-status":
        item = get_item(p["sampling"], ident, "抽样任务")
        if not isinstance(d.get("done"), bool):
            fail("done 必须为布尔值")
        item["done"] = d["done"]
    elif action == "coverage":
        if ident not in evidence or d.get("status") not in ("coded", "read-uncoded", "unread"):
            fail("覆盖状态或证据 ID 无效")
        p.setdefault("coverage", {})[ident] = {"status": d["status"], "note": text(d.get("note", ""))}
    elif action == "record-run":
        result = nonempty(d.get("detail", ""), "detail")
        if len(result) > 10000:
            fail("运行记录过长")
    else:
        fail("未知操作：" + action)
    if invalidate:
        reopen(p)
    audit(p, action, actor + " · " + str(result))
    return {"action": action, "id": result}


def csv_value(value):
    s = str(value if value is not None else "")
    return "\u200b" + s if re.match(r"^[\s]*[=+@-]", s) else s


def exports(p, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    targets = [out / "三级编码表.csv", out / "研究分析报告.html", out / "范畴关系图.mmd", out / "项目备份.json"]
    if any(x.exists() for x in targets):
        fail("导出文件已存在，请使用新的导出目录以免覆盖")
    validate(p)
    ev = index(p["evidence"], "证据")
    src = index(p["sources"], "资料")
    cats = index(p["categories"], "范畴")
    status_zh = {"pending": "待审核", "confirmed": "已确认", "rejected": "已搁置"}
    rows = [["编码ID", "概念", "定义", "子范畴", "范畴", "核心范畴候选", "核心范畴状态",
             "引文", "证据ID", "原始资料", "位置", "原始文本", "编码状态", "资料身份", "编码来源", "编码理由"]]
    for c in p["codes"]:
        for eid in c["evidenceIds"]:
            e = ev[eid]
            s = src[e["sourceId"]]
            cat = cats.get(c["categoryId"], {})
            parent = cats.get(cat.get("parentId"), {})
            rows.append([c["id"], c["name"], c["definition"], cat.get("name", "") if cat.get("type") == "子范畴" else "",
                         parent.get("name", "") or ("" if cat.get("type") == "子范畴" else cat.get("name", "")),
                         p["core"]["selected"], "已确认" if p["core"]["confirmed"] else "候选", c["quote"], eid,
                         s["name"], e["position"], e["text"], status_zh[c["status"]], "虚构示例" if s["demo"] else s["role"], c["origin"], c["rationale"]])
    with targets[0].open("x", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows([[csv_value(v) for v in row] for row in rows])
    esc = lambda x: html.escape(str(x))
    def section(title, items):
        return "<h2>" + esc(title) + "</h2>" + ("".join("<div class='item'>" + i + "</div>" for i in items) or "<p>无记录</p>")
    body = "<h1>" + esc(p["project"]["title"]) + "</h1><p>候选解释须由研究者复核；完成抽样任务不等于理论饱和。</p>"
    body += section("研究意图", ["<b>" + esc(k) + "</b>：" + esc(p["project"][k]) for k in PROJECT_KEYS])
    body += section("资料与证据", ["<b>" + esc(s["name"]) + "</b> · " + esc(s["role"]) + " · " +
        ("虚构示例" if s["demo"] else "用户资料") + " · " + ("纳入" if s["included"] else "排除") +
        "".join("<blockquote>" + esc(e["id"] + " · " + e["position"] + " · " + e["text"]) + "</blockquote>"
                for e in p["evidence"] if e["sourceId"] == s["id"]) for s in p["sources"]])
    body += section("概念与编码", ["<b>" + esc(c["name"]) + "</b> · " + status_zh[c["status"]] + " · " +
        esc(c["origin"]) + "<p>" + esc(c["definition"]) + "</p><blockquote>" + esc(c["quote"]) +
        "</blockquote><p>证据：" + esc("、".join(c["evidenceIds"])) + "；理由：" + esc(c["rationale"]) + "</p>" for c in p["codes"]])
    body += section("范畴", ["<b>" + esc(c["name"]) + "</b> · " + esc(c["type"]) + " · " + esc(c["description"]) +
        "<p>属性：" + esc("；".join(c["properties"])) + "；证据：" + esc("、".join(c["evidenceIds"])) + "</p>" for c in p["categories"]])
    body += section("关系、反例与替代解释", [esc(cats[r["from"]]["name"] + " → " + cats[r["to"]]["name"] + "：" + r["label"]) +
        "<p>证据：" + esc("、".join(r["evidenceIds"])) + "；限定及替代解释：" + esc(r["caution"]) + "</p>" for r in p["relations"]])
    body += section("候选核心范畴与故事线", [esc(p["core"]["selected"]) + " · " + ("已确认" if p["core"]["confirmed"] else "待确认") +
        "<p>" + esc(p["core"]["story"]) + "</p><p>候选：" + esc("、".join(p["core"]["alternatives"])) +
        "；证据：" + esc("、".join(p["core"].get("evidenceIds", []))) + "</p>"])
    body += section("抽样与备忘", [esc(t["title"] + "：" + t["reason"] + "；追问：" + t["question"] +
        (" · 已完成" if t["done"] else " · 待完成")) for t in p["sampling"]] +
        [esc(m["title"] + "：" + m["text"] + " · " + m["evidenceId"]) for m in p["memos"]])
    body += section("操作记录", [esc(a["time"] + " · " + a["action"] + " · " + a["detail"]) for a in p["audit"]])
    body += section("资料覆盖", [esc(e["id"] + " · " + p.get("coverage", {}).get(e["id"], {}).get("status", "unread") +
        " · " + p.get("coverage", {}).get(e["id"], {}).get("note", "")) for e in p["evidence"]])
    targets[1].write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>研究分析报告</title>"
                          "<style>body{max-width:960px;margin:3em auto;padding:1em;font:15px/1.8 sans-serif;color:#233d32}"
                          "blockquote{border-left:3px solid #9aaf86;padding-left:1em;white-space:pre-wrap}.item{border-bottom:1px solid #ddd}"
                          "p{white-space:pre-wrap}</style><body>" + body + "</body></html>", encoding="utf-8")
    graph = ["flowchart LR"]
    graph_ids = {c["id"]: "N" + str(i) for i, c in enumerate(p["categories"])}
    def graph_text(s):
        return html.escape(str(s), quote=True).replace("|", "&#124;").replace("\n", " ")
    if p["core"]["selected"]:
        graph.append('  CORE["核心范畴候选：%s"]' % graph_text(p["core"]["selected"]))
    for c in p["categories"]:
        graph.append('  %s["%s"]' % (graph_ids[c["id"]], graph_text(c["name"])))
    for r in p["relations"]:
        graph.append('  %s -->|"%s"| %s' % (graph_ids[r["from"]], graph_text(r["label"]), graph_ids[r["to"]]))
    targets[2].write_text("\n".join(graph) + "\n", encoding="utf-8")
    atomic_write(targets[3], p, create=True)
    return [str(x) for x in targets]


def cli():
    parser = argparse.ArgumentParser(description="程序化扎根理论本地项目工具；不调用模型或网络")
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="创建空白项目")
    init.add_argument("--project", required=True)
    init.add_argument("--title", required=True)
    sample = sub.add_parser("sample", help="创建虚构学习项目")
    sample.add_argument("--project", required=True)
    imp = sub.add_parser("import-text", help="导入纯文本")
    imp.add_argument("--project", required=True)
    imp.add_argument("--file", required=True)
    imp.add_argument("--participant", default="未标注")
    imp.add_argument("--role", default="研究资料")
    imp.add_argument("--name")
    apply = sub.add_parser("apply", help="应用结构化操作，整批校验后保存")
    apply.add_argument("--project", required=True)
    apply.add_argument("--ops", required=True)
    apply.add_argument("--actor", choices=("model", "human"), required=True)
    apply.add_argument("--human-review", action="store_true")
    apply.add_argument("--expected-sha256")
    for cmd in ("show", "validate"):
        p = sub.add_parser(cmd)
        p.add_argument("--project", required=True)
    exp = sub.add_parser("export", help="导出 CSV、HTML、关系图与 JSON")
    exp.add_argument("--project", required=True)
    exp.add_argument("--out", required=True)
    for cmd in ("backup", "restore"):
        p = sub.add_parser(cmd)
        p.add_argument("--from", dest="source", required=True)
        p.add_argument("--to", dest="destination", required=True)
    args = parser.parse_args()
    if args.cmd == "init":
        p = project_new(nonempty(args.title, "项目名称"))
        audit(p, "新建项目", p["project"]["title"])
        atomic_write(args.project, p, create=True)
        result = {"project": args.project}
    elif args.cmd == "sample":
        p = read_project(Path(__file__).resolve().parent.parent / "assets" / "example-project.json")
        atomic_write(args.project, p, create=True)
        result = {"project": args.project, "notice": "虚构示例，不可作为真实研究数据"}
    elif args.cmd == "import-text":
        p = read_project(args.project)
        source = import_source(p, args.file, args.participant, args.role, args.name)
        validate(p)
        atomic_write(args.project, p)
        result = {"sourceId": source, "segments": len([e for e in p["evidence"] if e["sourceId"] == source])}
    elif args.cmd == "apply":
        p = copy.deepcopy(read_project(args.project))
        ops = json.loads(Path(args.ops).read_text(encoding="utf-8-sig"))
        if not isinstance(ops, dict) or not isinstance(ops.get("ops"), list) or not ops["ops"]:
            fail("操作文件须为包含非空 ops 数组的 JSON 对象")
        result_ops = [apply_op(p, op, args.actor, args.human_review) for op in ops["ops"]]
        warnings = validate(p)
        atomic_write(args.project, p, expected=args.expected_sha256)
        result = {"applied": result_ops, "warnings": warnings, "sha256": digest(args.project)}
    elif args.cmd in ("show", "validate"):
        p = read_project(args.project)
        warnings = validate(p)
        result = p if args.cmd == "show" else {"valid": True, "warnings": warnings, "sha256": digest(args.project)}
    elif args.cmd == "export":
        p = read_project(args.project)
        result = {"files": exports(p, args.out), "warnings": validate(p)}
    else:
        p = read_project(args.source)
        atomic_write(args.destination, p, create=True)
        result = {"saved": args.destination, "warnings": validate(p)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        cli()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("错误：" + str(exc), file=sys.stderr)
        sys.exit(1)
