#!/usr/bin/env python3
"""为每个有过邮件往来的候选生成一份档案 md——把散在四处的信息合成一页。

一个博主的信息现在分布在：db_intl.csv（画像/报价/状态）、outreach_sent.jsonl
（发了什么、什么时候、哈希）、replies.jsonl（对方回了什么）、drafts_*.md（发出
去的正文原文）。谈判时要在四个文件之间来回跳，还容易看漏。本脚本把它们按人合成
一份档案，一人一文件。

**纯处理，不抓取**（见 SKILL.md §0 的设计纪律）：本脚本不访问任何网页。博主给的
网址里有什么，由带浏览器的一端看完写进「人工区」，脚本只负责保留它。

**人工区不会被覆盖**：`MANUAL_MARK` 那行以下的内容原样保留，重跑只重算它上面的
机器区。所以随时可以重跑来同步最新状态，不会弄丢手写的调研笔记——这是把「可再生
的机器数据」和「不可再生的人工判断」放进同一个文件时唯一安全的做法。

**只给收到过实质回信的人建档。** 发出去还没回音的人，档案里除了 CSV 已有的内容什么都
没有，白多一个要维护的地方；有来信才有东西可记（报价、条款、对方给的链接、待判断的
问题）。要扩大范围用 --sent / --all / --ids。

用法:
  python3 build_dossier.py                       # 默认：只出收到过回信的
  python3 build_dossier.py --sent                # 扩到所有实发过邮件的
  python3 build_dossier.py --all                 # 全库
  python3 build_dossier.py --ids INTL-010,INTL-011
  python3 build_dossier.py --out <目录>
"""
import argparse, csv, glob, hashlib, json, os, re, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.abspath(os.path.join(ROOT, "..", "海外社媒", "博主档案"))
MANUAL_MARK = "<!-- ↓↓↓ 人工区：以下内容重跑时原样保留，机器不会改写 ↓↓↓ -->"

MANUAL_TEMPLATE = """
## 网址与内容存档

> 博主自己给的链接，以及链接里实际有什么。**人看过再写**，不要写"待查"。

（暂无）

## 判断与待办

（暂无）
"""


def load_db(path):
    return {r["id"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def load_all_drafts():
    """把所有草稿文件里的正文按 id 收进来，用于还原「实际发出的原文」。"""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from outreach_send import parse_drafts
    out = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "drafts_*.md")) +
                    glob.glob(os.path.join(ROOT, "data", "replies_out_*.md"))):
        for cid, d in parse_drafts(p).items():
            sha = hashlib.sha256(d["body"].encode("utf-8")).hexdigest()
            out.setdefault(cid, {})[sha] = d
    return out


def fmt_int(v):
    v = (v or "").strip()
    if not v:
        return "—"
    try:
        return f"{int(float(v)):,}"
    except ValueError:
        return v


def cost_per_1k_followers(row):
    """每千粉成本 = 报价 ÷ 粉丝 × 1000。

    **这不是 schema 里的 `cpm`**，两者别混。schema 的 cpm 分母是 expected_exposure
    （实际播放），海外线在补采播放中位数之前一律为空。粉丝数是个更差的分母——粉丝
    不等于看到的人——但它现在就有，可以横向比谁贵谁便宜，所以单独起个名字放这里。
    """
    q = (row.get("quote_video") or row.get("quote_image") or "").strip()
    f = (row.get("followers") or "").strip()
    if not q or not f:
        return None
    try:
        q, f = float(q), float(f)
    except ValueError:
        return None
    return round(q / f * 1000, 2) if f else None


def section_profile(r):
    cp1k = cost_per_1k_followers(r)
    rows = [
        ("平台 / 垂类", f"{r['platform']} · {r['niche'] or '—'}"),
        ("粉丝数", fmt_int(r["followers"])),
        ("国家 / 语言", f"{r['country'] or '—'} · {r['language'] or '—'}"),
        ("主页", r["profile_url"] or "—"),
        ("邮箱", r["email"] or "—"),
        ("邮箱来源", f"{r['contact_source'] or '—'}"
                     f"{'（核验于 ' + r['contact_verified_at'] + '）' if r.get('contact_verified_at') else ''}"),
        ("入库时间", r["collected_at"] or "—"),
        ("数据置信度", r["data_confidence"] or "—"),
    ]
    out = "## 基本信息\n\n| | |\n|---|---|\n"
    out += "".join(f"| {k} | {v} |\n" for k, v in rows)

    out += "\n## 状态与报价\n\n| | |\n|---|---|\n"
    quote_rows = [
        ("触达状态", r["status"] or "—"),
        ("老板审批", r["approval"] or "—"),
        ("首次触达", r["first_contact_date"] or "—"),
        ("图文报价", fmt_int(r["quote_image"])),
        ("视频报价", fmt_int(r["quote_video"])),
        ("报价说明", r["quote_notes"] or "—"),
        ("每千粉成本", f"{cp1k}" if cp1k is not None else "—"),
        ("预期曝光", fmt_int(r["expected_exposure"])),
        ("预估 CPM", (r["cpm"] or "—") + ("" if r["cpm"] else
                     "　← 曝光为空时 CPM 必须为空（schema 口径）")),
    ]
    out += "".join(f"| {k} | {v} |\n" for k, v in quote_rows)
    return out


def section_scores(r):
    keys = [("score_fit", "契合"), ("score_engagement", "互动"), ("score_audience", "受众"),
            ("score_content", "内容"), ("score_value", "性价比"), ("score_total", "总分")]
    if not any((r.get(k) or "").strip() for k, _ in keys):
        return ""
    cells = " | ".join(f"{lab} {r.get(k) or '—'}" for k, lab in keys)
    return f"\n## 打分\n\n{cells}\n"


def section_log(r):
    log = (r.get("log_outreach") or "").strip()
    if not log:
        return ""
    out = "\n## 沟通记录\n\n"
    for item in [x.strip() for x in log.split("；") if x.strip()]:
        out += f"- {item}\n"
    return out


def section_mail(cid, audit, replies, drafts):
    """按时间顺序把发出去的和收回来的邮件拼成一条时间线。"""
    events = []
    for a in audit:
        if a.get("id") != cid or a.get("mode") != "live":
            continue
        body = (drafts.get(cid) or {}).get(a.get("body_sha256"))
        events.append((a["ts"], "out", a, body))
    for r in replies:
        if r.get("creator_id") != cid:
            continue
        events.append((r.get("date_iso") or r.get("fetched_at", ""), "in", r, None))
    if not events:
        return ""
    events.sort(key=lambda e: e[0])

    out = "\n## 邮件往来\n\n"
    for ts, kind, rec, body in events:
        if kind == "out":
            label = "回信" if rec.get("kind") == "reply" else "冷邮件"
            out += f"### → 我方发出 · {label} · {rec['ts']}\n\n"
            out += f"**收件人**：{rec['to']}　**主题**：{rec['subject']}\n\n"
            out += f"`message-id: {rec.get('smtp_message_id') or '（未记录）'}`\n\n"
            if body:
                out += "```\n" + body["body"] + "\n```\n\n"
            else:
                # 对不上说明草稿文件被改过或删了——审计日志的哈希才是权威。
                out += (f"> ⚠ 正文未能从草稿文件还原（body_sha256 "
                        f"`{rec.get('body_sha256', '')[:16]}…` 无匹配）。"
                        f"审计日志证明发生过这次发送，但原文需另行查证。\n\n")
        else:
            tag = {"reply": "对方回信", "bounce": "⚠ 退信",
                   "auto_reply": "自动回复"}.get(rec.get("kind"), rec.get("kind"))
            out += f"### ← {tag} · {rec.get('date') or rec.get('fetched_at')}\n\n"
            out += f"**来自**：{rec.get('from')}　**主题**：{rec.get('subject')}\n\n"
            out += f"匹配方式：{rec.get('matched_by')}\n\n"
            if rec.get("body_excerpt"):
                out += "```\n" + rec["body_excerpt"] + "\n```\n\n"
    return out


def build(cid, r, audit, replies, drafts, existing):
    head = (f"# {cid} · {r['name']}\n\n"
            f"> 由 `scripts/build_dossier.py` 生成于 {datetime.date.today().isoformat()}。\n"
            f"> 机器区（本行以下到人工区分隔线之间）重跑会覆盖，**改数据请改 "
            f"`data/db_intl.csv`**，那里才是唯一事实来源。\n\n")
    machine = (head + section_profile(r) + section_scores(r) + section_log(r)
               + section_mail(cid, audit, replies, drafts))
    if (r.get("notes") or "").strip():
        machine += f"\n## 内部备注（notes 列）\n\n{r['notes'].strip()}\n"

    manual = MANUAL_TEMPLATE
    if existing and MANUAL_MARK in existing:
        manual = existing.split(MANUAL_MARK, 1)[1]
    return machine + "\n---\n\n" + MANUAL_MARK + manual


def main():
    ap = argparse.ArgumentParser(description="生成博主档案 md（不抓取网页）")
    ap.add_argument("--db", default=os.path.join(ROOT, "data/db_intl.csv"))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--ids", help="逗号分隔，只出这些人")
    ap.add_argument("--sent", action="store_true",
                    help="扩到所有实发过邮件的人（默认只出收到过实质回信的）")
    ap.add_argument("--all", action="store_true", help="全库都出")
    a = ap.parse_args()

    db = load_db(a.db)
    audit = load_jsonl(os.path.join(ROOT, "data/outreach_sent.jsonl"))
    replies = load_jsonl(os.path.join(ROOT, "data/replies.jsonl"))
    drafts = load_all_drafts()

    if a.ids:
        ids = [x.strip() for x in a.ids.split(",") if x.strip()]
        missing = [i for i in ids if i not in db]
        if missing:
            sys.exit(f"库里没有: {missing}")
    elif a.all:
        ids = sorted(db)
    elif a.sent:
        ids = sorted({r["id"] for r in audit if r.get("mode") == "live"} & set(db))
    else:
        # 默认只给**收到过实质回信**的人建档（2026-08-13 维护者定的口径）。
        # 一开始是"发过邮件就建"，结果 12 份里 9 份人工区全空——发出去还没回音的人，
        # 档案里除了 CSV 已有的内容什么都没有，纯属多一个要维护的地方。
        # 有来信才有东西可记：报价、条款、他们给的链接、要判断的东西。
        # 退信和自动回复不算实质回信。
        ids = sorted({r["creator_id"] for r in replies
                      if r.get("kind") == "reply"} & set(db))

    os.makedirs(a.out, exist_ok=True)
    kept = 0
    for cid in ids:
        r = db[cid]
        # 文件名带昵称，在 Finder 里翻的时候编号本身认不出人
        slug = re.sub(r"[^\w\-]+", "-", (r["name"].split("(")[0].strip() or cid))[:40].strip("-")
        path = os.path.join(a.out, f"{cid}_{slug}.md")
        existing = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if existing and MANUAL_MARK in existing:
            kept += 1
        open(path, "w", encoding="utf-8").write(build(cid, r, audit, replies, drafts, existing))
    print(f"✓ {len(ids)} 份档案写入 {a.out}")
    if kept:
        print(f"  其中 {kept} 份已有人工区，内容原样保留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
