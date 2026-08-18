#!/usr/bin/env python3
"""拉取收件箱、把回信归属到候选、检测退信——闭合"发出去之后就断了"那一环。

为什么允许连网：读 IMAP 不属于「纯处理，不抓取」禁止的范围（见 docs/decisions.md
2026-08-12 条）。那条纪律针对的是"抓平台页面要浏览器+登录态+风控预算"，而这里只连
邮件服务器、读自己的邮箱、不碰任何创作者平台。**本脚本不访问任何社媒平台。**

匹配靠协议不靠猜：对方回信的 In-Reply-To / References 会带上我们发信时的 Message-ID，
审计日志里存着每封的 message-id，两边精确对上。取不到才退回"发件人邮箱 vs 库内 email"。

三条隐私约束（刻意写死在实现里）：
  1. 只报告匹配上的回信与退信；收件箱其余邮件**只计数，不输出任何内容**。
     读邮箱是为了闭环，不是为了把私人邮件摊到终端或对话里。
  2. 剥掉引用段（"On … wrote:" 之后），只留对方真正写的内容，不把我们的原文回显存一遍。
  3. 正文截断到 --max-body 字符（默认 2000）。回信是第三方私人通信，存够判断即可。
     data/replies.jsonl 不会进模板版（导出只复制 data/*.csv 且只留表头，已验证）。

用法:
  python3 fetch_replies.py                          # 演练：只报告，不写文件、不改库
  python3 fetch_replies.py --write                  # 写 data/replies.jsonl
  python3 fetch_replies.py --write --mark           # 并把匹配上的 status 推到「已回复」
  python3 fetch_replies.py --since 2026-08-01       # 指定起始日期（默认首封实发日）
"""
import argparse, email, imaplib, json, os, re, ssl, sys, datetime
from email.header import decode_header, make_header

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml --break-system-packages")

import outreach_batch
from outreach_send import AUDIT_LOG, read_audit, live_sends, credential_path, read_password

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLIES = os.path.join(ROOT, "data", "replies.jsonl")

# 退信/自动回复的判定线索。宁可多标一个"疑似"让人看，也不要把退信当成"没回复"——
# "对方没收到"和"收到了不想回"是两种完全不同的情况，后续动作也不同。
BOUNCE_FROM = ("mailer-daemon", "postmaster", "mail delivery", "microsoftexchange")
BOUNCE_SUBJ = ("undeliverable", "delivery status notification", "returned mail",
               "delivery has failed", "failure notice", "退信", "无法投递")
# 2026-08-17 补：原表认不出「Responses will be delayed」，把 INTL-015 的外出自动回复
# 当成真回信记了下来（--mark 会据此推进 status）。真回信随后就到所以没出事，但
# 只收到自动回复的情况下，库里会凭空多一个「已回复」。宁可多标一个疑似让人看，
# 也不要把机器人当成人。
AUTO_SUBJ = ("out of office", "automatic reply", "auto-reply", "autoreply", "自动回复",
             "will be delayed", "response delayed", "responses will be", "away from",
             "vacation", "on leave", "currently traveling", "limited access to email",
             "外出", "休假", "暂离")


def dec(raw):
    """邮件头解码，失败就原样返回——宁可显示乱码也不要因为一个头崩掉整轮。"""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def plain_body(msg):
    """取纯文本正文；只有 HTML 时粗剥标签。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    h = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace")
                    return re.sub(r"<[^>]+>", " ", h)
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", "replace")
    except Exception:
        return str(msg.get_payload())


QUOTE_MARKERS = [
    r"\nOn .{0,80}wrote:",          # Gmail 英文
    r"\n-{2,}\s*Original Message",
    r"\n>{1,}\s",                    # 引用前缀
    r"\n发件人[:：]",                # 中文客户端
    r"\nFrom: .{0,80}\n",
    r"\nThis e-mail \(including any enclosures\) is confidential",  # 飞书自动追加的免责声明
]


def strip_quotes(text):
    """砍掉引用段与自动追加的免责声明，只留对方真正写的部分。"""
    cut = len(text)
    for pat in QUOTE_MARKERS:
        m = re.search(pat, text)
        if m:
            cut = min(cut, m.start())
    return re.sub(r"\n{3,}", "\n\n", text[:cut]).strip()


def load_replies():
    if not os.path.exists(REPLIES):
        return []
    return [json.loads(l) for l in open(REPLIES, encoding="utf-8") if l.strip()]


def classify(frm, subj):
    f, s = frm.lower(), subj.lower()
    if any(b in f for b in BOUNCE_FROM) or any(b in s for b in BOUNCE_SUBJ):
        return "bounce"
    if any(a in s for a in AUTO_SUBJ):
        return "auto_reply"
    return "reply"


def main():
    ap = argparse.ArgumentParser(description="拉回信 + 归属匹配 + 退信检测（不碰社媒平台）")
    ap.add_argument("--preset", default=os.path.join(ROOT, "presets/roadtrip-intl.yaml"))
    ap.add_argument("--db", default=os.path.join(ROOT, "data/db_intl.csv"))
    ap.add_argument("--since", help="起始日期 YYYY-MM-DD，默认取首封实发日")
    ap.add_argument("--mailbox", default="INBOX")
    ap.add_argument("--max-body", type=int, default=2000, dest="max_body")
    ap.add_argument("--write", action="store_true", help="写 data/replies.jsonl（默认只报告）")
    ap.add_argument("--mark", action="store_true",
                    help="把匹配上的 id 推进到「已回复」（需同时 --write）")
    a = ap.parse_args()

    preset = yaml.safe_load(open(a.preset, encoding="utf-8"))
    smtp = preset.get("outreach", {}).get("smtp") or {}
    host = smtp.get("imap_host") or (smtp.get("host") or "").replace("smtp.", "imap.")
    port = smtp.get("imap_port", 993)
    sender = preset["outreach"]["sender"]
    pw, src = read_password(preset)
    if not pw:
        sys.exit("✗ 没找到口令。先跑 outreach_send.py set-password")

    audit = live_sends(read_audit())
    if not audit:
        sys.exit("审计日志里没有实发记录，无从匹配。")
    # message-id → 候选 id；顺带按发件人邮箱建兜底索引
    by_mid = {r["smtp_message_id"]: r["id"] for r in audit if r.get("smtp_message_id")}
    by_addr = {r["to"].lower(): r["id"] for r in audit}
    since = a.since or min(r["ts"][:10] for r in audit)
    since_imap = datetime.date.fromisoformat(since).strftime("%d-%b-%Y")

    print(f"  口令来源: {src}")
    print(f"  连接 {host}:{port}，邮箱 {sender['sender_email']}，自 {since} 起")
    ctx = ssl.create_default_context()
    with imaplib.IMAP4_SSL(host, port, ssl_context=ctx) as M:
        M.login(sender["sender_email"], pw)
        M.select(a.mailbox, readonly=True)      # readonly：绝不改动邮箱状态
        typ, data = M.search(None, f'(SINCE {since_imap})')
        uids = data[0].split() if data and data[0] else []
        print(f"  {a.mailbox} 内 {since} 之后共 {len(uids)} 封，逐封检查归属…\n")

        seen_mid = {r["message_id"] for r in load_replies()}
        hits, bounces, autos, unrelated, dup = [], [], [], 0, 0
        for uid in uids:
            typ, d = M.fetch(uid, "(RFC822)")
            if not d or not isinstance(d[0], tuple):
                continue
            msg = email.message_from_bytes(d[0][1])
            mid = (msg.get("Message-ID") or "").strip()
            refs = (msg.get("In-Reply-To") or "") + " " + (msg.get("References") or "")
            frm = dec(msg.get("From"))
            subj = dec(msg.get("Subject"))
            addr = (re.search(r"[\w\.\-\+]+@[\w\.\-]+", frm) or [""])
            addr = addr.group(0).lower() if hasattr(addr, "group") else ""

            cid = next((cid for m, cid in by_mid.items() if m and m in refs), None)
            how = "In-Reply-To"
            if not cid:
                cid = by_addr.get(addr)
                how = "发件人邮箱兜底"
            kind = classify(frm, subj)
            if kind == "bounce":
                # 退信里原收件人常在正文/头里，尽力提取
                body_all = plain_body(msg)
                for m, c in by_mid.items():
                    if m and m in body_all:
                        cid = cid or c
                        how = "退信正文含原 message-id"
                        break
            if not cid:
                unrelated += 1          # 无关邮件：只计数，绝不输出内容
                continue
            if mid in seen_mid:
                dup += 1
                continue

            body = strip_quotes(plain_body(msg))[:a.max_body]
            rec = {"fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
                   "creator_id": cid, "kind": kind, "matched_by": how,
                   "message_id": mid, "from": frm, "subject": subj,
                   "date": dec(msg.get("Date")), "body_excerpt": body}
            {"reply": hits, "bounce": bounces, "auto_reply": autos}[kind].append(rec)

    print(f"=== 结果 ===")
    print(f"  回信 {len(hits)} · 退信 {len(bounces)} · 自动回复 {len(autos)} · "
          f"已记录过 {dup} · 与本轮无关 {unrelated}（不显示内容）")
    for r in hits + bounces + autos:
        tag = {"reply": "回信", "bounce": "⚠ 退信", "auto_reply": "自动回复"}[r["kind"]]
        print(f"\n  [{tag}] {r['creator_id']}  匹配方式：{r['matched_by']}")
        print(f"    来自 {r['from'][:60]} | {r['subject'][:60]}")
        if r["body_excerpt"]:
            for line in r["body_excerpt"].split("\n")[:6]:
                print(f"    | {line[:96]}")

    if not a.write:
        print("\n（演练，未写文件、未改库。加 --write 才落盘。）")
        return 0

    os.makedirs(os.path.dirname(REPLIES), exist_ok=True)
    with open(REPLIES, "a", encoding="utf-8") as f:
        for r in hits + bounces + autos:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n✓ 已写入 {os.path.relpath(REPLIES, ROOT)}（{len(hits+bounces+autos)} 条）")

    if bounces:
        ids = sorted({r["creator_id"] for r in bounces})
        outreach_batch.log_note(a.db, ids, datetime.date.today().isoformat(),
                                "冷邮件退信（IMAP 检测）：对方未收到，需核对邮箱或改走其它渠道")
        print(f"  ⚠ 退信已登记进 log_outreach: {ids}")
        print(f"    注意：退信不是「没回复」，status 未推进——需要人决定换邮箱还是换渠道。")
    if a.mark and hits:
        ids = sorted({r["creator_id"] for r in hits})
        res = outreach_batch.mark_replied(a.db, ids, datetime.date.today().isoformat(),
                                          "IMAP 检测到回信")
        print(f"  status 已私信 → 已回复: {res['advanced']}")
        if res["kept"]:
            print(f"  保持不动（已在更靠后阶段）: {res['kept']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
