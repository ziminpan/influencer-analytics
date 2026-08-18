#!/usr/bin/env python3
"""把库文件的数值列还原成整数串，并报告任何非法值。

**为什么需要这个脚本**：db_intl.csv 有过两次同样的漂移（2026-08-12、2026-08-13），
`followers` 被写成 `16000.0`。来源不是仓库里的脚本——`scripts/` 下没有 pandas，五个
`DictWriter` 都显式带 `lineterminator="\\n"`——而是外部工具经 openpyxl/pandas
读表再回写 CSV，那两个库都把整数返回成 float。

危害不在数值本身（`16000.0 == 16000`），在两处：
  1. `int("16000.0")` 抛异常。`report_html.py` 曾把它吞在裸 `except: pass` 里，
     结果整张 CPM 图静静变空而不报错（v0.4.4 已改成 `int(float(...))` 并计数）。
  2. 一次漂移就是 95 行假 diff，把当批真正的几处改动埋掉，审计时根本看不出发生了什么。

所以这里只做格式还原，**绝不改动任何数值**：先验证每个值都是整数（`16000.5`
这种会被报出来而不是悄悄取整），确认无损再写回。

用法:
  python3 normalize_db.py                          # 演练，只报告
  python3 normalize_db.py --write
  python3 normalize_db.py --write data/db_cn.csv data/db_intl.csv
"""
import argparse, csv, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 只列真正该是整数的列。score_* 是小数口径，currency 之类是字符串，都不在此列。
INT_COLUMNS = ("followers", "posts_30d", "median_engagement", "quote_image",
               "quote_video", "expected_exposure", "budget_planned",
               "official_reads_median")
FLOATISH = re.compile(r"^-?\d+\.0+$")


def normalize(path, write):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        print(f"  {path}: 仅表头，跳过")
        return 0, []
    header = list(rows[0].keys())
    cols = [c for c in INT_COLUMNS if c in header]
    fixed, refused = 0, []
    per_col = {}
    for r in rows:
        for c in cols:
            v = (r.get(c) or "").strip()
            if not v or v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
                continue
            if FLOATISH.match(v):
                r[c] = str(int(float(v)))
                fixed += 1
                per_col[c] = per_col.get(c, 0) + 1
            else:
                # 不是纯 .0 结尾就不动：可能是 "16.5k" 这种未清洗值，也可能是真小数。
                # 悄悄取整会丢信息，报出来让人看。
                refused.append((r.get("id", "?"), c, v))
    print(f"  {os.path.relpath(path, ROOT)}: 可还原 {fixed} 个"
          f"{'（' + '、'.join(f'{k}×{v}' for k, v in per_col.items()) + '）' if per_col else ''}"
          f"，需人工看 {len(refused)} 个")
    for cid, c, v in refused[:10]:
        print(f"      ⚠ {cid} {c} = {v!r}")
    if write and fixed:
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    return fixed, refused


EMAIL_RE = re.compile(r"[\w\.\-\+]+@[\w\.\-]+\.\w+")


def audit_missing_email(path):
    """报告「notes/log 里出现过邮箱、email 列却是空的」的行。

    这是一次真实事故的机械化防线：INTL-016 的邮箱 2026-07-30 就采到了，写进了
    `notes` 却没落进 `email` 列，于是被邮件流程整批跳过两周——直到 08-14 逐行翻
    notes 才发现。人记得去查不算防线，能跑出来才算。

    只报告不改写：`email` 是取值列，往里写值是采集动作，得由看过页面的人来做
    （notes 里那串字符可能是截断的、可能是别人的、可能是平台客服邮箱）。
    """
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    hits = []
    for r in rows:
        if (r.get("email") or "").strip():
            continue
        blob = (r.get("notes") or "") + " " + (r.get("log_outreach") or "")
        found = EMAIL_RE.findall(blob)
        if found:
            hits.append((r.get("id", "?"), found[0]))
    if hits:
        print(f"  ⚠ {os.path.relpath(path, ROOT)}: {len(hits)} 行的 notes/log 里有邮箱、"
              f"email 列却为空（漏填风险，需人工确认后再填）:")
        for cid, mail in hits[:15]:
            print(f"      {cid}  {mail}")
    return hits


GEO_RE = re.compile(r"([A-Z]{2})\s+(\d+)")


def us_ca_share(geo):
    """从 `US 95 / DE 1 / AU 1` 这种串里算美加合计占比；算不出返回 None。"""
    if not geo or geo.strip().lower() == "unknown":
        return None
    hits = GEO_RE.findall(geo)
    if not hits:
        return None
    return sum(int(n) for c, n in hits if c in ("US", "CA")) / 100.0


def audit_audience_geo(path, floor=0.50):
    """报告「受众地域不达标或未知，却已进触达队列」的行。

    2026-08-17 复盘的机械化防线。原来的地域门槛筛的是**博主注册城市**，
    三个注册地在美/加的博主受众主体在俄语区/巴西/印度，一路通过进了付费流程。
    `unknown` 一律按不合格报出来（fail-closed）——把未知当合格用正是那次的成因。

    只报告不改状态：要不要淘汰是人的判断，他们可能对别的产品线仍有价值。
    """
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows or "audience_geo_top3" not in rows[0]:
        return []
    REACHED = {"已私信", "已回复", "已报价", "洽谈中", "待老板审批", "已签约", "已发布"}
    # 地域门槛只对旅行线（Instagram）生效。X 开发者线的 KPI 是 github_stars，
    # 地域不影响价值，且平台不提供该数据——一并审计会产出永远清不掉的告警噪音，
    # 而噪音多的告警等于没有告警。见 SKILL.md 红线 9 分线表。
    GEO_APPLIES = {"Instagram"}
    bad = []
    for r in rows:
        if (r.get("status") or "").strip() not in REACHED:
            continue
        if (r.get("platform") or "").strip() not in GEO_APPLIES:
            continue
        share = us_ca_share(r.get("audience_geo_top3"))
        if share is None:
            bad.append((r.get("id"), r.get("status"), "unknown", r.get("audience_geo_top3") or ""))
        elif share < floor:
            bad.append((r.get("id"), r.get("status"), f"{share:.0%}", r.get("audience_geo_top3")))
    if bad:
        known = [b for b in bad if b[2] != "unknown"]
        print(f"  ⚠ {os.path.relpath(path, ROOT)}: {len(bad)} 行已触达但受众地域不达标"
              f"（门槛 {floor:.0%} 美加合计），其中 {len(known)} 行有明确数据:")
        for cid, st, share, geo in known:
            print(f"      {cid}  {st:<6}美加 {share:<6}{geo}")
        if len(bad) - len(known):
            print(f"      另有 {len(bad)-len(known)} 行受众地域为 unknown（按不合格计）")
    return bad


def main():
    ap = argparse.ArgumentParser(description="库文件数值列格式还原（不改数值）+ 漏填邮箱审计")
    ap.add_argument("paths", nargs="*",
                    default=[os.path.join(ROOT, "data/db_intl.csv"),
                             os.path.join(ROOT, "data/db_cn.csv")])
    ap.add_argument("--write", action="store_true", help="不加则只报告")
    a = ap.parse_args()
    total, bad, leaks, geo = 0, [], [], []
    for p in a.paths:
        if not os.path.exists(p):
            print(f"  {p}: 不存在，跳过")
            continue
        f, r = normalize(p, a.write)
        total += f
        bad += r
        leaks += audit_missing_email(p)
        geo += audit_audience_geo(p)
    print(f"\n{'✓ 已写回' if a.write else '（演练，未写文件。加 --write 才写。）'}"
          f" 共 {total} 个单元格")
    print(f"  待人工处理：非法数值 {len(bad)}｜漏填邮箱嫌疑 {len(leaks)}｜受众地域不达标 {len(geo)}")
    # 三类都需要人看，任一非空即非零退出，别让它在 CI/批处理里静静过去。
    # 分开计数是因为它们要找的人不同：数值问题找写库的，邮箱找采集的，
    # 受众地域找决定要不要继续谈的那个人。
    return 1 if (bad or leaks or geo) else 0


if __name__ == "__main__":
    sys.exit(main())
