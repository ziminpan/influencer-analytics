#!/usr/bin/env python3
"""批量生成冷邮件草稿 + 登记已发送。本脚本自己不发信。

发送归 `outreach_send.py`（五道护栏，2026-08-11 起放开代发，见 decisions.md 同日条）。
本脚本刻意不含任何 SMTP 调用：生成、发送、登记三件事分开，改一件不至于动到另两件。

两个子命令：
  generate    读 db_intl.csv 指定 id 名单 + hooks 文件 + preset 产品信息，
              渲染成可直接复制粘贴的草稿，写到一个 markdown 文件里，人工逐份过一遍再发。
  log-note    往 log_outreach 追加任意事件记录（核验结论、口径变更、人工观察），
              不改任何其它字段。给"值得留痕但不属于已发/已回/跳过"的事用。
  mark-skipped 本轮决定不走某渠道触达此人，写明原因；**不改 status**
              （跳过一个渠道 ≠ 否定这个人，她仍可走别的渠道或改写文案再谈）。
  mark-replied 对方回信后登记：追加 log_outreach，并把 status 已私信→已回复。
              发出去之后系统本来是断的（status 永远停在已私信），这条补上那一环。
  mark-sent   确认某批 id 已发出后登记：追加 log_outreach（append-only），
              并在两条保护下推进 status / first_contact_date（详见 mark_sent() 注释）。
              `outreach_send.py` 真发成功后会直接调用同一个 mark_sent() 函数，
              所以这个子命令主要给"浏览器代填 + 人工点发送"那条路径用。

用法:
  python outreach_batch.py generate --db data/db_intl.csv --preset presets/roadtrip-intl.yaml \
      --hooks hooks.json --ids INTL-001,INTL-004,INTL-006 --out drafts.md

  python outreach_batch.py mark-sent --db data/db_intl.csv \
      --ids INTL-001,INTL-004 --date 2026-08-11 --channel "冷邮件"

hooks.json 格式（人工/LLM 判断产出，脚本不自动从 notes 摘要——notes 是内部审计文本，
不是给博主看的营销文案，两者不能划等号）：
  {"INTL-001": "your Vancouver Island hiking + road trip content (and @shehikesvi)"}
"""
import argparse, csv, json, re, sys, datetime

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml --break-system-packages")

ASK_BLOCK = """If you're open to it, three quick things:

1. Flat rate for one piece (whichever format you'd usually recommend: Reel, static, whatever fits your feed).
2. Earliest slot you've got.
3. Usage rights. We'd want to repost on our own channels with credit, is that in the rate or separate? Asking upfront so nobody gets surprised later.

We hand you the demo material so it's low-lift on your end, and we're not trying to change how you normally post. If it doesn't feel like you, it's not worth either of our time.

Either way, love what you're putting out there."""


def load_db(path):
    with open(path, encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def load_preset(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_display_name(raw):
    # db_intl.csv 的 name 列两种格式并存，取真名的位置不同：
    #   "handle (Real Name)"   → 真名在括号里         例：somehandle (Firstname)
    #   "Real Name | 描述"     → 真名在竖线前          例：Firstname | 地区 Outdoors & Travel
    #   纯 handle，两者都没有  → 没有真名，落 "there"   例：firstnamelastname
    #
    # 取到之后**只留名不留姓**：冷邮件里 "Hi <名> <姓>," 读起来像群发通知，
    # "Hi <名>," 才是人写的。2026-08-11 手改过一次带姓的称呼，但只改了产出文件
    # 没改这里，于是 08-12 生成第二批时又冒出带姓的称呼 ——
    # 修产物不修生成器，同一个毛病每批复发一次。
    # 例外：并列名（`<名A> & <名B>` 形态）整体保留，砍掉一半就成了失礼。
    import re
    m = re.search(r"\(([^)]+)\)", raw)
    if m:
        name = m.group(1).strip()
    elif "|" in raw:
        name = raw.split("|")[0].strip()
    else:
        return "there"
    if re.search(r"\s(&|and)\s", name, re.I):     # 并列名整体保留
        return name
    return name.split()[0] if name.split() else "there"


def make_subject(row, hook, product, subjects):
    """标题优先取 subjects.json 里的人工定制值；没有才退回通用式。

    2026-08-11 踩过：generate 对所有人写死同一个标题，6 封共用一句
    "Quick one about a road-trip collab — <公司>"。新域名零冷发历史下，
    跨收件人完全相同的标题是明确的群发信号。当时只改了产出文件，没改这里，
    于是 2026-08-12 生成第二批时**同样的 7 封又全部撞在一起**——
    修产物不修生成器，同一个 bug 就会每批复发一次。
    """
    custom = (subjects or {}).get(row["id"], "").strip()
    if custom:
        return custom
    return "Quick one about a road-trip collab, " + product["brand_name"]


def render_email(row, hook, product, sender, subjects=None):
    name_line = parse_display_name(row["name"])
    subject = make_subject(row, hook, product, subjects)
    # 开场句必须对 hook 的单复数免疫。旧写法是 "and {hook} was one of the ones…"，
    # hook 的中心词是单数时没问题（content / build），一旦是复数就出语法错：
    # "your Sequoia / Yosemite highlights ... was one of the ones" —— 2026-08-12 实测撞上，
    # 而 INTL-088 的 "highlights and the multi-state routes" 会再撞一次。
    # "I kept coming back to {hook}." 不含系动词，单复数都成立，从结构上根除这类错，
    # 而不是逐条去改 hook 的措辞（改 hook 是补丁，下一批还会犯）。
    opener = (f"I've been going through a lot of road-trip / outdoors accounts this week, "
              f"and I kept coming back to {hook}."
              if hook else
              "I've been going through a lot of road-trip / outdoors accounts this week, "
              "and I kept coming back to yours.")
    body = f"""Hi {name_line},

{opener}

I'm {sender['sender_name']}, I work on {product['product_name']} at {product['brand_name']}. It's a free, open-source AI trip planner ({product['web_fallback']}, code at {product['repo_url']}). {product['feature_pitch_email'].strip()}

{ASK_BLOCK}

{sender['sender_name']}
{sender['sender_title']}, {product['brand_name']}
{sender['sender_email']}"""
    return subject, body


def cmd_generate(args):
    db = load_db(args.db)
    preset = load_preset(args.preset)
    product = preset["product"]
    sender = preset["outreach"]["sender"]
    if not sender.get("domain_auth_verified"):
        sys.exit("[拒绝] domain_auth_verified 仍为 false，冷邮件门禁未解除，不生成草稿。")

    hooks = {}
    if args.hooks:
        with open(args.hooks, encoding="utf-8") as f:
            hooks = json.load(f)
    subjects = {}
    if args.subjects:
        with open(args.subjects, encoding="utf-8") as f:
            subjects = json.load(f)

    ids = args.ids.split(",")
    missing_hooks, missing_email, missing_id, _subjects_used = [], [], [], []
    out_lines = [f"# 触达草稿批次 · 生成于 {datetime.date.today()}",
                 "", "> 仅供人工逐份审阅后手动发送，本文件不代表已发送。", ""]

    for _id in ids:
        _id = _id.strip()
        row = db.get(_id)
        if not row:
            missing_id.append(_id)
            continue
        if not row.get("email"):
            missing_email.append(_id)
            continue
        hook = hooks.get(_id, "")
        if not hook:
            missing_hooks.append(_id)
        subject, body = render_email(row, hook, product, sender, subjects)
        _subjects_used.append(subject)
        out_lines += [
            f"## {_id} · {row['name']}",
            f"To: {row['email']}",
            f"Subject: {subject}", "",
            "```", body, "```", "",
        ]

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))

    print(f"生成 {len(ids) - len(missing_id) - len(missing_email)} 份草稿 → {args.out}")
    if missing_id:
        print(f"[跳过] 库里找不到的 id: {missing_id}")
    if missing_email:
        print(f"[跳过] 无邮箱的 id: {missing_email}")
    dup = [k for k in set(s for s in _subjects_used) if list(_subjects_used).count(k) > 1]
    if dup:
        print(f"[警告] 以下标题被多个收件人共用，是群发信号，建议改开: {dup}")
    if missing_hooks:
        print(f"[提醒] 以下 id 在 hooks.json 里没有定制钩子，用了空白开场，建议人工补一句再发: {missing_hooks}")


# 日志里代表"确实碰过这个人"的事件词。核验、入库、政策迁移都不算触达。
CONTACT_MARKERS = ("私信", "冷邮件", "触达", "邮件已", "已发送")
# log_outreach 的分隔符有两层：外层 ；，内层 |。**两层都要切**——
# 只切 ； 会让一段里塞着两个事件（如"2026-07-28 入库 | 2026-08-13 IG私信触达"），
# 取到段首那个入库日期而不是私信日期。2026-08-14 实际踩到，3 个人被填了错误的首触日。
LOG_SPLIT = re.compile(r"[；|]")


def earliest_contact_date(log_outreach):
    """从 log_outreach 里取**最早一次真实触达**的日期，取不到返回 None。

    为什么不能直接用"今天"：first_contact_date 的语义是首次触达日，而同一个人常常
    先走私信、后走邮件。2026-08-14 实测：8 个人在 08-11/08-13 已收过 IG 私信，
    当天补发邮件时该字段为空，于是全被填成 08-14，把首触日整体推后了 1–3 天。
    漏斗时长、跟进间隔、"多久没回"这些判断全建立在这个字段上，填错就全错。

    只认 CONTACT_MARKERS 里的事件词：入库、登录态核验、政策迁移都不是触达。
    """
    if not log_outreach:
        return None
    found = []
    for seg in LOG_SPLIT.split(log_outreach):
        if not any(k in seg for k in CONTACT_MARKERS):
            continue
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", seg)
        if m:
            found.append(m.group(1))
    return min(found) if found else None


def mark_sent(db_path, ids, date, channel="冷邮件"):
    """登记"已发送"：追加 log_outreach，并在保护下推进 status / first_contact_date。

    这是**唯一**的登记入口——`outreach_send.py` 真发成功后直接调用本函数，
    浏览器代填路径（playbooks/email-send.md 路径 A）走 CLI 的 mark-sent 子命令。
    两条路径共用同一份逻辑，避免"两个地方各写一遍、日后改一处漏一处"。
    返回 dict 供调用方打印。
    """
    with open(db_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    ids = set(ids)
    hit, advanced, kept, dated = [], [], [], []
    for row in rows:
        if row["id"] not in ids:
            continue
        note = f"{date} {channel}已人工发送确认"
        row["log_outreach"] = (row["log_outreach"] + "；" + note) if row.get("log_outreach") else note
        hit.append(row["id"])

        # 2026-08-11 起：确认发出后自动推进 status 与 first_contact_date。
        # 这两列原本是人类列，维护者决定让登记这一步代写（见 decisions.md 同日条），
        # 因为"审计日志说已发、库里还写待触达"会让漏斗虚高、并让下一批草稿重复选中同一人。
        # 两条保护，缺一不可：
        #   ① 只从「待触达」推进到「已私信」。已回复/已报价/洽谈中等后段状态一律不动——
        #      否则重跑一次会把人从「已回复」倒退回「已私信」，属于毁数据。
        #   ② first_contact_date 只在为空时填，且**填的是日志里最早那次触达的日期**，
        #      不是今天。见下面 earliest_contact_date() 的注释。
        if row.get("status") == "待触达":
            row["status"] = "已私信"
            advanced.append(row["id"])
        elif row.get("status") != "已私信":
            kept.append(f"{row['id']}({row.get('status')})")
        if not (row.get("first_contact_date") or "").strip():
            row["first_contact_date"] = earliest_contact_date(row["log_outreach"]) or date
            # 记实际写进去的值，不是传入的 date。两者常常不同——同一个人先私信后邮件时，
            # 首触日是私信那天。只打 date 会让人以为字段被填成了今天（实测误导过一次）。
            dated.append((row["id"], row["first_contact_date"]))

    with open(db_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    return {"hit": sorted(hit), "advanced": sorted(advanced), "dated": sorted(dated),
            "kept": sorted(kept), "missed": sorted(ids - set(hit))}


def mark_replied(db_path, ids, date, note=""):
    """登记"对方回信了"：追加 log_outreach，并在保护下把 status 推到「已回复」。

    发出去之后系统本来是断的——status 永远停在「已私信」，谁回了全靠人记，
    漏斗因此长期失真。这条命令补上那一环。

    三条保护：
      ① 只从「已私信」推进到「已回复」。已报价/洽谈中/已签约等更靠后的阶段一律不动，
         否则重跑一次会把人从「已报价」倒退回「已回复」，和 mark_sent 是同一类毁数据。
      ② 「待触达」直接拒绝并报错——没发过怎么会有回信？这种十有八九是 id 敲错了，
         静默放过会让一个从没联系过的人凭空变成「已回复」。
      ③ log_outreach 仍是追加式，永不改写历史。
    """
    with open(db_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    ids = set(ids)
    hit, advanced, kept, refused = [], [], [], []
    for row in rows:
        if row["id"] not in ids:
            continue
        if row.get("status") == "待触达":
            refused.append(f"{row['id']}(待触达——从未发出过，疑似 id 敲错)")
            continue
        suffix = f"：{note}" if note else ""
        row["log_outreach"] = ((row["log_outreach"] + "；" if row.get("log_outreach") else "")
                               + f"{date} 收到回信{suffix}")
        hit.append(row["id"])
        if row.get("status") == "已私信":
            row["status"] = "已回复"
            advanced.append(row["id"])
        elif row.get("status") != "已回复":
            kept.append(f"{row['id']}({row.get('status')})")

    with open(db_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    return {"hit": sorted(hit), "advanced": sorted(advanced), "kept": sorted(kept),
            "refused": sorted(refused), "missed": sorted(ids - set(hit) - {r.split("(")[0] for r in refused})}


def mark_skipped(db_path, ids, date, reason, channel="冷邮件"):
    """登记"本轮决定不通过某渠道触达此人"，并写明原因。

    **不改 status**：跳过一个渠道 ≠ 否定这个人。direction_only 政策下 `status=待触达`
    表示"值得建立联系"，而这里只是判断"这条渠道不合适"（例：INTL-086 受众 63% 在澳洲，
    而正文通篇讲北美国家公园预订，发过去大概率无效）。改成淘汰会丢失"她仍可走
    Collabstr 或改写文案再谈"这层信息。

    原因写进 log_outreach（追加式、双方都只许追加），**不写 notes**——notes 是人类列，
    脚本不代写，这条例外只开给 status/first_contact_date（见 SKILL.md 第 7 节）。
    """
    with open(db_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    ids, hit = set(ids), []
    for row in rows:
        if row["id"] not in ids:
            continue
        note = f"{date} 本轮跳过{channel}触达：{reason}"
        row["log_outreach"] = (row["log_outreach"] + "；" + note) if row.get("log_outreach") else note
        hit.append(row["id"])

    with open(db_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return {"hit": sorted(hit), "missed": sorted(ids - set(hit))}


def log_note(db_path, ids, date, text):
    """往 log_outreach 追加一条任意事件记录，其余字段一律不动。

    存在的理由：不是每件值得留痕的事都是"已发/已回/跳过"。内容核验结论、口径变更、
    人工观察都属于这一类——它们在 `notes`（人类列，脚本不代写）和三个 mark-* 之间
    没有归宿，于是往往只留在聊天记录里。2026-07-30 的教训是"记在别处 ≠ 在库里"：
    只有落到 data/db_*.csv 才会被 ingest/scoring/report 看见。

    刻意不改 status——事件登记与状态推进是两件事，混在一起会让人无法只记录不推进。
    """
    with open(db_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    ids, hit = set(ids), []
    for row in rows:
        if row["id"] not in ids:
            continue
        note = f"{date} {text}"
        row["log_outreach"] = (row["log_outreach"] + "；" + note) if row.get("log_outreach") else note
        hit.append(row["id"])

    with open(db_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return {"hit": sorted(hit), "missed": sorted(ids - set(hit))}


def cmd_log_note(args):
    res = log_note(args.db, [x.strip() for x in args.ids.split(",")], args.date, args.text)
    print(f"已追加 {len(res['hit'])} 条记录: {res['hit']}（status 未改动）")
    if res["missed"]:
        print(f"[警告] 库里没找到这些 id: {res['missed']}")


def cmd_mark_skipped(args):
    res = mark_skipped(args.db, [x.strip() for x in args.ids.split(",")],
                       args.date, args.reason, args.channel)
    print(f"已登记 {len(res['hit'])} 条跳过记录: {res['hit']}")
    print(f"  status 保持不动——跳过一个渠道不等于否定这个人")
    if res["missed"]:
        print(f"[警告] 库里没找到这些 id: {res['missed']}")
    print("  下一步：跑 scripts/sync_xlsx.py 把它推进管理表（xlsx 是视图，别直接改表）。")


def cmd_mark_replied(args):
    res = mark_replied(args.db, [x.strip() for x in args.ids.split(",")], args.date, args.note or "")
    print(f"已登记 {len(res['hit'])} 条回信记录: {res['hit']}")
    if res["advanced"]:
        print(f"  status 已私信 → 已回复: {res['advanced']}")
    if res["kept"]:
        print(f"  ⚠ 以下已处于更靠后的阶段，status 保持不动（防止倒退）: {res['kept']}")
    if res["refused"]:
        print(f"  ✗ 拒绝登记（从未发出过，请核对 id）: {res['refused']}")
    if res["missed"]:
        print(f"[警告] 库里没找到这些 id: {res['missed']}")
    print("  下一步（可选）：跑 scripts/sync_xlsx.py 把 CSV 推进运营管理表 xlsx。")


def print_mark_sent(res, date):
    print(f"已登记 {len(res['hit'])} 条 log_outreach 追加记录: {res['hit']}")
    if res["advanced"]:
        print(f"  status 待触达 → 已私信: {res['advanced']}")
    if res["dated"]:
        for cid, d in res["dated"]:
            extra = "（取自日志里最早的触达事件，非今天）" if d != date else ""
            print(f"  first_contact_date 填入 {d}: {cid}{extra}")
    if res["kept"]:
        print(f"  ⚠ 以下已处于后段状态，status 保持不动（防止倒退）: {res['kept']}")
    if res["missed"]:
        print(f"[警告] 库里没找到这些 id，未登记: {res['missed']}")
    print("  下一步（可选）：跑 scripts/sync_xlsx.py 把 CSV 推进运营管理表 xlsx。"
          "CSV 是唯一权威，xlsx 是视图，不要手工改表里的触达状态。")


def cmd_mark_sent(args):
    res = mark_sent(args.db, [x.strip() for x in args.ids.split(",")],
                    args.date, args.channel)
    print_mark_sent(res, args.date)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("--db", required=True)
    g.add_argument("--preset", required=True)
    g.add_argument("--hooks")
    g.add_argument("--subjects", help="{id: 标题} 的 JSON；缺省会退回通用标题并告警")
    g.add_argument("--ids", required=True, help="逗号分隔的 id 名单，明确指定范围，不做自动筛选")
    g.add_argument("--out", required=True)
    g.set_defaults(func=cmd_generate)

    n = sub.add_parser("log-note")
    n.add_argument("--db", required=True)
    n.add_argument("--ids", required=True)
    n.add_argument("--date", required=True)
    n.add_argument("--text", required=True, help="要追加的事件记录，逐字写进 log_outreach")
    n.set_defaults(func=cmd_log_note)

    k = sub.add_parser("mark-skipped")
    k.add_argument("--db", required=True)
    k.add_argument("--ids", required=True)
    k.add_argument("--date", required=True)
    k.add_argument("--reason", required=True, help="为什么跳过，会逐字写进 log_outreach")
    k.add_argument("--channel", default="冷邮件")
    k.set_defaults(func=cmd_mark_skipped)

    r = sub.add_parser("mark-replied")
    r.add_argument("--db", required=True)
    r.add_argument("--ids", required=True)
    r.add_argument("--date", required=True)
    r.add_argument("--note", help="回信要点，写进 log_outreach")
    r.set_defaults(func=cmd_mark_replied)

    m = sub.add_parser("mark-sent")
    m.add_argument("--db", required=True)
    m.add_argument("--ids", required=True)
    m.add_argument("--date", required=True)
    m.add_argument("--channel", default="冷邮件")
    m.set_defaults(func=cmd_mark_sent)

    args = p.parse_args()
    args.func(args)
