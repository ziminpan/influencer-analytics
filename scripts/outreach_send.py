#!/usr/bin/env python3
"""逐份发送冷邮件——五道护栏下的受控发送（2026-08-11 维护者决策放开，见 decisions.md）。

此前的红线是"代理绝不点发送"。放开这条的前提是维护者同意了五道护栏，本脚本就是那五道：

  1. 默认 dry-run          send 不带 --live 只演练，不碰 SMTP。
  2. 逐份确认最终全文      --confirm <token>，token 是「收件人+标题+正文」的哈希，
                           由 preview 打印。文本改一个字 token 就变，没预览过的内容发不出去。
  3. 硬性日上限            preset 的 pacing.daily_email_cap，按审计日志里今天的实发数计。
  4. 完整审计日志          data/outreach_sent.jsonl，append-only，含正文哈希与 SMTP message-id。
  5. 随时可停的开关        data/OUTREACH_HALT 存在即拒发；halt / resume 子命令控制。

**发什么就是你审过的什么**：正文不在这里重新渲染，而是直接从 `outreach_batch.py generate`
产出的草稿 md 里逐字读取。重新渲染会引入「你审的版本」与「实际发出的版本」漂移的可能，
那正是逐份确认要防的事。

逐份推进的循环（推荐用法，一次只处理一个人）：
  python3 outreach_send.py next --drafts drafts.md          # 自动找下一个未发的，打印全文+令牌
  → 人读全文 → 粘贴它给出的 send --live 命令 → 发完自动登记 → 再 next

真发成功后会**自动调用 outreach_batch.mark_sent()** 登记（追加 log_outreach、
在保护下推进 status/first_contact_date），不需要再手动跑一次 mark-sent——
那一步是纯记账，忘了跑就会出现"审计日志说已发、库里还写待触达"的不一致。

全部子命令:
  python3 outreach_send.py list    --drafts drafts.md          # 清单+进度（只给 4 位指纹）
  python3 outreach_send.py next    --drafts drafts.md          # 下一个未发的全文
  python3 outreach_send.py preview --drafts drafts.md --id INTL-003
  python3 outreach_send.py send    --drafts drafts.md --id INTL-003 --confirm a1b2c3d4        # 演练
  python3 outreach_send.py send    --drafts drafts.md --id INTL-003 --confirm a1b2c3d4 --live # 真发
  python3 outreach_send.py reply   --drafts replies_out.md --id INTL-057 --confirm <token> --live
                                   # 回信：挂进原会话（In-Reply-To），护栏按回信语义调整
  python3 outreach_send.py halt / resume / log
  python3 outreach_send.py set-password / check-smtp

口令配置（一次性，之后不用再管）：
  python3 outreach_send.py set-password   # 交互式输入，不回显、0600 存本机、不进 history
  python3 outreach_send.py check-smtp     # 只登录不发信，验证口令可用
取值顺序：环境变量 OUTREACH_SMTP_PASSWORD > preset 的 outreach.smtp.password_file。
口令永不写进仓库、日志或任何输出——只打印长度与 sha256 前 8 位。
"""
import argparse, hashlib, json, os, re, smtplib, ssl, sys, datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr, make_msgid

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml --break-system-packages")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_LOG = os.path.join(ROOT, "data", "outreach_sent.jsonl")
HALT_FILE = os.path.join(ROOT, "data", "OUTREACH_HALT")
ENV_PASSWORD = "OUTREACH_SMTP_PASSWORD"   # SMTP 主机/端口读 preset 的 outreach.smtp，不写死

# 允许发冷邮件的 status。**白名单不是黑名单**：将来新增状态默认发不出去，
# 要放行必须显式加进来，比"列出所有禁止项、漏一个就放行"安全。
#
# 「已私信」在列，是因为 status 是跨渠道的单一字段，分不清"发过邮件"和"发过私信"。
# 2026-08-14 实测撞上：INTL-015 走 IG 私信触达后，对方在私信里给了邮箱要求改走邮件，
# 那是换渠道续同一段对话，不是重复触达，却被"必须等于待触达"挡死。
# 防重复发送真正靠的是下面那条——审计日志里查同一 id 有没有 live 邮件记录，
# 那条判据直接、准确，且不受 status 怎么写影响。
SENDABLE_STATUS = {"待触达", "已私信"}

# 处于会话中的状态：这些人**正在等我们答复**，发信前必须确认收件箱里没有新回信。
# 2026-08-18 实测代价：对方 00:05 发来完整方案与档期，我方 10:03 回「还没有 brief」，
# 10:14 才抓收件箱。同一线程里那两封挨在一起读起来是婉拒，而邮件发出不可撤回。
IN_CONVERSATION = {"已回复", "洽谈中", "待老板审批", "已报价"}
INBOX_STALE_SECONDS = 30 * 60      # 收件箱抓取超过这个时长即视为过期


# ---------- 草稿解析：只认 outreach_batch.py generate 的格式 ----------

def parse_drafts(path):
    """→ {id: {"name","to","subject","body"}}；正文取围栏代码块内的原文。"""
    text = open(path, encoding="utf-8").read()
    out, cur = {}, None
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^##\s+(INTL-\d+|CN-\d+)\s*·\s*(.*)$", line.strip())
        if m:
            cur = {"id": m.group(1), "name": m.group(2).strip(),
                   "to": None, "subject": None, "body": None}
            out[cur["id"]] = cur
            i += 1
            continue
        if cur:
            if line.startswith("To:") and cur["to"] is None:
                cur["to"] = line[3:].strip()
            elif line.startswith("Subject:") and cur["subject"] is None:
                cur["subject"] = line[8:].strip()
            elif line.strip().startswith("```") and cur["body"] is None:
                body, i = [], i + 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    body.append(lines[i])
                    i += 1
                cur["body"] = "\n".join(body).strip("\n")
        i += 1
    incomplete = [k for k, v in out.items()
                  if not (v["to"] and v["subject"] and v["body"])]
    if incomplete:
        sys.exit(f"草稿解析不完整（缺 To/Subject/正文）: {incomplete}")
    return out


def token_of(draft):
    """确认令牌 = 收件人 + 标题 + 正文 的哈希。任一字变化则令牌变化。"""
    raw = f"{draft['to']}\n{draft['subject']}\n{draft['body']}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def body_sha(draft):
    return hashlib.sha256(draft["body"].encode("utf-8")).hexdigest()


# ---------- 审计日志 ----------

def read_audit():
    if not os.path.exists(AUDIT_LOG):
        return []
    out = []
    with open(AUDIT_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append_audit(rec):
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def live_sends(audit):
    return [r for r in audit if r.get("mode") == "live"]


def sent_today(audit, today):
    return [r for r in live_sends(audit) if r["ts"].startswith(today)]


# ---------- 护栏检查 ----------

def inbox_age_seconds():
    """data/replies.jsonl 最近一次抓取距今多久；从未抓过返回 None。"""
    if not os.path.exists(REPLIES_IN):
        return None
    newest = None
    for line in open(REPLIES_IN, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        ts = json.loads(line).get("fetched_at")
        if ts and (newest is None or ts > newest):
            newest = ts
    if not newest:
        return None
    try:
        t = datetime.datetime.fromisoformat(newest)
    except ValueError:
        return None
    return (datetime.datetime.now() - t).total_seconds()


def inbox_check(row, skip):
    """会话中的人：收件箱过期就拒发。返回阻断原因列表。

    只对**正在等我们答复**的人生效。给 `待触达` 的冷发不触发——那些人没在等，
    多一次 IMAP 调用没有意义，而无谓的阻断会让人养成加 --skip 的习惯，
    那等于把这道检查废掉。
    """
    if skip or (row or {}).get("status") not in IN_CONVERSATION:
        return []
    age = inbox_age_seconds()
    if age is None:
        return ["收件箱从未抓取过，而对方正在等答复 → 先跑 "
                "`python3 scripts/fetch_replies.py --write`"]
    if age > INBOX_STALE_SECONDS:
        return [f"收件箱上次抓取在 {age / 60:.0f} 分钟前（超过 "
                f"{INBOX_STALE_SECONDS // 60} 分钟），而对方状态是"
                f"「{row.get('status')}」，正在等我们答复。先跑 "
                f"`python3 scripts/fetch_replies.py --write` 确认没有新回信，"
                f"否则可能出现「我们的信与对方的信交叉」（2026-08-18 实际发生过）"]
    return []


def preflight(draft, preset, db, audit, today):
    """返回阻断原因列表；空列表 = 可以发。"""
    blocks = []
    sender = preset.get("outreach", {}).get("sender", {})
    if not sender.get("domain_auth_verified"):
        blocks.append("preset 的 domain_auth_verified 不为 true——发信域门禁未解除")
    if os.path.exists(HALT_FILE):
        blocks.append(f"急停开关已置位（{os.path.relpath(HALT_FILE, ROOT)} 存在）→ 先 resume")

    cap = preset.get("pacing", {}).get("daily_email_cap")
    if cap is None:
        blocks.append("preset 未配 pacing.daily_email_cap——上限未定义时拒发")
    else:
        n = len(sent_today(audit, today))
        if n >= cap:
            blocks.append(f"今日实发 {n} 封已达上限 {cap}")

    row = db.get(draft["id"])
    if row is None:
        blocks.append(f"{draft['id']} 不在库里")
    else:
        if row.get("status") not in SENDABLE_STATUS:
            blocks.append(f"{draft['id']} 状态是「{row.get('status')}」，"
                          f"不在可发状态 {sorted(SENDABLE_STATUS)} 内")
        db_mail = (row.get("email") or "").strip().lower()
        if db_mail and db_mail != parseaddr(draft["to"])[1].strip().lower():
            blocks.append(f"草稿收件人 {draft['to']} 与库内 email {row['email']} 不一致")

    for r in live_sends(audit):
        if r["id"] == draft["id"]:
            blocks.append(f"{draft['id']} 审计日志里已有实发记录（{r['ts']}）——拒绝重复发送")
            break
    blocks += inbox_check(row, getattr(preflight, "_skip_inbox", False))
    return blocks


# ---------- 子命令 ----------

def cmd_list(args):
    drafts = parse_drafts(args.drafts)
    audit = read_audit()
    done = {r["id"] for r in live_sends(audit)}
    print(f"草稿文件：{args.drafts}　共 {len(drafts)} 份\n")
    for d in drafts.values():
        flag = "已发" if d["id"] in done else "待发"
        # 故意不在这里打印完整令牌：否则可以从清单抄一个令牌直接 --live，
        # 绕过"看过全文才能确认"这道护栏，逐份确认就成了形式。
        # 只给前 4 位做人眼比对（改动过的草稿指纹会变），完整令牌只由 preview 给出。
        print(f"  [{flag}] {d['id']:<10} {d['name'][:26]:<28} {d['to']:<34} "
              f"指纹 {token_of(d)[:4]}…")
    # 只数**本批**已实发的：done 是审计日志里全部历史实发，直接拿来当分子会
    # 把别批的也算进来（实测显示过"已实发 6 / 7"，而这批一封都没发）。
    print(f"\n已实发 {len(done & set(drafts))} / {len(drafts)}")
    print("完整确认令牌只在 preview 里给出——那一步会同时打印将要发出的全文。")


def cmd_preview(args):
    drafts = parse_drafts(args.drafts)
    d = drafts.get(args.id) or sys.exit(f"草稿里没有 {args.id}")
    preset = yaml.safe_load(open(args.preset, encoding="utf-8"))
    db = load_db(args.db)
    audit = read_audit()
    today = datetime.date.today().isoformat()
    sender = preset["outreach"]["sender"]

    print("=" * 72)
    print(f"From:    {formataddr((sender['sender_display'], sender['sender_email']))}")
    print(f"To:      {d['to']}")
    print(f"Subject: {d['subject']}")
    print("-" * 72)
    print(d["body"])
    print("=" * 72)
    blocks = preflight(d, preset, db, audit, today)
    if blocks:
        print("\n✗ 当前会被拒发：")
        for b in blocks:
            print(f"   - {b}")
    else:
        cap = preset["pacing"]["daily_email_cap"]
        print(f"\n✓ 护栏检查通过（今日 {len(sent_today(audit, today))}/{cap}）")
    # 提示命令用 python3：macOS 上 `python` 通常不存在，照抄会直接失败。
    # 整行必须是可以原样粘贴的一整条命令——上一版拆成两行导致过复制错误。
    print(f"\n这就是将要发出的全文。确认无误后，把下面**整整一行**粘贴执行：")
    print(f"\npython3 scripts/outreach_send.py send --drafts {args.drafts} "
          f"--id {d['id']} --confirm {token_of(d)} --live\n")
    print(f"（想先演练就把结尾的 --live 去掉。--confirm 后面只跟令牌 "
          f"{token_of(d)}，不要跟别的东西。）")


def cmd_next(args):
    """找出草稿里下一个还没实发的 id，直接把它的 preview 走一遍。

    只省"找下一个是谁"这点力气——preview 全文和逐份令牌一步都不省。
    刻意一次只处理一个：连着把 5 份都 preview 出来，人就会开始跳读，
    逐份确认会退化成批量。
    """
    drafts = parse_drafts(args.drafts)
    audit = read_audit()
    done = {r["id"] for r in live_sends(audit)}
    remaining = [d for d in drafts.values() if d["id"] not in done]
    if not remaining:
        print(f"草稿里 {len(drafts)} 份全部已实发，没有下一封了。")
        return 0
    nxt = remaining[0]
    print(f"还剩 {len(remaining)} 份未发：{[d['id'] for d in remaining]}")
    print(f"下面是其中第一份 {nxt['id']} 的全文——\n")
    args.id = nxt["id"]
    return cmd_preview(args)


def cmd_send(args):
    drafts = parse_drafts(args.drafts)
    d = drafts.get(args.id) or sys.exit(f"草稿里没有 {args.id}")
    preset = yaml.safe_load(open(args.preset, encoding="utf-8"))
    db = load_db(args.db)
    audit = read_audit()
    today = datetime.date.today().isoformat()
    sender = preset["outreach"]["sender"]

    expected = token_of(d)
    if args.confirm != expected:
        sys.exit(f"✗ 令牌不匹配：你给的是 {args.confirm}，当前草稿是 {expected}。\n"
                 f"  文本可能在你确认之后被改过——请重新 preview 看一遍全文再发。")

    # 确认方式（2026-08-11 第二次修订，见 decisions.md）：
    #   human —— 令牌由人从 preview 搬到命令行。机械保证："只有人看过的文本能发出去"，
    #            因为不显示全文就拿不到有效令牌。
    #   chat  —— 代理在对话里展示全文、用户口头确认、代理代传令牌。此时令牌**不再证明
    #            人看过了**（展示与算令牌是同一方），只剩"展示之后文件未被改动"这一层。
    #            降级是明知的：换来的是少两次复制粘贴（真出过两次复制事故）。
    #            补偿是事后可核查——审计日志记 confirmed_by 与正文哈希，草稿文件进 git，
    #            任何人都能验证"发出的正文哈希 == 文件里的正文哈希"。
    if args.confirmed_by == "chat":
        print("ⓘ 确认方式：对话确认（confirmed_by=chat）。令牌由代理代传，"
              "因此它只保证文件未被改动，不构成「人已阅读」的机械证明；"
              "核查依据是审计日志的正文哈希 + git 里的草稿文件。")

    blocks = preflight(d, preset, db, audit, today)
    if blocks:
        print("✗ 护栏拒发：")
        for b in blocks:
            print(f"   - {b}")
        return 1

    msg = EmailMessage()
    msg["From"] = formataddr((sender["sender_display"], sender["sender_email"]))
    msg["To"] = d["to"]
    msg["Subject"] = d["subject"]
    # 自己生成 Message-ID 再发：不设的话由服务器生成，客户端拿不到，
    # 审计日志里那一栏就是空的——等于无法把一条审计记录和已发信箱里的实信、
    # 或者一封退信/投诉对应起来。护栏 4 承诺了"含 message-id"，就得真的有。
    msg["Message-ID"] = make_msgid(domain=sender["sender_email"].split("@")[-1])
    msg.set_content(d["body"])

    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "id": d["id"], "name": d["name"], "to": d["to"],
           "subject": d["subject"], "body_sha256": body_sha(d),
           "confirm_token": expected, "from": sender["sender_email"],
           "confirmed_by": args.confirmed_by,
           "mode": "live" if args.live else "dry"}

    if not args.live:
        print("— 演练（未连接 SMTP）—")
        print(f"  会发给 {d['to']}，标题《{d['subject']}》，正文 {len(d['body'])} 字符")
        print(f"  正文 sha256 前 16 位：{rec['body_sha256'][:16]}")
        print("  确认要真发就把 --live 加上。")
        append_audit(rec)
        return 0

    pwd, pwd_src = read_password(preset)
    if not pwd:
        sys.exit(f"✗ 没找到 SMTP 口令。跑一次：\n"
                 f"    python3 scripts/outreach_send.py set-password\n"
                 f"  （或设环境变量 {ENV_PASSWORD}）。"
                 f"脚本不接受命令行传口令，避免落进 shell history。")

    smtp = preset.get("outreach", {}).get("smtp") or {}
    host, port = smtp.get("host"), smtp.get("port")
    if not host or not port:
        sys.exit("✗ preset 缺 outreach.smtp.host / port——以飞书生成专用密码时"
                 "弹窗显示的 SMTP 配置为准，填进 preset 再发。")
    ctx = ssl.create_default_context()
    if str(smtp.get("security", "ssl")).lower() == "starttls":
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(sender["sender_email"], pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(sender["sender_email"], pwd)
            s.send_message(msg)
    rec["smtp_message_id"] = msg.get("Message-ID", "")
    rec["smtp_host"] = f"{host}:{port}"
    rec["password_source"] = pwd_src
    append_audit(rec)
    print(f"✓ 已发送 {d['id']} → {d['to']}")
    print(f"  已写入审计日志：{os.path.relpath(AUDIT_LOG, ROOT)}")

    # 发完直接登记，不再要求人另跑一次 mark-sent：那一步是纯记账，忘了跑就会出现
    # "审计日志说已发、库里还写待触达"的不一致（INTL-003 就这么漂过一次）。
    # 复用 outreach_batch.mark_sent()，两条路径共用同一份逻辑与同样的两条保护。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import outreach_batch
    res = outreach_batch.mark_sent(args.db, [d["id"]], today, "冷邮件")
    outreach_batch.print_mark_sent(res, today)
    # 发完直接把下一封的全文摊开（默认行为，--no-next 关闭）。
    # 这只是省掉"手动敲 next"，**不省任何确认**——下一封仍要人看过全文再单独确认。
    # 仍然一次只出一个人：批量 preview 会让人开始跳读，逐份确认就退化成形式了。
    if not args.no_next:
        print("\n" + "─" * 72)
        remaining = [d for d in parse_drafts(args.drafts).values()
                     if d["id"] not in {r["id"] for r in live_sends(read_audit())}]
        if remaining:
            print(f"下一封（还剩 {len(remaining)} 份，确认前不会发）：\n")
            args.id = remaining[0]["id"]
            cmd_preview(args)
        else:
            print("本批草稿已全部发完。")
            print("建议收尾：python3 scripts/sync_xlsx.py --csv data/db_intl.csv "
                  "--xlsx \"<管理表>\" --write")
    return 0


def credential_path(preset):
    """口令文件位置：preset 的 outreach.smtp.password_file，默认 ~/.<公司>_smtp_password。

    preset 里存的是**路径**，不是口令本身——preset 进 git，口令永远不进。
    """
    p = (preset.get("outreach", {}).get("smtp") or {}).get("password_file") \
        or "~/.<公司>_smtp_password"
    return os.path.expanduser(p)


def read_password(preset):
    """取口令：环境变量优先，其次口令文件。两者都无则返回 None。

    文件读出来做 strip：用 echo 写的文件会带尾部换行，混进口令会导致
    认证失败，而报错信息只会说"密码错误"，很难查。
    """
    env = os.environ.get(ENV_PASSWORD)
    if env:
        return env.strip(), "环境变量"
    path = credential_path(preset)
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip(), path
    return None, None


REPLIES_IN = os.path.join(ROOT, "data", "replies.jsonl")


def inbound_of(cid):
    """取该候选最近一封**入站**回信，用于组装 In-Reply-To/References。

    没有入站回信就不该"回复"——那会变成另起一封冷邮件，还伪装成回复。
    """
    if not os.path.exists(REPLIES_IN):
        return None
    got = [json.loads(l) for l in open(REPLIES_IN, encoding="utf-8") if l.strip()]
    mine = [r for r in got if r.get("creator_id") == cid and r.get("kind") == "reply"
            and r.get("message_id")]
    return sorted(mine, key=lambda r: r.get("fetched_at", ""))[-1] if mine else None


def preflight_reply(draft, preset, db, audit, inbound):
    """回信的护栏与冷邮件不同，逐条说明为什么放开或保留：

    - **日上限不适用**：`daily_email_cap` 是冷发的风控预算。回复一个主动写信给你的人
      是最安全的邮件，让冷发额度拦住一封正当回信是本末倒置。改为只记录、不阻断。
    - **"同一 id 不可重发"必须放开**：回信本来就是给同一个人的第二封。改为按
      「同一封入站信 + 同一份正文」去重，防的是重复发同一条回复。
    - **状态检查换成更强的条件**：不再要求 `待触达`，而是要求**确有入站回信**。
      没人写信给你就没有可回的东西——这比看 status 更贴近实质。
    - 域名门禁与急停开关照旧保留。
    """
    blocks = []
    sender = preset.get("outreach", {}).get("sender", {})
    if not sender.get("domain_auth_verified"):
        blocks.append("preset 的 domain_auth_verified 不为 true——发信域门禁未解除")
    if os.path.exists(HALT_FILE):
        blocks.append(f"急停开关已置位（{os.path.relpath(HALT_FILE, ROOT)} 存在）→ 先 resume")
    if inbound is None:
        blocks.append(f"{draft['id']} 没有入站回信记录，无可回复对象"
                      f"（先跑 fetch_replies.py --write；若确要新发一封，用 send 而非 reply）")
    row = db.get(draft["id"])
    if row is None:
        blocks.append(f"{draft['id']} 不在库里")
    elif (row.get("email") or "").strip() and \
            row["email"].strip().lower() != parseaddr(draft["to"])[1].strip().lower():
        blocks.append(f"草稿收件人 {draft['to']} 与库内 email {row['email']} 不一致")
    # 必须过 live_sends：演练也会写审计日志（有意为之，留痕），拿全量记录去重
    # 会让"演练一次"把随后的真发挡死——演练不是发送。冷发路径同理。
    for r in live_sends(audit):
        if r.get("kind") == "reply" and r["id"] == draft["id"] \
                and r.get("in_reply_to") == (inbound or {}).get("message_id") \
                and r.get("body_sha256") == body_sha(draft):
            blocks.append(f"这条回复已发过（{r['ts']}）——同一封来信 + 同一份正文，拒绝重复")
    return blocks


def cmd_reply(args):
    drafts = parse_drafts(args.drafts)
    d = drafts.get(args.id) or sys.exit(f"草稿里没有 {args.id}")
    preset = yaml.safe_load(open(args.preset, encoding="utf-8"))
    db = load_db(args.db)
    audit = read_audit()
    today = datetime.date.today().isoformat()
    sender = preset["outreach"]["sender"]
    inbound = inbound_of(args.id)

    expected = token_of(d)
    if args.confirm != expected:
        sys.exit(f"✗ 令牌不匹配：你给的是 {args.confirm}，当前草稿是 {expected}。\n"
                 f"  回信涉及价格/交付/授权，比冷邮件更不该发未经确认的版本。请重新看全文。")

    print("=" * 72)
    print(f"From:    {formataddr((sender['sender_display'], sender['sender_email']))}")
    print(f"To:      {d['to']}")
    print(f"Subject: {d['subject']}")
    if inbound:
        print(f"挂在会话中: In-Reply-To {inbound['message_id'][:44]}…（{inbound['subject'][:40]}）")
    print("=" * 72)
    blocks = preflight_reply(d, preset, db, audit, inbound)
    if blocks:
        print("✗ 护栏拒发：")
        for b in blocks:
            print(f"   - {b}")
        return 1
    print(f"✓ 护栏通过（回信不占冷发日上限；今日冷发 {len(sent_today(read_audit(), today))} 封）")

    msg = EmailMessage()
    msg["From"] = formataddr((sender["sender_display"], sender["sender_email"]))
    msg["To"] = d["to"]
    msg["Subject"] = d["subject"]
    msg["Message-ID"] = make_msgid(domain=sender["sender_email"].split("@")[-1])
    # 挂进原会话：不设这两个头，回信会另起一个线程，对方看着像新邮件
    msg["In-Reply-To"] = inbound["message_id"]
    msg["References"] = inbound["message_id"]
    msg.set_content(d["body"])

    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
           "id": d["id"], "name": d["name"], "to": d["to"], "subject": d["subject"],
           "body_sha256": body_sha(d), "confirm_token": expected,
           "from": sender["sender_email"], "confirmed_by": args.confirmed_by,
           "kind": "reply", "in_reply_to": inbound["message_id"],
           "mode": "live" if args.live else "dry"}

    if not args.live:
        print("\n— 演练（未连接 SMTP）—")
        print(f"  会回给 {d['to']}，标题《{d['subject']}》，正文 {len(d['body'])} 字符")
        print(f"  正文 sha256 前 16 位：{rec['body_sha256'][:16]}")
        append_audit(rec)
        return 0

    pwd, pwd_src = read_password(preset)
    if not pwd:
        sys.exit(f"✗ 没找到 SMTP 口令。跑 outreach_send.py set-password")
    smtp = preset.get("outreach", {}).get("smtp") or {}
    host, port = smtp.get("host"), smtp.get("port")
    ctx = ssl.create_default_context()
    if str(smtp.get("security", "ssl")).lower() == "starttls":
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx); s.login(sender["sender_email"], pwd); s.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(sender["sender_email"], pwd); s.send_message(msg)
    rec["smtp_message_id"] = msg.get("Message-ID", "")
    rec["smtp_host"] = f"{host}:{port}"
    rec["password_source"] = pwd_src
    append_audit(rec)
    print(f"\n✓ 已回复 {d['id']} → {d['to']}（挂在原会话中）")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import outreach_batch
    outreach_batch.log_note(args.db, [d["id"]], today,
                            f"已回复对方询问（冷邮件线程内）：{d['subject']}")
    print(f"  已追加 log_outreach。**status 未自动推进**——"
          f"「已回复」指对方回了我们；要不要转「洽谈中」由人判断。")
    return 0


def cmd_set_password(args):
    """交互式保存 SMTP 口令到本机文件（不回显、不进 history、不进对话）。"""
    import getpass, stat
    preset = yaml.safe_load(open(args.preset, encoding="utf-8"))
    path = credential_path(preset)
    print(f"口令将保存到：{path}")
    print("（输入时不回显；口令只在你本机，不会进入仓库、shell history 或任何对话记录）")
    pw = getpass.getpass("粘贴飞书邮箱专用密码后回车：").strip()
    if not pw:
        sys.exit("✗ 没有输入，未保存。")
    again = getpass.getpass("再输一次确认：").strip()
    if pw != again:
        sys.exit("✗ 两次输入不一致，未保存。")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(pw)          # 刻意不写换行：尾部换行会混进口令
    mode = oct(os.stat(path).st_mode & 0o777)[-3:]
    print(f"\n✓ 已保存（{len(pw)} 字符，sha256 前 8 位 "
          f"{hashlib.sha256(pw.encode()).hexdigest()[:8]}，权限 {mode}）")
    print("  下一步：python3 scripts/outreach_send.py check-smtp   # 只登录不发信，验证口令")
    return 0


def cmd_check_smtp(args):
    """只连接+登录 SMTP，不发任何邮件——用来验证口令配置对不对。"""
    preset = yaml.safe_load(open(args.preset, encoding="utf-8"))
    pw, src = read_password(preset)
    if not pw:
        sys.exit(f"✗ 没找到口令。先跑：python3 scripts/outreach_send.py set-password\n"
                 f"  （或设环境变量 {ENV_PASSWORD}）")
    smtp = preset.get("outreach", {}).get("smtp") or {}
    sender = preset["outreach"]["sender"]
    host, port = smtp.get("host"), smtp.get("port")
    print(f"  口令来源：{src}")
    print(f"  连接 {host}:{port} 并以 {sender['sender_email']} 登录（不发信）…")
    ctx = ssl.create_default_context()
    try:
        if str(smtp.get("security", "ssl")).lower() == "starttls":
            with smtplib.SMTP(host, port) as s:
                s.starttls(context=ctx)
                s.login(sender["sender_email"], pw)
        else:
            with smtplib.SMTP_SSL(host, port, context=ctx) as s:
                s.login(sender["sender_email"], pw)
    except smtplib.SMTPAuthenticationError as e:
        sys.exit(f"✗ 认证失败：{e}\n"
                 f"  常见原因：专用密码已失效/被重新生成；或管理员未开启"
                 f"「第三方邮箱客户端登录」；或口令文件里混进了换行/空格。")
    except Exception as e:
        sys.exit(f"✗ 连接失败：{type(e).__name__}: {e}")
    print("✓ 登录成功，口令可用。未发送任何邮件。")
    return 0


def cmd_halt(args):
    with open(HALT_FILE, "w", encoding="utf-8") as f:
        f.write(f"halted_at: {datetime.datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"reason: {args.reason or '(未填)'}\n")
    print(f"✓ 急停已置位：{os.path.relpath(HALT_FILE, ROOT)}——所有实发将被拒绝，直到 resume。")


def cmd_resume(args):
    if os.path.exists(HALT_FILE):
        os.remove(HALT_FILE)
        print("✓ 急停已解除。")
    else:
        print("急停本来就没有置位。")


def cmd_log(args):
    audit = read_audit()
    if not audit:
        print("审计日志为空。")
        return
    print(f"共 {len(audit)} 条（实发 {len(live_sends(audit))}）：")
    for r in audit[-args.tail:]:
        print(f"  {r['ts']}  {r['mode']:<4}  {r['id']:<10} {r['to']:<34} {r['subject'][:34]}")


def load_db(path):
    import csv
    with open(path, encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser(description="逐份受控发送（五道护栏）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "preview", "send", "next"):
        p = sub.add_parser(name)
        p.add_argument("--drafts", required=True)
        if name not in ("list", "next"):
            p.add_argument("--id", required=True)
        if name != "list":
            p.add_argument("--preset", default=os.path.join(ROOT, "presets/roadtrip-intl.yaml"))
            p.add_argument("--db", default=os.path.join(ROOT, "data/db_intl.csv"))
        if name == "send":
            p.add_argument("--confirm", required=True, help="preview 打印的令牌")
            p.add_argument("--live", action="store_true", help="不加则只演练")
            p.add_argument("--no-next", action="store_true", dest="no_next",
                           help="发完不自动显示下一封（默认会显示，便于连着过）")
            p.add_argument("--confirmed-by", choices=["human", "chat"], default="human",
                           dest="confirmed_by",
                           help="human=令牌由人从 preview 搬来（机械保证）；"
                                "chat=对话里展示全文后口头确认，代理代传令牌（事后可核查）")
    rp = sub.add_parser("reply")
    rp.add_argument("--drafts", required=True)
    rp.add_argument("--id", required=True)
    rp.add_argument("--confirm", required=True)
    rp.add_argument("--live", action="store_true")
    rp.add_argument("--confirmed-by", choices=["human", "chat"], default="human",
                    dest="confirmed_by")
    rp.add_argument("--preset", default=os.path.join(ROOT, "presets/roadtrip-intl.yaml"))
    rp.add_argument("--db", default=os.path.join(ROOT, "data/db_intl.csv"))

    for nm in ("set-password", "check-smtp"):
        q = sub.add_parser(nm)
        q.add_argument("--preset", default=os.path.join(ROOT, "presets/roadtrip-intl.yaml"))
    h = sub.add_parser("halt"); h.add_argument("--reason")
    sub.add_parser("resume")
    lg = sub.add_parser("log"); lg.add_argument("--tail", type=int, default=20)

    a = ap.parse_args()
    return {"list": cmd_list, "preview": cmd_preview, "send": cmd_send,
            "next": cmd_next, "halt": cmd_halt, "resume": cmd_resume,
            "log": cmd_log, "reply": cmd_reply, "set-password": cmd_set_password,
            "check-smtp": cmd_check_smtp}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
