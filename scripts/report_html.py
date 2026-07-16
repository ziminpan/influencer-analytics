#!/usr/bin/env python3
"""零依赖 HTML 报告：装了 skill 就能跑，不要求任何人装 R。

用法:
    python report_html.py data/db_cn.csv report.html [--now 2026-07-15]
"""
import sys, csv, statistics as st
from datetime import datetime, date, timedelta

TIERS = [("KOC", 0, 10000), ("初级", 10000, 50000),
         ("腰部", 50000, 200000), ("头部", 200000, 10**12)]


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def bar_row(label, n, total, extra=""):
    pct = (n / total * 100) if total else 0
    return (f'<div class="row"><span class="lbl">{esc(label)}</span>'
            f'<span class="bar" style="width:{max(pct,1)*3}px"></span>'
            f'<span class="val">{n}{extra}</span></div>')


def main(path, out, now=None):
    now = datetime.strptime(now, "%Y-%m-%d").date() if now else date.today()
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    total = len(rows)

    # 漏斗
    order = ["待触达", "已私信", "已回复", "已报价", "洽谈中", "待老板审批",
             "已签约", "已发布", "婉拒/放弃", "无回应"]
    from collections import Counter
    cnt = Counter(r.get("status", "") for r in rows)
    funnel = "".join(bar_row(s, cnt.get(s, 0), total) for s in order if cnt.get(s))

    # 分档 CPM
    cpm_pts = []
    for r in rows:
        try:
            c = float(r["cpm"]); f = int(r["followers"])
            if c > 0 and f > 0:
                cpm_pts.append((f, c))
        except (ValueError, KeyError):
            pass
    cpm_html = ""
    for name, lo, hi in TIERS:
        vals = [c for f, c in cpm_pts if lo <= f < hi]
        if len(vals) >= 3:
            cpm_html += bar_row(name, round(st.median(vals), 1), 1, extra=f" 元 (n={len(vals)})")
        elif vals:
            cpm_html += f'<div class="row"><span class="lbl">{name}</span><span class="muted">样本{len(vals)}不足</span></div>'
    if not cpm_html:
        cpm_html = '<p class="muted">暂无足够报价样本（每档需≥3）。</p>'

    # 数据新鲜度
    stale = []
    for r in rows:
        try:
            if r.get("collected_at") and datetime.strptime(r["collected_at"], "%Y-%m-%d").date() < now - timedelta(days=30):
                stale.append(r["name"])
        except ValueError:
            pass
    low_conf = [r["name"] for r in rows if r.get("data_confidence") == "low"]

    html = f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>Influencer Analytics 报告</title>
<style>
body{{font-family:-apple-system,'Segoe UI',sans-serif;max-width:820px;margin:32px auto;color:#1a1a1a;padding:0 16px}}
h1{{font-size:22px}} h2{{font-size:16px;margin-top:28px;border-bottom:2px solid #eee;padding-bottom:6px}}
.row{{display:flex;align-items:center;gap:10px;margin:5px 0}}
.lbl{{width:90px;text-align:right;font-size:13px}}
.bar{{height:16px;background:linear-gradient(90deg,#4a7dab,#7ba7d0);border-radius:3px;min-width:3px}}
.val{{font-size:13px;font-weight:600}} .muted{{color:#999;font-size:13px}}
.snap{{background:#f6f8fa;padding:8px 12px;border-radius:6px;font-size:13px;color:#555}}
.warn{{color:#b45309}}
</style>
<h1>Influencer Analytics · Campaign Report</h1>
<p class="snap">数据快照：{now}　·　总库 {total} 人　·　文件 {esc(path)}</p>
<h2>触达漏斗</h2>{funnel}
<h2>分档中位 CPM</h2>{cpm_html}
<h2>数据质量告警</h2>
<p class="{'warn' if stale else 'muted'}">采集超30天待复核：{len(stale)} 人{'（'+', '.join(map(esc,stale[:12]))+'）' if stale else ''}</p>
<p class="{'warn' if low_conf else 'muted'}">低置信度行(粉丝数存疑)：{len(low_conf)} 人{'（'+', '.join(map(esc,low_conf[:12]))+'）' if low_conf else ''}</p>
</html>"""
    open(out, "w", encoding="utf-8").write(html)
    print(f"报告已生成: {out}（{total} 人，待复核 {len(stale)}，低置信 {len(low_conf)}）")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    now = sys.argv[sys.argv.index("--now") + 1] if "--now" in sys.argv else None
    main(sys.argv[1], sys.argv[2], now)
