#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表单平面（form plane）：模板即唯一真相源，子进程只填空，账本由工具算。

设计要点
--------
1. 字段分三层所有权：
   * F 层（子进程填）——只描述世界：位置、触发、影响、预期、实测、命令、反假设、搜证范围、信心档。
   * D 层（本工具算）——id、极性/归属、命令执行记录、行号锚点、严重度映射、报告渲染、模板迁移。
   * J 层（仅主代理）——decision/severity/why/actions，走独立的 `decide` 子命令，需要持有 main token。
2. 「每次执行都要格式化」被换成「每次执行都被喂一个已经格式化好的壳」：`new --count N`
   直接产出 N 个槽位，键齐、枚举写成候选清单、每个待填处都是 `TODO:` 前缀。
3. 不变量只留 6 条机械可判定的（见 `check`），其余正确性由「生成即正确」承担；
   `fill` / `check` / `templates-check` 一律打印「检查了 N 项」，避免静默停跑。

依赖：Python 3.9+ 标准库。
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
BUG_TEMPLATE = "bug"
DECISION_TEMPLATE = "decision"
CHALLENGE_TEMPLATE = "challenge"
AUDIT_FILE = "audit.json"
DECISIONS_FILE = "decisions.json"
FORMS_DIR = "forms"
BRIEFS_DIR = "briefs"
DEFAULT_DIR = ".audit-forms"
TODO = "TODO"
MAX_REQUIRED_FIELDS = 12
PATHLINE_RE = re.compile(r"^(?:[A-Za-z]:)?[^:\s]+:\d+(?:-\d+)?$")
KNOWN_CHECKS = ("nonempty", "pathline", "enum", "command")
SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, None: 4}
TAIL_CHARS = 1200


# --------------------------------------------------------------------------- io


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(2)


def note(msg):
    print(msg)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        die("文件不存在：%s" % path)
    except json.JSONDecodeError as exc:
        die("%s 不是合法 JSON：%s" % (path, exc))


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_template(name):
    path = TEMPLATE_DIR / (name.replace("/", ".") + ".json")
    if not path.exists():
        die("未知模板 %s（找不到 %s）" % (name, path))
    tpl = load_json(path)
    if tpl.get("template") != name:
        die("模板文件自述名 %r 与请求名 %r 不一致" % (tpl.get("template"), name))
    return tpl


def audit_paths(dir_):
    d = Path(dir_)
    return {
        "dir": d,
        "audit": d / AUDIT_FILE,
        "decisions": d / DECISIONS_FILE,
        "forms": d / FORMS_DIR,
        "briefs": d / BRIEFS_DIR,
    }


def load_audit(dir_):
    p = audit_paths(dir_)
    if not p["audit"].exists():
        die("这里没有表单审计实例（缺 %s）。先跑：init --dir %s ..." % (p["audit"], dir_))
    return load_json(p["audit"])


def form_file(dir_, unit):
    return audit_paths(dir_)["forms"] / (unit + ".json")


def load_form(dir_, unit):
    path = form_file(dir_, unit)
    if not path.exists():
        die("缺少表单文件 %s（先跑：new --unit %s --count <你发现的缺陷数>）" % (path, unit))
    return load_json(path)


def has_slot(doc, index):
    # 槽位号在 slots[] 里是 int，而 evidence{} / anchors{} 的键是 str（JSON 对象键）。
    # 不做归一，"evidence 里有指向不存在槽位的记录"会把每一条正常记录都报成幽灵。
    wanted = str(index)
    return any(str(slot.get("slot")) == wanted for slot in doc.get("slots", []))


def find_slot(doc, index):
    for slot in doc.get("slots", []):
        if slot.get("slot") == index:
            return slot
    die("表单 %s 里没有槽位 %s" % (doc.get("unit"), index))


def ensure_arrays(doc):
    """表单 v2 的数据模型：证据按归属分三处——槽位证据、槽位变异、单元级证据。

    为什么单元级证据单独存在：`run` / `mutate` 记录的是「工具真的执行了什么」，
    而**执行不等于属于某条发现**。阳性对照、装置自检、跨文件的辅助实验都不属于任何
    单条发现；上一版把命令与槽位强制 1:1 绑定，逼得调查者建空槽当证据桶（并把决定性
    证据挂到了别的槽上）。这里给它们一个正当容器。
    """
    doc.setdefault("slots", [])
    doc.setdefault("evidence", {})
    doc.setdefault("mutations", {})
    doc.setdefault("anchors", {})
    doc.setdefault("unitEvidence", [])
    return doc


def at_key(record):
    return record.get("at") or ""


def slot_evidence(doc, slot):
    return doc.get("evidence", {}).get(str(slot), [])


def slot_mutations(doc, slot):
    return doc.get("mutations", {}).get(str(slot), [])


def slot_records(doc, slot):
    """一条槽位上的全部执行记录（证据 + 变异），按时间排序——不依赖数组顺序。"""
    return sorted(slot_evidence(doc, slot) + slot_mutations(doc, slot), key=at_key)


def tail(text, n=TAIL_CHARS):
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    return text if len(text) <= n else "…" + text[-n:]


# ---------------------------------------------------------------------- template


def blank_value(field):
    if field["required"]:
        if field.get("type") == "enum":
            return "%s: one of %s" % (TODO, "|".join(field["enum"]))
        return "%s: %s" % (TODO, field.get("prompt", field["key"]))
    return ""


def blank_slot(tpl, index):
    slot = {"slot": index}
    for field in tpl["fields"]:
        slot[field["key"]] = blank_value(field)
    return slot


# ------------------------------------------------------------------- validation


def field_problems(field, value):
    """返回该字段的机械问题列表；同时报告它检查了几项。"""
    problems = []
    checked = 1
    text = "" if value is None else str(value)
    stripped = text.strip()

    if field["required"] and not stripped:
        problems.append("必填字段 %s 为空" % field["key"])
    if TODO in text:
        problems.append("字段 %s 仍是 TODO 占位" % field["key"])
    if field.get("maxLength") and len(stripped) > field["maxLength"]:
        problems.append("字段 %s 超过 %d 字" % (field["key"], field["maxLength"]))

    kind = field.get("type")
    if kind == "enum" and stripped:
        if stripped not in field["enum"]:
            problems.append("字段 %s 取值 %r 不在允许集合 %s 内" % (field["key"], stripped, "|".join(field["enum"])))
    if field.get("check") == "pathline" and stripped:
        if not PATHLINE_RE.match(stripped):
            problems.append("字段 where 不是 path:line 或 path:a-b 形态：%r" % stripped)
    return problems, checked


def slot_problems(doc, slot, allow_static):
    tpl = load_template(BUG_TEMPLATE)
    problems = []
    checked = 0
    for field in tpl["fields"]:
        probs, n = field_problems(field, slot.get(field["key"]))
        problems += ["slot %s: %s" % (slot["slot"], p) for p in probs]
        checked += n

    evidence = slot_evidence(doc, slot["slot"])
    mutations = slot_mutations(doc, slot["slot"])
    latest_evidence = max(evidence, key=at_key) if evidence else None
    checked += 1
    if latest_evidence:
        # how 与「按时间最近的一条证据运行」比对——不能依赖数组顺序：主代理归约时会重排/搬运记录。
        if str(slot.get("how", "")).strip() != (latest_evidence.get("cmd") or ""):
            problems.append("slot %s: how 与最近一条证据运行不一致（工具应在 run 时写回）" % slot["slot"])
    elif mutations:
        # 只有变异记录：how 允许留空，或等于最近一条变异命令
        latest_mutation = max(mutations, key=at_key)
        how = str(slot.get("how", "")).strip()
        if how and how != (latest_mutation.get("cmd") or ""):
            problems.append("slot %s: how 既非空、也不等于最近一条变异记录的命令" % slot["slot"])
    else:
        confidence = str(slot.get("confidence", "")).strip()
        if allow_static and confidence == "Low":
            pass  # 显式降级：只有静态阅读，confidence 必须自认 Low
        elif allow_static:
            problems.append("slot %s: 无运行记录时 confidence 必须是 Low（实际 %r）" % (slot["slot"], confidence))
        else:
            problems.append(
                "slot %s: 缺少运行记录——用 run 子命令执行 how 里的命令；"
                "若确实只有静态阅读，显式加 --allow-static 且 confidence=Low" % slot["slot"]
            )
    # 变异记录的阳性对照纪律：unit 级至少要有一条「改坏了被捕获」的对照，否则判别力无从判断
    return problems, checked


def anchor_slot(audit, slot, problems):
    """--verify-paths：把 where 指向的那几行真的抓出来存成锚点，防止行号漂移。"""
    where = str(slot.get("where", "")).strip()
    checked = 0
    if not PATHLINE_RE.match(where):
        return [], checked
    path_part, _, line_part = where.rpartition(":")
    root = Path(audit["repoRoot"]).resolve()
    target = (root / path_part).resolve()
    checked += 1
    # 锚点会被写进审计工件，而 where 是子进程填的：一旦允许仓库外路径，填
    # `C:/Users/x/.ssh/id_rsa:1` 就能把任意文件内容抄进报告（实测可读 win.ini）。
    if not target.is_relative_to(root):
        problems.append("slot %s: where 必须指向仓库内的文件，不能越出 %s：%s"
                        % (slot["slot"], root, path_part))
        return [], checked
    if not target.exists():
        problems.append("slot %s: where 指向的文件不存在：%s" % (slot["slot"], path_part))
        return [], checked
    if not target.is_file():
        problems.append("slot %s: where 指向的不是文件：%s" % (slot["slot"], path_part))
        return [], checked
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        problems.append("slot %s: where 指向的文件读不出来（%s）：%s" % (slot["slot"], exc, path_part))
        return [], checked
    lines = text.split("\n")
    if "-" in line_part:
        first, last = line_part.split("-", 1)
    else:
        first = last = line_part
    try:
        first_i, last_i = int(first), int(last)
    except ValueError:
        problems.append("slot %s: 行号无法解析：%r" % (slot["slot"], line_part))
        return [], checked
    checked += 1
    if first_i < 1 or last_i > len(lines) or first_i > last_i:
        problems.append("slot %s: 行号 %s 超出文件范围（共 %d 行）" % (slot["slot"], line_part, len(lines)))
        return [], checked
    excerpt = "\n".join(lines[first_i - 1:last_i])[:400]
    return [{
        "where": where,
        "excerpt": excerpt,
        "fileSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "capturedAt": now(),
    }], checked


# ---------------------------------------------------------------------- commands


def cmd_init(args):
    p = audit_paths(args.dir)
    if p["audit"].exists() and not args.force:
        # 协议要求「首轮收口后再派漫游单元」——那时实例早就存在了。
        # 没有追加单元的路径，"派个漫游单元"就只能是句空话（照抄命令直接报错）。
        if args.add_unit:
            audit = load_json(p["audit"])
            units = audit.setdefault("units", [])
            added = [u for u in args.add_unit if u not in units]
            units.extend(added)
            save_json(p["audit"], audit)
            note("已追加 unit：%s（当前：%s）" % ("、".join(added) or "无新增（已存在）", "、".join(units)))
            note("下一步：brief --unit %s --task \"<它要回答什么>\"，然后派发。"
                 % (added[0] if added else units[-1]))
            return
        die("%s 已存在；要重建加 --force，要追加调查单元用 --add-unit <ID>" % p["audit"])
    token = secrets.token_hex(16)
    audit = {
        "formsVersion": 1,
        "profile": args.profile,
        "target": args.target or "(未填写 target)",
        "scope": args.scope or "(未填写 scope)",
        "snapshot": args.snapshot or "(未填写 snapshot)",
        "repoRoot": str(Path(args.repo_root).resolve()),
        "units": args.unit or [],
        "unitTasks": {},
        "createdAt": now(),
        "mainTokenSha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
    }
    save_json(p["audit"], audit)
    p["forms"].mkdir(parents=True, exist_ok=True)
    p["briefs"].mkdir(parents=True, exist_ok=True)
    save_json(p["decisions"], {"template": DECISION_TEMPLATE, "decisions": []})

    # 本地排除，不改任何被跟踪文件
    try:
        git_dir = subprocess.run(["git", "-C", audit["repoRoot"], "rev-parse", "--git-dir"],
                                 capture_output=True, text=True).stdout.strip()
        if git_dir:
            exclude = Path(git_dir) if Path(git_dir).is_absolute() else Path(audit["repoRoot"]) / git_dir
            exclude = exclude / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            entry = str(Path(args.dir).name) + "/"
            if entry not in existing:
                exclude.write_text(existing + ("\n" if existing and not existing.endswith("\n") else "")
                                   + "# form-plane audit workspace\n" + entry + "\n", encoding="utf-8")
                note("已把 %s 追加进 .git/info/exclude（仅本地生效）" % entry)
    except Exception as exc:  # noqa: BLE001 - 排除失败不该阻断初始化
        note("提示：未能写入 .git/info/exclude（%s），请自行忽略 %s" % (exc, args.dir))

    note("已初始化表单审计实例：%s" % p["dir"])
    note("  profile=%s  units=%s" % (audit["profile"], ",".join(audit["units"]) or "(未声明)"))
    note("")
    note("主代理 token（只显示这一次，decide 需要它；子进程不应拿到）：")
    note("  export AUDIT_MAIN_TOKEN=%s" % token)
    note("")
    note("下一步：brief --unit <R1> 生成任务书，然后派发；子进程用 new/run/mutate/fill。")


def cmd_brief(args):
    audit = load_audit(args.dir)
    tpl = load_template(BUG_TEMPLATE)
    # 任务描述只写一次，存在契约里：重渲染任务书不该把它弄丢，
    # 也不该逼主代理每次重新交代"这个单元到底要回答什么"。
    tasks = audit.setdefault("unitTasks", {})
    if args.task:
        tasks[args.unit] = args.task
        save_json(audit_paths(args.dir)["audit"], audit)
    task = tasks.get(args.unit)
    lines = []
    lines.append("# 缺陷表单任务书 · unit %s" % args.unit)
    lines.append("")
    lines.append("审计：%s" % audit["target"])
    lines.append("范围：%s" % audit["scope"])
    lines.append("快照：%s" % audit["snapshot"])
    lines.append("工作根：%s" % audit["repoRoot"])
    lines.append("表单目录：%s" % audit_paths(args.dir)["forms"])
    lines.append("")
    lines.append("## 你的任务")
    lines.append("## 你的任务")
    lines.append("")
    if task:
        lines.append(task)
    else:
        lines.append("**（未指定）** —— 主代理派这个单元时没写清它要回答什么。"
                     "补一句 `brief --unit %s --task \"<...>\"` 再派发；"
                     "一个不知道自己该回答什么的单元，产出一定是散的。" % args.unit)
    lines.append("")
    lines.append("## 你的权限边界")
    lines.append("")
    lines.append("- 你只能填 F 层字段（下面列出的那些）。id、极性、归属、严重度、裁决都不归你写。")
    lines.append("- `decide` 子命令对你无效：它需要 main token，任务书里没有、也不要去找。")
    lines.append("- 不要修改被审目标树的任何文件。判别性探针/复现脚本放 `%s/probes/%s/`，"
                 "一次性实验产物放 `%s/scratch/%s/`，收口前清空——被审树里不留任何东西。"
                 % (args.dir, args.unit, args.dir, args.unit))
    lines.append("")
    lines.append("## 你要填的字段（%d 个必填，全部键已在空壳里）" % len([f for f in tpl["fields"] if f["required"]]))
    lines.append("")
    for field in tpl["fields"]:
        marks = []
        marks.append("必填" if field["required"] else "可选")
        if field.get("enum"):
            marks.append("允许值 " + "|".join(field["enum"]))
        if field.get("maxLength"):
            marks.append("≤%d 字" % field["maxLength"])
        if field.get("check") == "command":
            marks.append("由 run 记录，手写不算")
        lines.append("- `%s`（%s）：%s" % (field["key"], "，".join(marks), field.get("prompt", "")))
        if field.get("reviewQuestion"):
            lines.append("    评审问题：%s" % field["reviewQuestion"])
    lines.append("")
    lines.append("## 操作顺序")
    lines.append("")
    lines.append("1. 你发现 N 条缺陷，就一次性建 N 个空槽（单文件、N 槽）：")
    lines.append("   `python -B %s --dir %s new --unit %s --count N`" % (Path(__file__).name, args.dir, args.unit))
    lines.append("2. 打开那份 JSON，把每个槽位里的 `TODO:` 逐格替换成你的观察（只改值，不要加键、不要动结构）。")
    lines.append("3. 每个槽位至少跑一条命令，让工具替你记录证据（退出码 + 输出尾部）：")
    lines.append("   `python -B %s --dir %s run --unit %s --slot <n> --cmd \"<命令>\"`" % (Path(__file__).name, args.dir, args.unit))
    lines.append("   预期非 0 退出（例如复现失败）时加 `--expect-exit <n>`，工具会判定是否按预期复现。")
    lines.append("   **调试不算证据**：探针可以先用 node/python 直接调通，但报告里引用的那一条结论，"
                 "必须用 `run` 再跑一次留痕——否则 fill 会报「缺少运行记录」，而你写好的探针全都要重跑。")
    lines.append("   命令含复杂引号时用 `-- <argv...>` 形式（不经 shell）。")
    lines.append("4. 不是某一条发现的运行（对照实验、装置自检、跨文件辅助实验）省略 `--slot`，"
                 "它会记成单元级证据——不要为它单开一个空槽：")
    lines.append("   `python -B %s --dir %s run --unit %s --cmd \"<命令>\" --purpose \"<这条在验证什么>\"`"
                 % (Path(__file__).name, args.dir, args.unit))
    lines.append("5. 想证明「这套检查真的抓得住这类坏」（判别力），用 mutate 改坏一处再跑检查：")
    lines.append("   `python -B %s --dir %s mutate --unit %s --slot <n> --file <相对路径> --from \"<锚点>\" --to \"<改坏>\" --cmd \"<检查命令>\"`"
                 % (Path(__file__).name, args.dir, args.unit))
    lines.append("   锚点必须恰好出现 1 次；工具改完会跑检查、再逐字节还原并校验哈希。"
                 "证明变异装置本身有效（这次变异**应该**被抓到）时加 `--control`。")
    lines.append("6. 自检，迭代到 0 problem：")
    lines.append("   `python -B %s --dir %s fill --unit %s --verify-paths`" % (Path(__file__).name, args.dir, args.unit))
    lines.append("   `--verify-paths` 会把 where 指向的那几行抓成锚点存下来（防行号漂移）。")
    lines.append("   确实只有静态阅读的槽位，必须 confidence=Low，并显式加 `--allow-static`。")
    lines.append("")
    lines.append("## 回报格式（≤250 字）")
    lines.append("")
    lines.append("表单路径、槽位数量、fill 的检查项数与 problem 数、每条槽位一句话摘要、"
                 "以及你没覆盖到的部分。不要复述整份 JSON。")
    text = "\n".join(lines) + "\n"

    out = Path(args.out) if args.out else (audit_paths(args.dir)["briefs"] / (args.unit + ".md"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if args.stdout:
        sys.stdout.write(text)
    note("已生成任务书：%s" % out)
    if not task:
        note("  提示：unit %s 还没有任务描述，任务书里是空任务块（brief --unit %s --task \"...\"）。"
             % (args.unit, args.unit))


def cmd_new(args):
    audit = load_audit(args.dir)
    tpl = load_template(BUG_TEMPLATE)
    path = form_file(args.dir, args.unit)
    if path.exists():
        doc = load_json(path)
        if doc.get("template") != BUG_TEMPLATE:
            die("%s 的模板是 %r，当前工具只认 %s" % (path, doc.get("template"), BUG_TEMPLATE))
    else:
        doc = ensure_arrays({"template": BUG_TEMPLATE, "unit": args.unit, "createdAt": now(),
                             "repoRoot": audit["repoRoot"]})

    have = len(doc["slots"])
    target = have + args.add if args.add else args.count
    if target < have:
        die("已有 %d 个槽位，--count %d 会删掉已填内容；要加就加，要删用 prune" % (have, target))
    created = 0
    for index in range(have + 1, target + 1):
        doc["slots"].append(blank_slot(tpl, index))
        created += 1
    save_json(path, doc)
    note("表单：%s（槽位 %d 个，本次新建 %d 个）" % (path, len(doc["slots"]), created))

    pending = []
    for slot in doc["slots"]:
        for field in tpl["fields"]:
            if TODO in str(slot.get(field["key"], "")):
                pending.append(field["key"])
    note("待填格子：%d 处" % len(pending))
    if created:
        note("提示：一个槽位 = 一条你要报告的东西（缺陷或负结果）；只替换 `TODO:` 后面的内容，不要增删键。")
        note("提示：对照实验、装置自检、跨文件的辅助证据**不要**另建槽位——用 `run` / `mutate` 不填 --slot 记到单元级证据里。")


def claim_snapshot(slot):
    """记录证据那一刻，这个槽位在主张什么。

    槽位号会在收敛（删空槽）或改写主张后漂移，而证据是按槽位号挂的——
    一次真实审计里调查者把 14 槽砍到 10 槽，随后批量补记证据整体错位一位，
    每条结论的证据都成了别人的，而 fill 全绿。记下当时的主张，check 就能对出来。
    槽位还没填（title 还是 TODO）时不记，免得填完之后误报。
    """
    if slot is None:
        return None
    title = str(slot.get("title") or "")
    return None if (not title or title.startswith(TODO)) else title


def cmd_run(args):
    audit = load_audit(args.dir)
    path = form_file(args.dir, args.unit)
    doc = ensure_arrays(load_json(path))
    slot = find_slot(doc, args.slot) if args.slot is not None else None

    if args.argv and args.cmd:
        # 两条形式混用不会报用法错，而会把尾巴当 argv 去**真的执行**（盲测里跑出过
        # OSError: [WinError 193] 加一段 traceback，且什么都没记下来）。宁可拒绝。
        die("--cmd 与尾随位置参数不能同时给：--cmd 是经 shell 执行的整条命令，"
            "`-- <argv...>` 是不经 shell 的 argv。二选一（含复杂引号用后者）。")
    if args.argv:
        cmd_text = " ".join(args.argv)
        use_shell = False
        argv = args.argv
    elif args.cmd:
        cmd_text = args.cmd
        use_shell = True
        argv = None
    else:
        die('需要 --cmd "<命令>"，或 -- <argv...>（后者不经 shell，适合含引号的命令）')

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    started = time.time()
    exit_code, out, err = None, "", ""
    try:
        if use_shell:
            proc = subprocess.run(cmd_text, shell=True, cwd=audit["repoRoot"], env=env,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=args.timeout)
        else:
            proc = subprocess.run(argv, cwd=audit["repoRoot"], env=env,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=args.timeout)
        exit_code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        err = "timeout after %ss" % args.timeout
    except FileNotFoundError as exc:
        err = "command not found: %s" % exc

    record = {
        "cmd": cmd_text,
        "shell": use_shell,
        "exit": exit_code,
        "expectedExit": args.expect_exit,
        "matched": exit_code == args.expect_exit,
        "cwd": audit["repoRoot"],
        "durationMs": int((time.time() - started) * 1000),
        "stdoutTail": tail(out),
        "stderrTail": tail(err),
        "purpose": args.purpose or "",
        "slotTitle": claim_snapshot(slot),
        "at": now(),
    }
    if slot is None:
        doc["unitEvidence"].append(record)
        where = "单元级证据（不属于任何槽位）"
        count = len(doc["unitEvidence"])
    else:
        doc["evidence"].setdefault(str(args.slot), []).append(record)
        slot["how"] = cmd_text
        where = "槽位 %s" % args.slot
        count = len(doc["evidence"][str(args.slot)])
    save_json(path, doc)

    note("记录%s的第 %d 次运行：exit=%s（期望 %s）→ %s"
         % (where, count, exit_code, args.expect_exit,
            "按预期" if record["matched"] else "与期望不符"))
    if record["stdoutTail"]:
        note("--- stdout 尾部 ---")
        note(record["stdoutTail"])
    if record["stderrTail"]:
        note("--- stderr 尾部 ---")
        note(record["stderrTail"])
    if not record["matched"]:
        note("注意：与 --expect-exit 不符。若这是刻意的（例如复现退出码 3 的故障），"
             "把 --expect-exit 设成该值重跑，让记录本身可判读。")


def cmd_fill(args):
    audit = load_audit(args.dir)
    units = [args.unit] if args.unit else list(audit.get("units") or [])
    if not units:
        units = sorted(p.stem for p in audit_paths(args.dir)["forms"].glob("*.json"))
    if not units:
        die("没有可校验的表单：既没声明 unit，forms/ 下也没有文件")

    problems = []
    checked = 0
    slots_total = 0
    for unit in units:
        path = form_file(args.dir, unit)
        if not path.exists():
            problems.append("%s: 缺表单文件（先跑 new --unit %s --count N）" % (unit, unit))
            continue
        doc = ensure_arrays(load_json(path))
        if doc.get("template") != BUG_TEMPLATE:
            problems.append("%s: 模板 %r 不是 %s（用 migrate 升级）" % (unit, doc.get("template"), BUG_TEMPLATE))
            continue
        if not doc.get("slots"):
            problems.append("%s: 表单里 0 个槽位" % unit)
        for slot in doc["slots"]:
            slots_total += 1
            probs, n = slot_problems(doc, slot, args.allow_static)
            checked += n
            if args.verify_paths:
                anchors, n2 = anchor_slot(audit, slot, probs)
                checked += n2
                if anchors:
                    doc.setdefault("anchors", {})[str(slot["slot"])] = anchors
            problems += ["%s %s" % (unit, p) for p in probs]
        save_json(path, doc)

    note("fill：检查了 %d 项，覆盖 %d 个槽位；%d 个问题" % (checked, slots_total, len(problems)))
    for problem in problems:
        note("  - " + problem)
    if problems:
        note("按上面逐条改；改完重跑 fill，直到 0 个问题。")
        sys.exit(1)
    note("OK：所有槽位字段齐备、枚举合法、证据已由 run/mutate 记录。")


def recorded_challenges(dir_):
    path = audit_paths(dir_)["dir"] / "challenges.json"
    if not path.exists():
        return {}
    records = load_json(path)
    return {(c["unit"], c["slot"]): c.get("verdict") for c in records.get("challenges", [])}


def require_main_token(audit, provided):
    token = provided or os.environ.get("AUDIT_MAIN_TOKEN", "")
    if not token:
        die("decide 属于 J 层，需要 main token：--token <值> 或 export AUDIT_MAIN_TOKEN=...\n"
            "    子进程拿不到该 token；若你是子进程，请把线索写进槽位的 counter/checked/notes，由主代理裁决。")
    if hashlib.sha256(token.encode("utf-8")).hexdigest() != audit.get("mainTokenSha256"):
        die("main token 不匹配：decide 被拒绝（J 层只由主代理执行）")


def cmd_decide(args):
    audit = load_audit(args.dir)
    require_main_token(audit, args.token)
    tpl = load_template(DECISION_TEMPLATE)
    legal = {f["key"]: f for f in tpl["fields"]}

    if args.decision not in legal["decision"]["enum"]:
        die("decision 取值必须是 %s" % "|".join(legal["decision"]["enum"]))
    if args.severity and args.severity not in legal["severity"]["enum"]:
        die("severity 取值必须是 %s" % "|".join(legal["severity"]["enum"]))
    if not args.why or TODO in args.why:
        die("必须给 --why：这条结论依据哪几条记录、为什么是这个结论")

    doc = ensure_arrays(load_form(args.dir, args.unit))
    slot = find_slot(doc, args.slot)
    evidence = slot_evidence(doc, args.slot)
    kind = str(slot.get("kind", "")).strip()

    # 结论类型必须与槽位类型一致：verification 记录的是负结果，defect 才是缺陷。
    if kind == "verification" and args.decision != "VERIFIED":
        die("该槽位的 kind=verification（负结果），decision 只能是 VERIFIED；"
            "若它其实是一条缺陷，先把槽位的 kind 改成 defect。")
    if kind == "defect" and args.decision == "VERIFIED":
        die("该槽位的 kind=defect，decision 不能是 VERIFIED；"
            "若这是「实测某行为是好的」的负结果，先把槽位的 kind 改成 verification。")

    # 评级规则：缺陷类结论必填 severity；REJECTED 与 VERIFIED 禁止评级。
    if args.decision in ("CONFIRMED", "CONDITIONAL", "NEEDS-DECISION") and not args.severity:
        die("%s 必须给 --severity（Critical|High|Medium|Low）" % args.decision)
    if args.decision in ("REJECTED", "VERIFIED") and args.severity:
        die("%s 是「不成立」或「负结果」，不得评级；把理由写进 --why" % args.decision)

    # 结论不得强于证据（机械可判定的部分）
    if args.decision in ("CONFIRMED", "VERIFIED") and not evidence:
        die("%s 需要至少一条由 run 记录的可执行证据；该槽位目前 0 条。"
            "先 run，或把 decision 改成 CONDITIONAL/REJECTED 并在 --why 里写明缺口。" % args.decision)
    if args.decision == "CONFIRMED" and args.severity in ("Critical", "High"):
        if not any(r.get("matched") for r in evidence):
            die("Critical/High 的 CONFIRMED 要求至少一条按预期成功复现的运行记录"
                "（run --expect-exit <实际值>）。当前没有。")
        if not args.allow_unchallenged and (args.unit, args.slot) not in recorded_challenges(args.dir):
            die("Critical/High 的 CONFIRMED 要求先做一次盲化对抗复核并登记结果：\n"
                "      challenge --unit %s --slot %s          # 生成只含结论与复现配方的盲化任务书\n"
                "      challenge --unit %s --slot %s --verdict <target-stands|target-weakened|target-refuted|unresolved> --job <执行者>\n"
                "    理由：这类结论最可能由同一盲区复制一遍。确有理由跳过时用 --allow-unchallenged，并在 --why 里写明。"
                % (args.unit, args.slot, args.unit, args.slot))
    if args.decision == "REJECTED" and not evidence and not args.allow_static:
        die("REJECTED 需要能说明「为什么它不成立」的证据：默认要求至少一条运行记录，"
            "或显式 --allow-static（表示结论只基于静态阅读）。")

    # 严重度偏离调查者提示时必须单独说明——防止「谁改了级别、为什么」被埋在 why 里。
    hint = str(slot.get("severityHint", "")).strip()
    if args.severity and hint and args.severity != hint and not (args.severity_because or "").strip():
        die("你把严重度从调查者提示的 %s 改成了 %s，必须用 --severity-because 说明依据"
            "（impact × likelihood × reachability × recoverability 四维怎么算的）。" % (hint, args.severity))

    entries = load_json(audit_paths(args.dir)["decisions"])
    previous = [d for d in entries["decisions"]
                if d.get("unit") == args.unit and d.get("slot") == args.slot]
    if previous and not args.revise:
        old = previous[-1]
        die("该槽位已有裁决：%s / %s（%s）。裁决是门禁结论，覆盖必须显式——"
            "要改写就加 --revise（旧条目会进 history 留痕）。"
            % (old.get("decision"), old.get("severity") or "未定级", str(old.get("why"))[:60]))
    if previous:
        history = entries.setdefault("history", [])
        history.extend(previous)
        note("已把 %d 条旧裁决移入 history 留痕" % len(previous))
    entries["decisions"] = [d for d in entries["decisions"]
                            if not (d.get("unit") == args.unit and d.get("slot") == args.slot)]
    entries["decisions"].append({
        "unit": args.unit,
        "slot": args.slot,
        "kind": kind,
        "title": slot.get("title"),
        "decision": args.decision,
        "severity": args.severity,
        "severityHint": hint or None,
        "severityBecause": args.severity_because or "",
        "why": args.why,
        "flipQuestion": args.flip_question or "",
        "actions": args.actions or "",
        "evidenceRuns": len(evidence),
        "mutations": len(slot_mutations(doc, args.slot)),
        "decidedAt": now(),
    })
    entries["template"] = DECISION_TEMPLATE
    save_json(audit_paths(args.dir)["decisions"], entries)
    note("已裁决 %s slot %s：%s / %s" % (args.unit, args.slot, args.decision, args.severity or "(未定级)"))


def cmd_check(args):
    audit = load_audit(args.dir)
    problems = []
    checked = 0

    known = {BUG_TEMPLATE, DECISION_TEMPLATE}
    checked += 1
    for unit in (audit.get("units") or []):
        path = form_file(args.dir, unit)
        checked += 1
        if not path.exists():
            problems.append("unit %s 声明了但缺表单文件" % unit)

    form_docs = {}
    for path in sorted(audit_paths(args.dir)["forms"].glob("*.json")):
        doc = ensure_arrays(load_json(path))
        unit = doc.get("unit") or path.stem
        form_docs[unit] = doc
        checked += 1
        if doc.get("template") not in known:
            problems.append("%s 的模板 %r 不是已知版本" % (path.name, doc.get("template")))
        for slot in doc.get("slots", []):
            checked += 1
            for field in load_template(BUG_TEMPLATE)["fields"]:
                if TODO in str(slot.get(field["key"], "")):
                    problems.append("%s slot %s 的 %s 仍是 TODO" % (unit, slot["slot"], field["key"]))
        # 单元级证据必须真的执行过东西，且阳性对照失败要显式可见
        for entry in doc.get("unitEvidence", []):
            checked += 1
            if not str(entry.get("cmd", "")).strip():
                problems.append("%s 单元级证据有一条没有命令记录" % unit)
            if entry.get("control") and entry.get("testCaughtMutation") is False:
                problems.append("%s 的阳性对照失败（改坏了却没被捕获）：`%s`"
                                % (unit, str(entry.get("cmd"))[:60]))
        # 槽位级变异同样要查：一条"本该被抓住却没被抓住"的阳性对照留在槽位里，
        # 轻则读的人以为装置有效，重则整条判据的判别力是假的（盲化复核真抓到过这种）。
        for slot_no, mutations in (doc.get("mutations") or {}).items():
            for mut in mutations:
                checked += 1
                if mut.get("control") and mut.get("testCaughtMutation") is False:
                    problems.append("%s slot %s 的阳性对照失败（改坏了却没被捕获）：`%s`"
                                    % (unit, slot_no, str(mut.get("cmd"))[:60]))

    decisions = load_json(audit_paths(args.dir)["decisions"])
    seen = set()
    for entry in decisions.get("decisions", []):
        checked += 1
        if "unit" not in entry or "slot" not in entry:
            problems.append("裁决条目缺少 unit/slot 键，无法定位：%s" % json.dumps(entry, ensure_ascii=False)[:80])
            continue
        key = (entry["unit"], entry["slot"])
        if key in seen:
            problems.append("重复裁决：%s slot %s" % key)
        seen.add(key)
        if entry["unit"] not in form_docs:
            problems.append("裁决指向不存在的表单：%s" % entry["unit"])
            continue
        if not has_slot(form_docs[entry["unit"]], entry["slot"]):
            problems.append("裁决指向不存在的槽位：%s slot %s" % key)

    for unit, doc in form_docs.items():
        for slot in doc.get("slots", []):
            checked += 1
            if (unit, slot["slot"]) not in seen:
                problems.append("未裁决：%s slot %s（%s）" % (unit, slot["slot"], str(slot.get("title"))[:60]))
        # 幽灵桶：证据挂在根本不存在的槽位上，报告里看不见它，check 却一声不响。
        for bucket in ("evidence", "mutations", "anchors"):
            for key in (doc.get(bucket) or {}):
                checked += 1
                if not has_slot(doc, key):
                    problems.append("%s 的 %s 里有指向不存在槽位的记录：slot %s"
                                    % (unit, bucket, key))

    for entry in decisions.get("decisions", []):
        if "unit" not in entry or "slot" not in entry:
            continue                      # 上面已经记成问题，这里不再二次崩
        unit, slot_no = entry["unit"], entry["slot"]
        doc = form_docs.get(unit, {})
        evidence = slot_evidence(doc, slot_no)
        decision = entry["decision"]
        # kind 以**当前槽位**为准（裁决条目里那份是裁决时的快照）；两者不一致本身就是漂移。
        target_slot = find_slot(doc, slot_no) if has_slot(doc, slot_no) else None
        kind = str((target_slot or {}).get("kind") or "").strip()
        recorded_kind = str(entry.get("kind") or "").strip()
        checked += 1
        if recorded_kind and kind and recorded_kind != kind:
            problems.append("槽位 kind 与裁决时记录的不一致（裁决时 %s，现在 %s）：%s slot %s"
                            % (recorded_kind, kind, unit, slot_no))

        checked += 1
        if decision in ("CONFIRMED", "VERIFIED") and not evidence:
            problems.append("%s 但没有运行记录：%s slot %s" % (decision, unit, slot_no))
        checked += 1
        if kind == "verification" and decision != "VERIFIED":
            problems.append("kind=verification 的槽位裁决不是 VERIFIED：%s slot %s" % (unit, slot_no))
        checked += 1
        if kind == "defect" and decision == "VERIFIED":
            problems.append("kind=defect 的槽位裁决成了 VERIFIED：%s slot %s" % (unit, slot_no))
        checked += 1
        if decision in ("REJECTED", "VERIFIED") and entry.get("severity"):
            problems.append("%s 不该带 severity：%s slot %s" % (decision, unit, slot_no))
        checked += 1
        if entry.get("severity") and entry.get("severityHint") \
                and entry["severity"] != entry["severityHint"] \
                and not str(entry.get("severityBecause") or "").strip():
            problems.append("严重度偏离提示值（%s→%s）但没有 severityBecause：%s slot %s"
                            % (entry["severityHint"], entry["severity"], unit, slot_no))
        if decision == "CONFIRMED" and entry.get("severity") in ("Critical", "High"):
            checked += 1
            if not any(r.get("matched") for r in evidence):
                problems.append("High/Critical 的 CONFIRMED 缺按预期复现的记录：%s slot %s" % (unit, slot_no))
            checked += 1
            if (unit, slot_no) not in recorded_challenges(args.dir):
                problems.append("High/Critical 的 CONFIRMED 缺盲化对抗复核记录：%s slot %s "
                                "（用 challenge 生成任务书并登记 verdict）" % (unit, slot_no))

    note("check：检查了 %d 项；%d 个问题" % (checked, len(problems)))
    for problem in problems:
        note("  - " + problem)

    # 提示（不影响判定）：同一命令被挂在多个槽位，是"槽位 ↔ 证据错配"的典型征兆——
    # 一次真实审计里，调查者把 7 个探针整体挂错了一位，fill 全绿而每条结论的证据都是别人的。
    # 工具判不了"这条证据是否支撑那条主张"，但能把这个征兆摆出来给人看。
    for unit, doc in sorted(form_docs.items()):
        owners = {}
        for slot_no, recs in (doc.get("evidence") or {}).items():
            for rec in recs:
                owners.setdefault(rec.get("cmd"), []).append(slot_no)
        for cmd_text, slots in owners.items():
            distinct = sorted(set(slots))
            if len(distinct) > 1:            # 同一槽里跑两次同一条命令不算错配
                note("  提示：同一命令挂在 %d 个槽位（%s %s）——确认每条主张真的由它支撑；"
                     "只作对照的一次性运行应记到单元级证据。"
                     % (len(distinct), unit, "/".join(distinct)))
    sys.exit(1 if problems else 0)


def cmd_note(args):
    """记录过程披露 / 残留不确定性——报告末尾两节由它渲染，避免这两块只存在于对话里。"""
    audit = load_audit(args.dir)
    entries = audit.setdefault("notes", {"disclosure": [], "residual": []})
    entries.setdefault(args.kind, []).append({"text": args.text, "at": now()})
    # 这里曾经直接 write_text：写一半被杀会把 audit.json 截成 0 字节，整个实例不可读（实测）。
    save_json(audit_paths(args.dir)["audit"], audit)
    note("已记录 %s（累计 %d 条）：%s" % (args.kind, len(entries[args.kind]), args.text[:70]))


def decision_label(key):
    """把 summary 里的「DECISION/SEVERITY」键渲染成人能读的标签，避免出现 'None'。"""
    if key == "未裁决":
        return "未裁决"
    decision, _, severity = key.partition("/")
    if decision == "REJECTED":
        return "已排除（怀疑被推翻）"
    if decision == "VERIFIED":
        return "已核实为安全 / 按设计"
    if not severity or severity == "-":
        return "%s（未定级）" % decision
    return "%s/%s" % (decision, severity)


def audit_verdict(rows):
    """从裁决机械算出结论行——重型平面被删掉后，这是唯一被保留的「门禁」能力。

    判定不看 Prose：只看未闭合的缺陷级结论的严重度，以及未裁决数量。
    """
    open_high = [r for r in rows if r[2] and r[2]["decision"] in ("CONFIRMED", "CONDITIONAL", "NEEDS-DECISION")
                 and r[2].get("severity") in ("Critical", "High")]
    open_medium = [r for r in rows if r[2] and r[2]["decision"] in ("CONFIRMED", "CONDITIONAL", "NEEDS-DECISION")
                   and r[2].get("severity") == "Medium"]
    undecided = [r for r in rows if r[2] is None]
    if undecided:
        return ("INCOMPLETE", "仍有 %d 个槽位未裁决，本报告不构成结论" % len(undecided))
    if open_high:
        return ("BLOCKED", "存在 %d 条 Critical/High 级未闭合缺陷 ⇒ 不具备发布/合并条件" % len(open_high))
    if open_medium:
        return ("READY-WITH-CONDITIONS", "无 High 以上未闭合项，但有 %d 条 Medium 待处置" % len(open_medium))
    return ("READY", "无 Medium 以上未闭合项")


def cmd_report(args):
    audit = load_audit(args.dir)
    decisions = load_json(audit_paths(args.dir)["decisions"]).get("decisions", [])
    indexed = {(d["unit"], d["slot"]): d for d in decisions}

    # 没收口就出报告 = 把半成品当交付物。盲测里出现过一个 5 槽全 TODO、check 报 5 个问题的实例
    # 照样渲染出报告，读的人看不出它根本没审完。要出半成品就显式 --force，报告里会带着未填/未裁决标记。
    forms_dir = audit_paths(args.dir)["forms"]
    todo_slots, undecided = [], []
    for path in sorted(forms_dir.glob("*.json")):
        doc = ensure_arrays(load_json(path))
        unit = doc.get("unit") or path.stem
        for slot in doc.get("slots", []):
            label = "%s slot %s" % (unit, slot["slot"])
            if any(TODO in str(v) for v in slot.values() if isinstance(v, str)):
                todo_slots.append(label)
            elif (unit, slot["slot"]) not in indexed:
                undecided.append(label)
    if (todo_slots or undecided) and not args.force:
        die("未收口：%d 个槽位没填完（%s）、%d 个槽位没裁决（%s）。先 fill/decide 再来；"
            "确要出半成品报告就加 --force。"
            % (len(todo_slots), "、".join(todo_slots[:3]) or "无",
               len(undecided), "、".join(undecided[:3]) or "无"))

    rows = []
    forms = {}
    for path in sorted(audit_paths(args.dir)["forms"].glob("*.json")):
        doc = ensure_arrays(load_json(path))
        unit = doc.get("unit") or path.stem
        forms[unit] = doc
        for slot in doc.get("slots", []):
            d = indexed.get((unit, slot["slot"]))
            rows.append((unit, slot, d))
    rows.sort(key=lambda row: (SEVERITY_RANK.get(row[2]["severity"] if row[2] else None, 4), row[0], row[1]["slot"]))

    verdict, verdict_text = audit_verdict(rows)
    defects = [r for r in rows if r[2] and r[2]["decision"] in ("CONFIRMED", "CONDITIONAL", "NEEDS-DECISION")]
    assertedsafe = [r for r in rows if r[2] and r[2]["decision"] == "VERIFIED"]
    rejected = [r for r in rows if r[2] and r[2]["decision"] == "REJECTED"]
    undecided = [r for r in rows if r[2] is None]

    lines = ["# 审计报告：%s" % audit["target"], ""]
    lines.append("- 范围：%s" % audit["scope"])
    lines.append("- 快照：%s" % audit["snapshot"])
    lines.append("- 生成时间：%s" % now())
    lines.append("- 槽位合计：%d（缺陷 %d / 已核实为安全 %d / 已排除 %d / 未裁决 %d）"
                 % (len(rows), len(defects), len(assertedsafe), len(rejected), len(undecided)))
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    lines.append("**%s** —— %s" % (verdict, verdict_text))
    lines.append("")
    lines.append("## 结论摘要")
    lines.append("")
    counts = {}
    for _, _, d in rows:
        key = (d["decision"] + "/" + (d["severity"] or "-")) if d else "未裁决"
        counts[key] = counts.get(key, 0) + 1

    def summary_key(key):
        severity = key.split("/", 1)[1] if "/" in key else None
        decision = key.split("/", 1)[0]
        return (SEVERITY_RANK.get(severity, 4), decision)

    for key in sorted(counts, key=summary_key):
        lines.append("- %s：%d" % (decision_label(key), counts[key]))
    lines.append("")

    if defects:
        lines.append("## 需要的动作（按优先级）")
        lines.append("")
        for unit, slot, d in sorted(defects, key=lambda r: SEVERITY_RANK.get(r[2].get("severity"), 4)):
            # 没记动作的缺陷也要出现——聚合节少一条，读的人会以为它不需要处理。
            lines.append("- **[%s] %s slot %s** —— %s"
                         % (d.get("severity") or "未定级", unit, slot["slot"],
                            d.get("actions") or "未记录动作（见明细）"))
            lines.append("  （对象：%s）" % slot.get("title"))
        lines.append("")

    lines.append("## 明细")
    lines.append("")
    for unit, slot, d in rows:
        if d is None:
            head = "(未裁决)"
        elif d["decision"] == "VERIFIED":
            head = "已核实为安全 / 按设计"
        elif d["decision"] == "REJECTED":
            head = "已排除（怀疑被推翻）"
        else:
            head = "%s" % (d["severity"] or "(未定级)")
        kind = str(slot.get("kind") or "").strip()
        lines.append("### %s slot %s — %s · %s%s"
                     % (unit, slot["slot"], head, slot.get("title"),
                        "" if kind in ("", "defect") else "（kind=%s）" % kind))
        lines.append("")
        lines.append("- 位置：`%s`" % slot.get("where"))
        lines.append("- 触发：%s" % slot.get("trigger"))
        lines.append("- 影响：%s" % slot.get("impact"))
        lines.append("- 预期：%s" % slot.get("expected"))
        lines.append("- 实测：%s" % slot.get("actual"))
        lines.append("- 反假设：%s" % slot.get("counter"))
        lines.append("- 搜证范围：%s" % slot.get("checked"))
        lines.append("- 子进程信心：%s（严重度提示：%s）"
                     % (slot.get("confidence"), slot.get("severityHint") or "未给"))
        if d:
            lines.append("- 裁决：**%s%s** —— %s"
                         % (d["decision"], (" / " + d["severity"]) if d.get("severity") else "", d["why"]))
            if d.get("severityBecause"):
                lines.append("- 级别偏离理由（调查者提示 %s → 裁 %s）：%s"
                             % (d.get("severityHint") or "无", d.get("severity"), d["severityBecause"]))
            if d.get("actions"):
                lines.append("- 动作：%s" % d["actions"])
            if d.get("flipQuestion"):
                lines.append("- 可翻盘的问题：%s" % d["flipQuestion"])
        else:
            lines.append("- 裁决：**未裁决**")
        for run, is_mut in form_records(forms, unit, slot["slot"]):
            lines.extend(render_record(run, is_mut))
        for anchor in form_anchors(forms, unit, slot["slot"]):
            lines.append("- 锚点：`%s`" % anchor["where"])
            lines.append("  ```")
            lines.append("  " + anchor["excerpt"].replace("\n", "\n  ")[:400])
            lines.append("  ```")
        if slot.get("notes"):
            lines.append("- 备注：%s" % slot["notes"])
        lines.append("")

    # 单元级证据：对照、装置自检、跨文件辅助实验（不属于任何槽位）
    unit_blocks = []
    for unit, doc in sorted(forms.items()):
        entries = doc.get("unitEvidence", [])
        if entries:
            unit_blocks.append((unit, entries))
    if unit_blocks:
        lines.append("## 覆盖与对照证据（单元级，不属于任何槽位）")
        lines.append("")
        for unit, entries in unit_blocks:
            lines.append("### %s（%d 条）" % (unit, len(entries)))
            lines.append("")
            for run in sorted(entries, key=at_key):
                is_mut = "file" in run and "from" in run
                lines.extend(render_record(run, is_mut))
            lines.append("")
        controls = [r for _, entries in unit_blocks for r in entries if r.get("control")]
        if controls:
            caught = sum(1 for r in controls if r.get("testCaughtMutation") is not False)
            lines.append("阳性对照小结：%d 处对照变异中 %d 处被捕获%s"
                         % (len(controls), caught,
                            "（全部成立，变异装置有效）" if caught == len(controls)
                            else "——**存在对照失败，判别力结论不可用**"))
            lines.append("")


    notes_block = audit.get("notes") or {}
    disclosures = notes_block.get("disclosure") or []
    residuals = notes_block.get("residual") or []
    if disclosures:
        lines.append("## 过程披露（对本审计不利的事实）")
        lines.append("")
        for item in disclosures:
            lines.append("- %s" % item["text"])
        lines.append("")
    if residuals:
        lines.append("## 残留不确定性（未闭合的前提）")
        lines.append("")
        for item in residuals:
            lines.append("- %s" % item["text"])
        lines.append("")

    text = "\n".join(lines) + "\n"
    out = Path(args.out) if args.out else (audit_paths(args.dir)["dir"] / "report.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if args.stdout:
        sys.stdout.write(text)
    note("已渲染报告：%s（%d 个槽位，已裁决 %d）" % (out, len(rows), sum(1 for r in rows if r[2])))


def form_records(forms, unit, slot):
    """一条槽位上的执行记录（证据 + 变异），按时间排序。"""
    doc = ensure_arrays(forms.get(unit, {}))
    pairs = [(r, False) for r in slot_evidence(doc, slot)]
    pairs += [(r, True) for r in slot_mutations(doc, slot)]
    pairs.sort(key=lambda pair: at_key(pair[0]))
    return pairs


def form_anchors(forms, unit, slot):
    return forms.get(unit, {}).get("anchors", {}).get(str(slot), [])


def exit_text(run):
    """exit=None 不是退出码，是"这条命令根本没跑成"（命令没找到 / 超时）。
    报告里必须区分开——否则读的人会把"没跑成"当成"跑出了别的退出码"。"""
    return "未执行成功（命令没找到或超时，见 stderr）" if run.get("exit") is None else str(run["exit"])


def render_record(run, is_mut):
    """一条执行记录 → markdown 行。变异与证据分属两个数组，这里按 is_mut 分流。"""
    if is_mut:
        # 锚点给完整字面量：截断后 from/to 会长得一模一样，读报告的人无法照着复核。
        return ["- 变异判别力（%s%s）：`%s` 里 `%s` → `%s`，之后 `%s` → exit=%s，%s"
                % ("YES" if run.get("testCaughtMutation") else "NO",
                   "，阳性对照" if run.get("control") else "",
                   run.get("file"), run.get("from"), run.get("to"),
                   run["cmd"], exit_text(run),
                   "该检查拦住了这条回归" if run.get("testCaughtMutation")
                   else "**该检查没有拦住这条回归**")]
    block = ["- 证据（运行）：`%s` → exit=%s（期望 %s，%s）"
             % (run["cmd"], exit_text(run), run.get("expectedExit"),
                "按预期" if run.get("matched") else "与期望不符")]
    if run.get("stdoutTail"):
        block += ["  ```", "  " + run["stdoutTail"].replace("\n", "\n  ")[:600], "  ```"]
    return block


def cmd_migrate(args):
    """模板版本迁移（破坏性重构后的升级路径）。

    v1 → v2：`runs` 里的记录按语义拆到 `evidence` / `mutations` 两个数组；槽位新增 `kind`
    字段（老表单没有这个信息，一律按 defect 迁移并在提示里列出来，让主代理复核）。
    """
    audit = load_audit(args.dir)
    tpl = load_template(BUG_TEMPLATE)
    forms_dir = audit_paths(args.dir)["forms"]
    # v1 没有 kind 概念——但若该槽位已经被裁决过，裁决本身就说明了它的性质。
    dec_path = audit_paths(args.dir)["decisions"]
    decided = {}
    if dec_path.exists():
        for entry in load_json(dec_path).get("decisions", []):
            decided[(entry["unit"], entry["slot"])] = entry.get("decision")
    migrated = 0
    skipped = 0
    for path in sorted(forms_dir.glob("*.json")):
        doc = load_json(path)
        if doc.get("template") == BUG_TEMPLATE:
            skipped += 1
            continue
        unit = doc.get("unit") or path.stem
        new_doc = ensure_arrays({
            "template": BUG_TEMPLATE,
            "unit": unit,
            "createdAt": doc.get("createdAt") or now(),
            "migratedFrom": doc.get("template"),
            "migratedAt": now(),
            "repoRoot": doc.get("repoRoot") or audit["repoRoot"],
        })
        notes = []
        for old_slot in doc.get("slots", []):
            new_slot = blank_slot(tpl, old_slot.get("slot"))
            if not old_slot.get("kind"):
                prior = decided.get((unit, old_slot.get("slot")))
                if prior == "VERIFIED":
                    new_slot["kind"] = "verification"
                    notes.append("slot %s 的 kind 按已登记的 VERIFIED 裁决推断为 verification"
                                 % old_slot.get("slot"))
                else:
                    new_slot["kind"] = "defect"
                    notes.append("slot %s 的 kind 按 defect 迁移（老表单无此字段，请复核）"
                                 % old_slot.get("slot"))
            dropped = []
            for key in new_slot:
                if key in old_slot:
                    new_slot[key] = old_slot[key]
            for key in old_slot:
                if key not in new_slot:
                    dropped.append(key)
            if dropped:
                notes.append("slot %s 丢弃未知字段：%s" % (old_slot.get("slot"), "、".join(dropped)))
            new_doc["slots"].append(new_slot)

        for slot_key, records in (doc.get("runs") or {}).items():
            for record in records:
                # v1 的变异记录带 kind='mutate'；再按形状兜一层（file/from/to），
                # 免得将来有人手改过 v1 文件、把标记弄丢。
                is_mutation = record.get("kind") == "mutate" or ("file" in record and "from" in record)
                if is_mutation:
                    record.pop("kind", None)
                    new_doc["mutations"].setdefault(slot_key, []).append(record)
                else:
                    new_doc["evidence"].setdefault(slot_key, []).append(record)
        for slot_key, anchors in (doc.get("anchors") or {}).items():
            new_doc["anchors"][slot_key] = anchors
        if doc.get("unitEvidence"):
            new_doc["unitEvidence"] = doc["unitEvidence"]
        new_doc["migrationNotes"] = notes

        if notes:
            note("%s：" % path.name)
            for item in notes:
                note("   - " + item)
        note("%s：%s → %s，槽位 %d，证据 %d / 变异 %d%s"
             % (path.name, doc.get("template"), BUG_TEMPLATE, len(new_doc["slots"]),
                sum(len(v) for v in new_doc["evidence"].values()),
                sum(len(v) for v in new_doc["mutations"].values()),
                "（--dry-run，未落盘）" if args.dry_run else ""))
        if not args.dry_run:
            save_json(path, new_doc)
        migrated += 1
    # 裁决与复核存根也带模板版本——表单升了它们没升，就成了一份"当前模板"下的半旧工件。
    stores = ((audit_paths(args.dir)["decisions"], DECISION_TEMPLATE),
              (audit_paths(args.dir)["dir"] / "challenges.json", CHALLENGE_TEMPLATE))
    for path, template in stores:
        if not path.exists():
            continue
        entries = load_json(path)
        if entries.get("template") != template:
            note("%s：%s → %s%s" % (path.name, entries.get("template"), template,
                                    "（--dry-run，未落盘）" if args.dry_run else ""))
            if not args.dry_run:
                entries["template"] = template
                save_json(path, entries)
    note("migrate：迁移 %d 个文件，跳过 %d 个已是最新%s"
         % (migrated, skipped, "（--dry-run，未落盘）" if args.dry_run else ""))


def cmd_dispatch(args):
    audit = load_audit(args.dir)
    entries = audit.setdefault("dispatches", [])
    entries.append({"unit": args.unit, "job": args.job, "brief": args.note or
                    str(audit_paths(args.dir)["briefs"] / (args.unit + ".md")), "at": now()})
    save_json(audit_paths(args.dir)["audit"], audit)
    note("已登记派发：unit %s ← job %s（累计 %d 次）" % (args.unit, args.job, len(entries)))
    seen = {}
    for entry in entries:
        seen[entry["unit"]] = seen.get(entry["unit"], 0) + 1
    note("派发统计：" + "，".join("%s×%d" % (u, n) for u, n in sorted(seen.items())))
    if args.unit not in (audit.get("unitTasks") or {}):
        note("  提示：unit %s 没有任务描述，任务书里的任务块是空的——派发前补 "
             "`brief --unit %s --task \"...\"`。" % (args.unit, args.unit))


def backup_paths(dir_, target):
    """变异前把原文另存一份，返回 (manifest, bytes)。

    还原只写在 `finally` 里——那对 `TerminateProcess`/`taskkill` 无效，而 mutate 改的是
    **用户的真实仓库**。一次被强杀的 mutate 会把文件永久留在变异态（实测复现）。所以：
    变异前先落盘原文 + 清单，任何一条后续命令启动时都会检查并自动还原。
    """
    key = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:16]
    d = audit_paths(dir_)["dir"] / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d / (key + ".json"), d / (key + ".bin")


def pid_alive(pid):
    """判断 pid 是否还活着。

    注意：Windows 上 `os.kill(pid, 0)` 不是"探活"——它会真的把进程 TerminateProcess 掉，
    所以这里必须走 tasklist。
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                                 capture_output=True, text=True, timeout=20).stdout or ""
        except Exception:  # noqa: BLE001 - 探活失败时按"已死"处理会误还原，按"活着"更安全
            return True
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def recover_pending_mutations(dir_):
    """任何命令启动时先自愈：上次被中断的变异必须在这里还原掉。

    清单还在 = 上一轮没收尾（或者被杀在还原之前）。**但正在跑的 mutate 不能被别人回滚**：
    并行审计里另一个调查者跑任何一条命令都会触发这里，若不做存活判断，就会把别人正在做的
    变异取证中途还原掉——那会直接伪造出"改坏了检查仍然通过"的假结论。
    """
    d = Path(dir_) / "backups"
    if not d.is_dir():
        return
    for man in sorted(d.glob("*.json")):
        binp = man.with_suffix(".bin")
        if not binp.exists():
            man.unlink(missing_ok=True)
            continue
        try:
            info = json.loads(man.read_text(encoding="utf-8"))
            target = Path(info["file"])
        except Exception:  # noqa: BLE001 - 清单本身坏了也不该拖死命令
            man.unlink(missing_ok=True)
            binp.unlink(missing_ok=True)
            continue
        if pid_alive(info.get("pid")):
            continue                      # 另一个进程正在变异这个文件，别碰
        if target.exists():
            current = hashlib.sha256(target.read_bytes()).hexdigest()
            if current != info.get("sha256"):
                target.write_bytes(binp.read_bytes())
                note("警告：上一次 mutate 未收尾（进程被强杀），已自动还原 %s" % target)
        man.unlink(missing_ok=True)
        binp.unlink(missing_ok=True)


def cmd_mutate(args):
    """变异判别力记录：改坏一处 → 跑指定命令 → 还原并校验哈希。

    `--cmd` 是被期望「因为这次变异而失败」的命令（通常是测试或断言脚本）：
      * 命令失败（非 0）→ 判别力 YES：该断言确实能拦住这个回归；
      * 命令仍成功      → 判别力 NO：这条回归不会被现有检查发现（这本身就是要报的结论）。
    `--control` 声明「这次变异**应该**被捕获」——阳性对照：它证明变异装置本身有效。
    不填 --slot 时记为单元级证据（对照、装置自检、跨文件实验都不属于某条发现）。
    """
    audit = load_audit(args.dir)
    path = form_file(args.dir, args.unit)
    doc = ensure_arrays(load_json(path))
    slot = find_slot(doc, args.slot) if args.slot is not None else None

    target = Path(audit["repoRoot"]) / args.file
    if not target.exists():
        die("变异目标不存在：%s" % target)
    original_bytes = target.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    text = original_bytes.decode("utf-8")
    occurrences = text.count(args.from_literal)
    if occurrences != 1:
        die("锚点在 %s 中出现 %d 次，必须恰好 1 次才能安全变异（阳性对照纪律）"
            % (args.file, occurrences))
    mutated = text.replace(args.from_literal, args.to_literal)
    if mutated == text:
        die("变异后文本未改变，锚点与替换串相同")

    if args.argv:
        cmd_text = " ".join(args.argv)
        use_shell, argv = False, args.argv
    elif args.cmd:
        cmd_text = args.cmd
        use_shell, argv = True, None
    else:
        die('需要 --cmd "<期望因变异而失败的命令>"，或 -- <argv...>')

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    exit_code, out, err = None, "", ""
    restored_ok = False

    # 清单文件就是锁：O_EXCL 建不出来说明同一文件上已经有一个未收尾的变异。
    man, binp = backup_paths(args.dir, target)
    try:
        fd = os.open(str(man), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        die("这个文件上还有一个未收尾的变异（%s）。先随便跑一条命令，工具会在启动时自动还原；"
            "确认过文件无误再删掉该清单。" % man)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"file": str(target), "sha256": original_sha, "pid": os.getpid(), "at": now()},
                  fh, ensure_ascii=False)
    binp.write_bytes(original_bytes)

    try:
        # 必须按字节写：write_text 在 Windows 会把 \n 翻成 \r\n，变异就不再是"只改了这一处"。
        target.write_bytes(mutated.encode("utf-8"))
        try:
            if use_shell:
                proc = subprocess.run(cmd_text, shell=True, cwd=audit["repoRoot"], env=env,
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=args.timeout)
            else:
                proc = subprocess.run(argv, cwd=audit["repoRoot"], env=env,
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=args.timeout)
            exit_code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired:
            err = "timeout after %ss" % args.timeout
    finally:
        target.write_bytes(original_bytes)
        restored_ok = hashlib.sha256(target.read_bytes()).hexdigest() == original_sha
        if restored_ok:
            # 还原成功才清备份；还原失败要留着，下一条命令启动时会再试一次。
            man.unlink(missing_ok=True)
            binp.unlink(missing_ok=True)

    caught = exit_code not in (0, None)
    record = {
        "file": args.file,
        "from": args.from_literal,
        "to": args.to_literal,
        "cmd": cmd_text,
        "exit": exit_code,
        "testCaughtMutation": caught,
        "control": bool(args.control),
        "restored": restored_ok,
        "stdoutTail": tail(out),
        "stderrTail": tail(err),
        "at": now(),
    }
    if slot is None:
        doc["unitEvidence"].append(record)
        where = "单元级证据（不属于任何槽位）"
    else:
        doc["mutations"].setdefault(str(args.slot), []).append(record)
        where = "槽位 %s" % args.slot
    save_json(path, doc)

    note("变异：%s 的 %r → %r%s" % (args.file, args.from_literal, args.to_literal,
                                    "（阳性对照）" if args.control else ""))
    verdict = "YES" if caught else "NO"
    if args.control and not caught:
        note("判别力：NO（命令 exit=%s）——**阳性对照失败**：这次变异本该被捕获却没有，"
             "说明装置或断言有问题，先修装置再看别的变异结果" % exit_code)
    elif args.control:
        note("判别力：YES（命令 exit=%s）——阳性对照成立：该断言确实能拦住这个回归" % exit_code)
    else:
        note("判别力：%s（命令 exit=%s）%s"
             % (verdict, exit_code,
                "——该检查能拦住这条回归" if caught else "——命令仍成功，说明这条回归不会被现有检查发现"))
    note("还原：%s（sha256 %s）%s" % ("已逐字节还原" if restored_ok else "**还原失败，请手动检查**",
                                    original_sha[:16], "  [%s]" % where))
    if not restored_ok:
        sys.exit(1)


def cmd_prune(args):
    """删除空槽/多余槽：把它的证据与锚点搬到指定槽位或单元级，再删掉槽位本身。"""
    path = form_file(args.dir, args.unit)
    doc = ensure_arrays(load_json(path))
    slot = find_slot(doc, args.slot)

    if args.move_to is not None:
        # 搬到不存在的槽位 = 把记录塞进报告里看不见的幽灵桶（实测 check 还报 0 问题）。
        if args.move_to == args.slot:
            die("--move-to 不能指向被删的那个槽位自身，否则记录会直接蒸发")
        if not has_slot(doc, args.move_to):
            die("--move-to 指向的槽位不存在：%s（现有槽位 %s）"
                % (args.move_to, "、".join(str(s["slot"]) for s in doc["slots"]) or "无"))

    moved = 0
    # 只搬「执行记录」（证据 + 变异）到目标容器；锚点是文件摘录、没有命令，
    # 它不属于单元级证据，只能跟着搬到另一个槽位，没有目标就丢弃。
    for bucket in ("evidence", "mutations"):
        records = doc.get(bucket, {}).pop(str(args.slot), [])
        if not records:
            continue
        if args.move_to is not None:
            doc[bucket].setdefault(str(args.move_to), []).extend(records)
        else:
            doc["unitEvidence"].extend(records)
        moved += len(records)
    anchors = doc.get("anchors", {}).pop(str(args.slot), [])
    if anchors and args.move_to is not None:
        doc["anchors"].setdefault(str(args.move_to), []).extend(anchors)
    doc["slots"] = [s for s in doc["slots"] if s["slot"] != args.slot]
    save_json(path, doc)

    # 槽位没了，它的裁决也必须一起消失——否则 check 会报「裁决指向不存在的槽位」。
    dec_path = audit_paths(args.dir)["decisions"]
    decisions = load_json(dec_path)
    before = len(decisions.get("decisions", []))
    decisions["decisions"] = [d for d in decisions.get("decisions", [])
                              if not (d["unit"] == args.unit and d["slot"] == args.slot)]
    dropped = before - len(decisions["decisions"])
    if dropped:
        save_json(dec_path, decisions)

    note("已删除 %s slot %s（%s）；搬运 %d 条记录到%s%s"
         % (args.unit, args.slot, str(slot.get("title"))[:40], moved,
            " slot %s" % args.move_to if args.move_to is not None else "单元级证据",
            "；同时清除 %d 条裁决" % dropped if dropped else ""))


def cmd_challenge(args):
    """盲化对抗复核：只把结论与最小复现配方交给复核者，不给证据包与推理。"""
    audit = load_audit(args.dir)
    doc = ensure_arrays(load_form(args.dir, args.unit))
    slot = find_slot(doc, args.slot)
    # 证据与变异分属两个数组，按时间合并——渲染时用 is_mut 区分，不再依赖记录里的 kind 字段。
    records = [(r, False) for r in slot_evidence(doc, args.slot)]
    records += [(r, True) for r in slot_mutations(doc, args.slot)]
    records.sort(key=lambda pair: at_key(pair[0]))

    if args.verdict:
        if args.verdict not in ("target-stands", "target-weakened", "target-refuted", "unresolved"):
            die("verdict 必须是 target-stands|target-weakened|target-refuted|unresolved")
        path = audit_paths(args.dir)["dir"] / "challenges.json"
        store = load_json(path) if path.exists() else {"template": CHALLENGE_TEMPLATE, "challenges": []}
        store["template"] = CHALLENGE_TEMPLATE
        store["challenges"] = [c for c in store["challenges"]
                               if not (c["unit"] == args.unit and c["slot"] == args.slot)]
        store["challenges"].append({"unit": args.unit, "slot": args.slot, "verdict": args.verdict,
                                    "job": args.job or "", "note": args.note or "", "at": now()})
        save_json(path, store)
        note("已记录对抗复核裁决：%s slot %s → %s" % (args.unit, args.slot, args.verdict))
        return

    for key in ("title", "where", "expected", "actual"):
        if TODO in str(slot.get(key, "")):
            die("槽位尚未填完（%s 仍是 TODO）；先把 F 层填好再请求复核" % key)
    if not records:
        die("没有运行记录，无法给出最小复现配方——先用 run 记录证据")

    lines = ["# 对抗复核（盲化）：%s slot %s" % (args.unit, args.slot), ""]
    lines.append("你是一名对抗性复核者。下面只有**结论 + 最小复现配方**，"
                 "没有调查者的推理、反假设、搜证范围，也没有任何已有裁决——这是刻意的。")
    lines.append("")
    lines.append("## 待挑战的结论")
    lines.append("")
    lines.append("- 一句话结论：%s" % slot.get("title"))
    lines.append("- 位置：`%s`" % slot.get("where"))
    lines.append("- 预期（若实现安全）：%s" % slot.get("expected"))
    lines.append("- 声称的实测：%s" % slot.get("actual"))
    lines.append("")
    lines.append("## 最小复现配方")
    lines.append("")
    lines.append("工作根：%s" % audit["repoRoot"])
    lines.append("下面按时间列出本槽位的**全部** %d 条记录（变异与运行分开标注）。"
                 "复现时先看标注，再看命令原文——注意：变异锚点是**完整字面量**，不要凭前几个字符猜。" % len(records))
    for run, is_mut in records:
        if is_mut:
            # 锚点必须原样给出：截断会让 from/to 变成两个一模一样的字符串，复核者无法照做。
            lines.append("- 变异%s：改坏 `%s`："
                         % ("（阳性对照）" if run.get("control") else "", run.get("file")))
            lines.append("  - 原字面量：`%s`" % run.get("from"))
            lines.append("  - 改成：`%s`" % run.get("to"))
            lines.append("  - 之后跑 `%s` → exit=%s（判别力 %s）"
                         % (run["cmd"], exit_text(run),
                            "YES：该检查拦得住" if run.get("testCaughtMutation") else "NO：改坏了检查仍通过"))
            if run.get("stdoutTail"):
                lines.append("  - 输出尾部：")
                lines.append("    ```")
                lines.append("    " + run["stdoutTail"].replace("\n", "\n    ")[:600])
                lines.append("    ```")
            continue
        lines.append("- 命令：`%s`" % run["cmd"])
        lines.append("  - 记录到的退出码：%s（期望 %s，%s）"
                     % (exit_text(run), run.get("expectedExit"), "按预期" if run.get("matched") else "与期望不符"))
        if run.get("stdoutTail"):
            lines.append("  - 输出尾部：")
            lines.append("    ```")
            lines.append("    " + run["stdoutTail"].replace("\n", "\n    ")[:800])
            lines.append("    ```")
    lines.append("")
    lines.append("## 你的任务")
    lines.append("")
    lines.append("尽最大努力**推翻**它。逐条检验下面五条反驳假设，每条都要给直接证据或明确记为未闭合：")
    lines.append("")
    lines.append("1. **运行时/环境差异**：结论依赖的运行时、版本或平台与真实目标是否不同？")
    lines.append("2. **路径可达性**：从真实入口出发，触发条件真的可达吗？有没有守卫、short-circuit 或默认值让它不可达？")
    lines.append("3. **替代路径**：是否存在另一条实现同样效果的路径，使这条缺陷的实际影响被夸大？")
    lines.append("4. **是否真是回归/新问题**：在基线版本上跑同一配方，行为是否本来就如此？")
    lines.append("5. **测试侧**：现有检查是否恰好把这个（错误的）行为固化成契约？把结论要求的修法做对之后，测试会不会反而变红？")
    lines.append("")
    lines.append("## 回报格式")
    lines.append("")
    lines.append("```text")
    lines.append("verdict: target-stands | target-weakened | target-refuted | unresolved")
    lines.append("confidence: High | Medium | Low")
    lines.append("per-refutation-check:")
    lines.append("  CH-1 <你的反驳假设> → refuted-target-stands | target-weakened | target-refuted | unresolved  证据：<命令/输出/file:line>")
    lines.append("  ...（CH-1..CH-5）")
    lines.append("strongest-counter-evidence: <你找到的最强反证；没有就写 none>")
    lines.append("not-verified: <你没能检验的部分>")
    lines.append("```")
    lines.append("")
    lines.append("不要修改被审目标树的任何文件；需要实验就在自己的 scratch 目录里做副本。")
    lines.append("不要把「我没找到问题」写成 target-stands——那要由证据支撑，不是由沉默支撑。")
    text = "\n".join(lines) + "\n"

    out = Path(args.out) if args.out else (audit_paths(args.dir)["dir"] / "challenges" /
                                          ("%s-%s.md" % (args.unit, args.slot)))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if args.stdout:
        sys.stdout.write(text)
    note("已生成盲化复核任务书：%s" % out)
    note("派发后请登记：challenge --unit %s --slot %s --verdict <结果> --job <执行者 id>"
         % (args.unit, args.slot))


def cmd_templates_check(args):
    problems = []
    checked = 0
    for name in (BUG_TEMPLATE, DECISION_TEMPLATE):
        tpl = load_template(name)
        fields = tpl["fields"]
        keys = [f["key"] for f in fields]
        checked += 1
        if len(keys) != len(set(keys)):
            problems.append("%s 有重复字段名" % name)
        required = [f for f in fields if f["required"]]
        checked += 1
        budget = tpl.get("maxRequiredFields", MAX_REQUIRED_FIELDS)
        if len(required) > budget:
            problems.append("%s 必填字段 %d 个，超出预算 %d" % (name, len(required), budget))
        checked += 1
        if budget > MAX_REQUIRED_FIELDS:
            problems.append("%s 声明的预算 %d 超过全局上限 %d" % (name, budget, MAX_REQUIRED_FIELDS))
        for field in fields:
            checked += 1
            has_check = field.get("check") in KNOWN_CHECKS
            has_question = bool(field.get("reviewQuestion"))
            if field.get("escapeHatch"):
                continue
            if not has_check and not has_question:
                problems.append("%s.%s 既没有机械检查也没有评审问题——按预算规则不允许新增这种字段"
                                % (name, field["key"]))
            if field.get("check") == "enum" and not field.get("enum"):
                problems.append("%s.%s 声明了 enum 检查却没有允许值" % (name, field["key"]))
            if field.get("check") == "pathline" and field.get("type") != "string":
                problems.append("%s.%s pathline 检查只能用于 string" % (name, field["key"]))
        checked += 1
        hatches = [f["key"] for f in fields if f.get("escapeHatch")]
        if len(hatches) > 1:
            problems.append("%s 有 %d 个逃生口字段（%s）；逃生口最多一个，否则它就是绕过预算的后门"
                            % (name, len(hatches), "、".join(hatches)))
    note("templates-check：检查了 %d 项；%d 个问题" % (checked, len(problems)))
    for problem in problems:
        note("  - " + problem)
    sys.exit(1 if problems else 0)


def cmd_self_test(args):
    """端到端自证：空槽 → 未填被拒 → run 记录 → 填齐通过 → J 层门禁 → 报告。"""
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="form-selftest-"))
    repo = tmp / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "thing.js").write_text("\n".join("line %d" % i for i in range(1, 13)) + "\n",
                                           encoding="utf-8")
    (repo / "check.py").write_text(
        "import pathlib, sys\n"
        "sys.exit(0 if 'line 3' in pathlib.Path('src/thing.js').read_text(encoding='utf-8') else 1)\n",
        encoding="utf-8")
    audit_dir = tmp / "audit"
    py = sys.executable or "python"
    results = []

    def step(name, ok, detail=""):
        results.append((name, ok, detail))
        note(("  ok   " if ok else "  FAIL ") + name + ((" — " + detail) if detail else ""))

    def first_lines(text, n=3):
        """失败时把工具输出摆出来——否则只知道断言没过，不知道为什么。"""
        lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
        return " / ".join(lines[:n])[:200]

    note("自证：%s" % tmp)

    def run_tool(*argv):
        proc = subprocess.run([py, "-B", str(Path(__file__).resolve()), "--dir", str(audit_dir)] + list(argv),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    def run_tool_dir_last(*argv):
        """同一批命令，但把 --dir 放到子命令之后——文档、任务书、手写命令里都出现过这种写法。"""
        proc = subprocess.run([py, "-B", str(Path(__file__).resolve())] + list(argv) + ["--dir", str(audit_dir)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    rc, out = run_tool("init", "--repo-root", str(repo), "--target", "selftest",
                       "--scope", "src/**", "--snapshot", "git:aaa..bbb", "--unit", "R1")
    step("init 建实例并给出 token", rc == 0 and "AUDIT_MAIN_TOKEN=" in out, out.strip().splitlines()[-1][:60])
    token = ""
    for line in out.splitlines():
        if "AUDIT_MAIN_TOKEN=" in line:
            token = line.split("AUDIT_MAIN_TOKEN=", 1)[1].strip()
    step("token 可被解析", len(token) == 32, "len=%d" % len(token))

    rc, out = run_tool("new", "--unit", "R1", "--count", "4")
    doc = load_json(form_file(audit_dir, "R1"))
    step("new --count 4 生成 4 个空槽", rc == 0 and len(doc["slots"]) == 4, "slots=%d" % len(doc["slots"]))
    step("空槽里每个必填格子都是 TODO（含 kind）", all(TODO in doc["slots"][0][f["key"]]
                                                   for f in load_template(BUG_TEMPLATE)["fields"] if f["required"]))
    step("v2 数据模型：evidence/mutations/unitEvidence 三个容器都在",
         all(k in doc for k in ("evidence", "mutations", "unitEvidence")))

    rc, out = run_tool("fill", "--unit", "R1")
    step("未填时 fill 被拒（exit 1）", rc == 1 and "问题" in out, out.strip().splitlines()[0][:70])

    rc, _ = run_tool("decide", "--unit", "R1", "--slot", "1", "--decision", "CONFIRMED",
                     "--severity", "High", "--why", "x")
    step("无 token 时 decide 被拒", rc == 2)

    rc, _ = run_tool("run", "--unit", "R1", "--slot", "1", "--cmd",
                     '"%s" -c "print(\'ok\')"' % py, "--expect-exit", "0")
    rc2, _ = run_tool("run", "--unit", "R1", "--slot", "2", "--cmd",
                      '"%s" -c "import sys; sys.exit(3)"' % py, "--expect-exit", "3")
    doc = load_json(form_file(audit_dir, "R1"))
    step("run 记录了执行并代填 how",
         rc == 0 and rc2 == 0 and len(doc["evidence"]["1"]) == 1 and doc["evidence"]["2"][0]["matched"],
         "slot1 exit=%s slot2 matched=%s" % (doc["evidence"]["1"][0]["exit"], doc["evidence"]["2"][0]["matched"]))
    step("how 字段被工具写回", doc["slots"][0]["how"] != doc["slots"][1]["how"])

    # 不填 --slot 的 run：单元级证据（对照 / 装置自检 / 跨文件辅助实验的家）
    rc, out = run_tool("run", "--unit", "R1", "--cmd", '"%s" -c "print(\'device-check\')"' % py,
                       "--purpose", "装置自检：确认测试运行器可用")
    doc = load_json(form_file(audit_dir, "R1"))
    unit_runs = [e for e in doc["unitEvidence"] if e.get("purpose")]
    step("不填 --slot 的 run 记入单元级证据（不再逼人建空槽）",
         rc == 0 and len(unit_runs) == 1 and unit_runs[0]["matched"],
         "unitEvidence=%d" % len(doc["unitEvidence"]))
    step("单元级证据没有污染任何槽位的证据数组",
         all(str(i) not in doc["evidence"] for i in (3, 4)) and len(doc["evidence"]) == 2)

    # mutate --control：阳性对照（不填 slot，进单元级证据）
    rc, out = run_tool("mutate", "--unit", "R1", "--file", "src/thing.js",
                       "--from", "line 3", "--to", "line THREE", "--cmd", '"%s" check.py' % py,
                       "--control")
    doc = load_json(form_file(audit_dir, "R1"))
    controls = [e for e in doc["unitEvidence"] if e.get("control")]
    step("mutate --control 记入单元级证据且对照成立",
         rc == 0 and len(controls) == 1 and controls[0]["testCaughtMutation"],
         "control caught=%s" % (controls[0]["testCaughtMutation"] if controls else "无"))

    rc, out = run_tool("dispatch", "--unit", "R1", "--job", "selftest-agent-1")
    step("派发登记可查", rc == 0 and "selftest-agent-1" in out)

    rc, out = run_tool("mutate", "--unit", "R1", "--slot", "2", "--file", "src/thing.js",
                       "--from", "line 3", "--to", "line THREE", "--cmd", '"%s" check.py' % py)
    doc_mut = load_json(form_file(audit_dir, "R1"))
    mutation_yes = doc_mut["mutations"].get("2", [])
    step("变异判别力 YES：检查确实拦住了这条回归",
         rc == 0 and mutation_yes and mutation_yes[-1]["testCaughtMutation"] and mutation_yes[-1]["restored"],
         "exit=%s restored=%s" % (mutation_yes[-1]["exit"], mutation_yes[-1]["restored"]) if mutation_yes else "无记录")

    rc, out = run_tool("mutate", "--unit", "R1", "--slot", "2", "--file", "src/thing.js",
                       "--from", "line 9", "--to", "line NINE", "--cmd", '"%s" check.py' % py)
    doc_mut = load_json(form_file(audit_dir, "R1"))
    mutation_no = doc_mut["mutations"].get("2", [])
    step("变异判别力 NO：检查覆盖不到的另一处回归照样通过",
         rc == 0 and mutation_no and not mutation_no[-1]["testCaughtMutation"])
    step("变异记录与证据记录分属两个数组（不再靠 kind 字段区分）",
         len(doc_mut["mutations"]["2"]) == 2 and len(doc_mut["evidence"]["2"]) == 1
         and all("kind" not in r for r in doc_mut["mutations"]["2"]))
    step("变异后文件被逐字节还原",
         (repo / "src" / "thing.js").read_text(encoding="utf-8").startswith("line 1\nline 2\nline 3"),
         "sha 校验见上一步输出")
    rc, out = run_tool("mutate", "--unit", "R1", "--slot", "2", "--file", "src/thing.js",
                       "--from", "line", "--to", "row", "--cmd", '"%s" check.py' % py)
    step("锚点出现多次时拒绝变异（阳性对照纪律）", rc == 2 and "恰好" in out, first_lines(out))

    # 用脚本把 4 个槽位填成合法内容（模拟子进程只改值）：1 缺陷High候选 / 2 缺陷Medium / 3 负结果 / 4 静态无证据
    doc = load_json(form_file(audit_dir, "R1"))
    fills = [
        ("defect", "thing 在越界时会静默回退", "src/thing.js:3", "输入为空时", "数据被写成当天", "应抛错", "实测回落到今天", "High", "Medium"),
        ("defect", "导出漏掉 topStarred", "src/thing.js:5-7", "ranking 重写时", "榜单少一层", "必须报错", "实测 exit 0", "High", "Medium"),
        ("verification", "弱值拒绝逻辑在打开开关时确实是 fail-closed", "src/thing.js:8", "显式打开开关后", "若实现是坏的会放行弱凭据", "应返回 500", "实测返回 500，关掉开关则 200", "High", ""),
        ("defect", "描述含实体未解码", "src/thing.js:9", "上游描述含 &amp;", "客户端显示字面量", "应解码", "实测原样输出（仅静态阅读，未跑探针）", "Low", "Low"),
    ]
    for slot, (kind, title, where, trigger, impact, expected, actual, conf, hint) in zip(doc["slots"], fills):
        slot.update({"kind": kind, "title": title, "where": where, "trigger": trigger, "impact": impact,
                     "expected": expected, "actual": actual, "confidence": conf,
                     "counter": "上游保证单行", "checked": "读了 src/thing.js 全文与调用方"})
        if hint:
            slot["severityHint"] = hint
    save_json(form_file(audit_dir, "R1"), doc)

    # 负结果槽位也必须跑一次真实检查——负结果不是沉默，是执行过的检查
    run_tool("run", "--unit", "R1", "--slot", "3", "--cmd", '"%s" -c "print(\'fail-closed confirmed\')"' % py)
    rc, out = run_tool("fill", "--unit", "R1", "--verify-paths")
    step("第 4 槽无运行记录时 fill 仍被拒", rc == 1 and "缺少运行记录" in out)
    rc, out = run_tool("fill", "--unit", "R1", "--verify-paths", "--allow-static")
    step("显式 --allow-static 后 fill 通过（0 问题）", rc == 0 and "0 个问题" in out,
         out.strip().splitlines()[0][:70])
    doc = load_json(form_file(audit_dir, "R1"))
    step("锚点被抓取（含摘录与文件哈希）",
         bool(doc["anchors"].get("1")) and "excerpt" in doc["anchors"]["1"][0])

    rc, out = run_tool("decide", "--unit", "R1", "--slot", "3", "--decision", "CONFIRMED",
                       "--severity", "High", "--why", "x", "--token", token)
    step("kind=verification 的槽位不允许 CONFIRMED（必须 VERIFIED）",
         rc == 2 and "kind=verification" in out)

    rc, out = run_tool("decide", "--unit", "R1", "--slot", "4", "--decision", "CONFIRMED",
                       "--severity", "High", "--why", "x", "--token", token)
    step("无运行记录的槽位不允许 CONFIRMED", rc == 2 and "需要至少一条" in out, first_lines(out))

    rc, out = run_tool("decide", "--unit", "R1", "--slot", "1", "--decision", "CONFIRMED",
                       "--severity", "High", "--why", "已按预期复现", "--token", token)
    step("High 的 CONFIRMED 要求先做盲化对抗复核", rc == 2 and "盲化对抗复核" in out, first_lines(out))

    rc, out = run_tool("challenge", "--unit", "R1", "--slot", "1")
    challenge_file = audit_dir / "challenges" / "R1-1.md"
    body = challenge_file.read_text(encoding="utf-8") if challenge_file.exists() else ""
    step("盲化复核任务书只给结论与复现配方，不给反假设/搜证范围",
         rc == 0 and "最小复现配方" in body
         and "上游保证单行" not in body and "读了 src/thing.js 全文与调用方" not in body)

    rc, out = run_tool("challenge", "--unit", "R1", "--slot", "2")
    challenge_file_2 = audit_dir / "challenges" / "R1-2.md"
    body_2 = challenge_file_2.read_text(encoding="utf-8") if challenge_file_2.exists() else ""
    step("含变异记录的槽位也能生成盲化任务书（变异与证据已分数组）",
         rc == 0 and "判别力" in body_2, out.strip().splitlines()[-1][:80] if rc != 0 else "")

    rc, out = run_tool("challenge", "--unit", "R1", "--slot", "1",
                       "--verdict", "target-stands", "--job", "selftest-challenger")
    step("复核结果可登记", rc == 0 and "target-stands" in out)

    rc, out = run_tool("decide", "--unit", "R1", "--slot", "1", "--decision", "CONFIRMED",
                       "--severity", "High", "--why", "已按预期复现，且盲化复核 target-stands",
                       "--token", token, "--actions", "改回退逻辑", "--flip-question", "上游是否已保证非空？")
    step("严重度偏离提示值（Medium→High）时必须写 --severity-because",
         rc == 2 and "severity-because" in out)

    rc, out = run_tool("decide", "--unit", "R1", "--slot", "1", "--decision", "CONFIRMED",
                       "--severity", "High", "--why", "已按预期复现，且盲化复核 target-stands",
                       "--severity-because", "影响是数据被静默写错且下游无法察觉，可达性 Common、不可自动恢复",
                       "--token", token, "--actions", "改回退逻辑", "--flip-question", "上游是否已保证非空？")
    step("写清偏离理由后 decide 成功", rc == 0 and "已裁决" in out)

    rc, out = run_tool("check")
    step("仍有未裁决槽位时 check 报问题", rc == 1 and "未裁决" in out)

    rc, out = run_tool("decide", "--unit", "R1", "--slot", "2", "--decision", "CONFIRMED",
                       "--severity", "Medium", "--why", "缺真实上游数据，但机制已复现", "--token", token)
    step("提示值与裁决一致时不要求偏离理由", rc == 0 and "已裁决" in out)
    rc, out = run_tool("decide", "--unit", "R1", "--slot", "3", "--decision", "VERIFIED",
                       "--why", "实测打开开关后弱凭据被拒（负结果：该控制是有效的）", "--token", token)
    step("负结果以 VERIFIED 立项（不带 severity）", rc == 0 and "已裁决" in out)
    rc, out = run_tool("decide", "--unit", "R1", "--slot", "4", "--decision", "REJECTED",
                       "--why", "静态阅读未见该路径可达", "--token", token, "--allow-static")
    step("REJECTED 允许只基于静态阅读（显式 --allow-static）", rc == 0 and "已裁决" in out)
    rc, out = run_tool("check")
    step("全部裁决后 check 通过（0 问题）", rc == 0 and "0 个问题" in out,
         out.strip().splitlines()[0][:70])

    rc, out = run_tool("report")
    report_path = audit_dir / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    order = [report.find("### R1 slot %d" % i) for i in (1, 2, 3, 4)]
    step("报告按严重度排序（High→Medium→Low→已核实）且含全部槽位",
         rc == 0 and all(i > 0 for i in order) and order == sorted(order)
         and all(t in report for _, t, *_ in fills),
         "slot 位置=%s %s" % (order, out.strip().splitlines()[-1][:100] if rc != 0 else ""))
    step("报告带可翻盘的问题", "可翻盘的问题" in report)
    step("报告带机械算出的结论行（BLOCKED：存在未闭合的 High）",
         "**" in report and "BLOCKED" in report and "不具备发布/合并条件" in report)
    step("报告带「需要的动作」聚合节且含 High 条目",
         "## 需要的动作（按优先级）" in report and "[High]" in report)
    step("没记动作的缺陷也在聚合节里露面（不许静默消失）",
         "未记录动作（见明细）" in report)
    step("报告带「覆盖与对照证据」附录（单元级证据 + 阳性对照小结）",
         "## 覆盖与对照证据" in report and "阳性对照小结" in report and "device-check" in report)
    step("报告把负结果单列为「已核实为安全 / 按设计」",
         "已核实为安全 / 按设计" in report)
    step("报告把被推翻的怀疑单列为「已排除（怀疑被推翻）」",
         "已排除（怀疑被推翻）" in report)
    step("报告写出严重度偏离理由", "级别偏离理由" in report and "可达性 Common" in report)

    rc, out = run_tool("brief", "--unit", "R1")
    brief = (audit_dir / "briefs" / "R1.md").read_text(encoding="utf-8")
    step("任务书列出字段与权限边界",
         rc == 0 and "decide" in brief and "必填" in brief and "main token" in brief)
    step("没写任务描述时，任务块明说「未指定」而不是静默留白",
         "## 你的任务" in brief and "（未指定）" in brief and "没有任务描述" in out)

    rc, out = run_tool("brief", "--unit", "R1", "--task", "只回答一件事：限速维度是否可被单 IP 打满")
    rc2, _ = run_tool("brief", "--unit", "R1")           # 重渲染不带 --task
    brief = (audit_dir / "briefs" / "R1.md").read_text(encoding="utf-8")
    step("任务描述写进契约，重渲染不丢",
         rc == 0 and rc2 == 0 and "限速维度是否可被单 IP 打满" in brief
         and (load_json(audit_paths(audit_dir)["audit"]).get("unitTasks") or {}).get("R1", "").startswith("只回答一件事"))
    step("任务书里的命令把 --dir 写在子命令之前（canonical 形态）",
         not re.search(r"audit_forms\.py [a-z-]+ --dir", brief),
         "反例：--dir 写在子命令之后会 exit=2（unrecognized arguments）")
    rc, out = run_tool_dir_last("templates-check")
    step("--dir 写在子命令之后也能被解析（位置敏感只是陷阱）", rc == 0, first_lines(out))

    doc = load_json(form_file(audit_dir, "R1"))
    doc["template"] = "bug/v1"          # 伪造一份 v1 表单来验证迁移路径
    # v1 的变异记录带 kind='mutate' 标记——伪造时也要补上，否则迁移无从区分
    v1_mutations = {k: [dict(r, kind="mutate") for r in v] for k, v in doc["mutations"].items()}
    doc["runs"] = {"1": doc["evidence"]["1"] + v1_mutations.get("1", []),
                   "2": doc["evidence"]["2"] + v1_mutations.get("2", []),
                   "3": doc["evidence"]["3"] + v1_mutations.get("3", [])}
    for slot in doc["slots"]:
        slot.pop("kind", None)
    doc.pop("evidence")
    doc.pop("mutations")
    save_json(form_file(audit_dir, "R1"), doc)
    rc_dry, out_dry = run_tool("migrate", "--dry-run")
    rc_mig, out_mig = run_tool("migrate")
    doc = load_json(form_file(audit_dir, "R1"))
    step("migrate 把旧模板表单升级到当前模板（runs 拆成 evidence/mutations、按裁决推断 kind）",
         rc_dry == 0 and rc_mig == 0 and doc["template"] == BUG_TEMPLATE
         and doc.get("migratedFrom") == "bug/v1"
         and len(doc["evidence"]["1"]) == 1 and len(doc["mutations"]["2"]) == 2
         and doc["slots"][2]["kind"] == "verification"
         and [s["kind"] for s in doc["slots"]] == ["defect", "defect", "verification", "defect"],
         "kinds=%s evidence1=%d mutations2=%d"
         % ([s["kind"] for s in doc["slots"]], len(doc.get("evidence", {}).get("1", [])),
            len(doc.get("mutations", {}).get("2", []))))
    rc, out = run_tool("check")
    step("迁移后 check 仍通过（裁决未受影响）", rc == 0 and "0 个问题" in out,
         " / ".join(l.strip() for l in out.strip().splitlines()[:3]))
    rc, out2 = run_tool("fill", "--unit", "R1", "--verify-paths", "--allow-static")
    step("迁移后 fill 仍通过", rc == 0 and "0 个问题" in out2,
         " / ".join(l.strip() for l in out2.strip().splitlines()[:3]))

    # 主代理归约时会重排/搬运记录——数组顺序因此不再等于时间顺序，
    # 而 how 是按挂钟顺序写回的。这条用例防止「依赖数组顺序」的回归。
    doc = load_json(form_file(audit_dir, "R1"))
    doc["evidence"]["1"] = list(reversed(doc["evidence"]["1"]))
    save_json(form_file(audit_dir, "R1"), doc)
    rc, out = run_tool("fill", "--unit", "R1", "--verify-paths", "--allow-static")
    step("证据数组被重排后 fill 仍通过（how 按时间比对，不依赖数组顺序）",
         rc == 0 and "0 个问题" in out, out.strip().splitlines()[0][:80])

    rc, out = run_tool("prune", "--unit", "R1", "--slot", "4")
    doc = load_json(form_file(audit_dir, "R1"))
    decisions_doc = load_json(audit_dir / "decisions.json")
    step("prune 删除空槽并同步清掉它的裁决（不留悬空引用）",
         rc == 0 and [s["slot"] for s in doc["slots"]] == [1, 2, 3]
         and not any(d["slot"] == 4 for d in decisions_doc["decisions"]),
         "slots=%s" % [s["slot"] for s in doc["slots"]])
    rc, out = run_tool("check")
    step("prune 之后 check 仍 0 问题", rc == 0 and "0 个问题" in out,
         " / ".join(l.strip() for l in out.strip().splitlines()[:3]))

    failures = [r for r in results if not r[1]]
    note("")
    if failures:
        note("SELF-TEST FAIL：%d/%d 项未通过" % (len(failures), len(results)))
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(1)
    note("SELF-TEST PASS：%d/%d 项通过（工作区 %s，已清理）" % (len(results), len(results), tmp))
    shutil.rmtree(tmp, ignore_errors=True)


# -------------------------------------------------------------------------- cli


def build_parser():
    parser = argparse.ArgumentParser(prog="audit_forms.py",
                                     description="表单平面：模板即唯一真相源，子进程只填空。")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="审计实例目录（默认 %s）" % DEFAULT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="建立审计实例，生成 main token")
    p.add_argument("--repo-root", default=".")
    p.add_argument("--profile", default="change", choices=["change", "fix-verification", "security", "project"])
    p.add_argument("--target")
    p.add_argument("--scope")
    p.add_argument("--snapshot")
    p.add_argument("--unit", action="append")
    p.add_argument("--add-unit", action="append",
                   help="往已有实例追加调查单元（漫游单元等），不重建实例")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("brief", help="从模板渲染某一 unit 的任务书")
    p.add_argument("--unit", required=True)
    p.add_argument("--task", help="本单元要回答什么（写一次就存进 audit.json，重渲染不丢）")
    p.add_argument("--out")
    p.add_argument("--stdout", action="store_true")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("new", help="生成 N 个空槽（单文件）")
    p.add_argument("--unit", required=True)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--add", type=int, default=0, help="在已有槽位后再加 N 个")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("run", help="执行并记录一条证据命令（不填 --slot 则记为单元级证据）")
    p.add_argument("--unit", required=True)
    p.add_argument("--slot", type=int, help="挂到某个槽位；省略则记入单元级证据（对照/自检/辅助实验）")
    p.add_argument("--cmd")
    p.add_argument("--expect-exit", type=int, default=0)
    p.add_argument("--purpose", help="这条运行是干什么的（单元级证据建议写明）")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("argv", nargs="*")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("fill", help="硬校验：TODO 残留 / 必填 / 枚举 / 行号 / 运行记录")
    p.add_argument("--unit")
    p.add_argument("--verify-paths", action="store_true")
    p.add_argument("--allow-static", action="store_true")
    p.set_defaults(func=cmd_fill)

    p = sub.add_parser("decide", help="J 层裁决（仅主代理，需 main token）")
    p.add_argument("--unit", required=True)
    p.add_argument("--slot", type=int, required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--severity")
    p.add_argument("--severity-because", dest="severity_because",
                   help="与调查者的 severityHint 不一致时必填：为什么改级别")
    p.add_argument("--why", required=True)
    p.add_argument("--flip-question", dest="flip_question")
    p.add_argument("--actions")
    p.add_argument("--allow-static", action="store_true")
    p.add_argument("--allow-unchallenged", action="store_true",
                   help="High/Critical 的 CONFIRMED 跳过盲化复核（必须写进 --why）")
    p.add_argument("--revise", action="store_true",
                   help="改写已有裁决（旧条目进 history 留痕；不加这个会被拒绝）")
    p.add_argument("--token")
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("mutate", help="变异判别力：改坏一处→跑检查→还原并校验哈希（--control 声明阳性对照）")
    p.add_argument("--unit", required=True)
    p.add_argument("--slot", type=int, help="挂到某个槽位；省略则记入单元级证据")
    p.add_argument("--file", required=True, help="相对工作根的待变异文件")
    p.add_argument("--from", dest="from_literal", required=True, help="锚点字面量（必须恰好出现 1 次）")
    p.add_argument("--to", dest="to_literal", required=True, help="替换后的字面量")
    p.add_argument("--cmd", help="期望因变异而失败的命令（测试/断言）")
    p.add_argument("--control", action="store_true",
                   help="阳性对照：声明这次变异**应该**被捕获（用来证明变异装置有效）")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("argv", nargs="*")
    p.set_defaults(func=cmd_mutate)

    p = sub.add_parser("prune", help="删除空槽/多余槽（可把其证据搬到指定槽或单元级）")
    p.add_argument("--unit", required=True)
    p.add_argument("--slot", type=int, required=True)
    p.add_argument("--move-to", type=int, help="把该槽的证据/锚点搬到这个槽位；省略则搬到单元级证据")
    p.set_defaults(func=cmd_prune)

    p = sub.add_parser("challenge", help="盲化对抗复核：生成只含结论与复现配方的任务书，或登记结果")
    p.add_argument("--unit", required=True)
    p.add_argument("--slot", type=int, required=True)
    p.add_argument("--verdict")
    p.add_argument("--job")
    p.add_argument("--note")
    p.add_argument("--out")
    p.add_argument("--stdout", action="store_true")
    p.set_defaults(func=cmd_challenge)

    p = sub.add_parser("dispatch", help="登记一次派发（unit ← 执行者 id）")
    p.add_argument("--unit", required=True)
    p.add_argument("--job", required=True)
    p.add_argument("--note")
    p.set_defaults(func=cmd_dispatch)

    p = sub.add_parser("note", help="记录过程披露 / 残留不确定性（报告末尾两节）")
    p.add_argument("--kind", choices=["disclosure", "residual"], required=True)
    p.add_argument("--text", required=True)
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("migrate", help="把旧模板版本的表单升级成当前模板")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("check", help="审计级不变量 + 打印检查项数")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("report", help="从已填事实渲染 markdown 报告")
    p.add_argument("--out")
    p.add_argument("--stdout", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="明知未收口也出报告（报告里会如实标出未填/未裁决的槽位）")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("templates-check", help="模板预算与字段规则自检")
    p.set_defaults(func=cmd_templates_check)

    p = sub.add_parser("self-test", help="端到端自证（临时目录，跑完清理）")
    p.set_defaults(func=cmd_self_test)

    # `--dir` 在子命令前后都应该能用。位置敏感是纯陷阱：文档、任务书、手写命令
    # 三种写法都真实存在，写错位置只会得到一句 unrecognized arguments。
    # default=SUPPRESS 保证没写时不覆盖主解析器已经解析出的值。
    for child in sub.choices.values():
        child.add_argument("--dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return parser


def main():
    # 两个流都必须固定成 UTF-8：否则 stderr 跟随 Windows 控制台代码页（cp936），
    # 中文报错在别的进程里读出来就是乱码，断言和日志全都对不上。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 老解释器没有 reconfigure
            pass
    args = build_parser().parse_args()
    # 任何命令启动前先自愈：上次被强杀的 mutate 可能把用户的文件留在变异态。
    try:
        recover_pending_mutations(args.dir)
    except Exception as exc:  # noqa: BLE001 - 自愈失败不该阻断命令，但要喊出来
        note("警告：检查未收尾的变异时出错：%s" % exc)
    args.func(args)


if __name__ == "__main__":
    main()
