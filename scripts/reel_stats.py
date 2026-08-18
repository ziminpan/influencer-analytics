#!/usr/bin/env python3
"""把浏览器端采到的 Reel 播放数原始值，算成 schema 要求的曝光口径并写库。

**纯处理，不抓取**（SKILL.md §0）：抓取由带登录态的浏览器端做，本脚本只接收
`{id: [{reel_id, raw, pinned}, ...]}` 这样的原始数组，做单位换算、剔置顶、取中位数。
这样换来三件事：换算逻辑能离线自测、能进 CI、改判据不用重新消耗风控预算。

**为什么必须是中位数而不是均值**：2026-08-17 实测 INTL-010 最近 10 条
Reel 播放 1812/5437/2861/1239/**61000**/3084/**28000**/3442/5210/2606——
中位数 3,263，均值 10,970，Collabstr 页面显示的 "Average Views" 是 8.4k。
一两条爆款把均值拉高 2.6 倍，而商单拿不到爆款的流量。
用均值算 CPM 会把 $245/千次播放 算成 $95，差 2.6 倍，方向还是偏乐观的那一边。

**单位换算放在脚本这一侧**，浏览器只交原始文本：IG 界面语言为中文时播放数显示成
`6.1万`。直接存成数字是历史上"万单位数据事故"的同一个形态（见 schema 开头的原则），
而放在脚本里换算意味着这段逻辑可以被 --self-test 覆盖。

样本不足 10 条时**拒绝写入**，不是凑合算——schema 明写"样本不足 10 条或平台不显示
view counts 时保持空值，不用 followers/likes 补猜"。

用法:
  # 浏览器端产出 samples.json 后：
  python3 reel_stats.py --in samples.json                 # 演练，只报告
  python3 reel_stats.py --in samples.json --write
  python3 reel_stats.py --self-test                       # 只测换算与中位数逻辑
"""
import argparse, csv, json, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_SAMPLES = 10          # schema 硬要求，不可配——放宽它等于放宽口径本身


def to_int(raw):
    """把界面显示的播放数文本换成整数；换不出来返回 None（绝不猜）。

    中文 locale 的 `万`/`亿` 和英文 locale 的 `K`/`M` 都要吃，因为同一个账号
    换个界面语言就是另一种写法，而库里只能存绝对数。
    """
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw or "").replace(",", "").replace("，", "").strip()
    if not s:
        return None
    for pat, mul in ((r"^([\d.]+)\s*万$", 10_000), (r"^([\d.]+)\s*亿$", 100_000_000),
                     (r"^([\d.]+)\s*[kK]$", 1_000), (r"^([\d.]+)\s*[mM]$", 1_000_000)):
        m = re.match(pat, s)
        if m:
            return int(round(float(m.group(1)) * mul))
    return int(s) if re.fullmatch(r"\d+", s) else None


def compute(items):
    """→ (最近 MIN_SAMPLES 条的中位数, 用到的样本列表, 诊断信息)。不足则中位数为 None。"""
    total = len(items)
    pinned = sum(1 for i in items if i.get("pinned"))
    vals, bad = [], []
    for i in items:
        if i.get("pinned"):
            continue                      # 置顶是账号的橱窗，不是日常表现
        v = to_int(i.get("raw", i.get("views")))
        (vals.append(v) if v is not None else bad.append(i.get("raw")))
    used = vals[:MIN_SAMPLES]             # 浏览器端按主页顺序给，即最新在前
    diag = {"抓到": total, "置顶剔除": pinned, "换算失败": bad,
            "可用": len(vals), "取用": len(used)}
    if len(used) < MIN_SAMPLES:
        return None, used, diag
    return statistics.median(used), used, diag


def main():
    ap = argparse.ArgumentParser(description="Reel 播放数 → 曝光口径（不抓取）")
    ap.add_argument("--in", dest="inp", help="浏览器端产出的 JSON")
    ap.add_argument("--db", default=os.path.join(ROOT, "data/db_intl.csv"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--self-test", action="store_true", dest="self_test")
    a = ap.parse_args()

    if a.self_test:
        cases = [("6.1万", 61000), ("2.8万", 28000), ("1.1万", 11000), ("1,812", 1812),
                 ("3084", 3084), ("12.5K", 12500), ("1.2M", 1200000), ("1亿", 100000000),
                 ("很多", None), ("", None), (5437, 5437)]
        bad = [(r, to_int(r), e) for r, e in cases if to_int(r) != e]
        print(f"  单位换算 {len(cases) - len(bad)}/{len(cases)} 通过")
        for r, got, exp in bad:
            print(f"    ✗ {r!r} → {got}，应为 {exp}")
        # 中位数：偶数个取两中间值平均；奇数个取正中
        t = [{"raw": v} for v in [1812, 5437, 2861, 1239, "6.1万", 3084,
                                  "2.8万", 3442, 5210, 2606]]
        med, used, diag = compute(t)
        ok = med == 3263
        print(f"  INTL-010 实测 10 条中位数 = {med}（应为 3263）{' ✓' if ok else ' ✗'}")
        t2 = t[:9]
        med2, _, _ = compute(t2)
        print(f"  样本 9 条时拒绝出值 = {med2 is None and '✓ 返回 None' or '✗ 竟然出了值'}")
        t3 = t + [{"raw": 999, "pinned": True}]
        med3, used3, d3 = compute(t3)
        print(f"  置顶被剔除 = {'✓' if d3['置顶剔除'] == 1 and med3 == 3263 else '✗'}")
        return 1 if bad or not ok else 0

    if not a.inp:
        sys.exit("需要 --in <samples.json> 或 --self-test")
    data = json.load(open(a.inp, encoding="utf-8"))
    rows = list(csv.DictReader(open(a.db, encoding="utf-8")))
    hdr = list(rows[0].keys())
    by_id = {r["id"]: r for r in rows}

    wrote, refused = [], []
    for cid, items in data.items():
        r = by_id.get(cid)
        if not r:
            refused.append((cid, "不在库里")); continue
        med, used, diag = compute(items)
        print(f"\n  {cid}  {r['name'][:28]}")
        print(f"    {diag}")
        if med is None:
            print(f"    ✗ 样本不足 {MIN_SAMPLES} 条，按 schema 保持空值，不写入")
            refused.append((cid, f"样本 {diag['可用']} < {MIN_SAMPLES}"))
            continue
        print(f"    样本: {used}")
        print(f"    中位数 {int(med):,}　均值 {int(sum(used)/len(used)):,}"
              f"（均值/中位 {sum(used)/len(used)/med:.1f}×）")
        q = (r.get("quote_video") or r.get("quote_image") or "").strip()
        if q:
            try:
                per_k = float(q) / med * 1000
                print(f"    报价 {r['currency'] or '?'} {q} → **每千次播放 "
                      f"{per_k:,.2f}**（对照：每千粉 "
                      f"{float(q)/float(r['followers'])*1000:,.2f}）")
            except ValueError:
                pass
        if a.write:
            r["raw_samples"] = ";".join(str(v) for v in used)
            r["median_engagement"] = str(int(med))
            r["engagement_basis"] = "ig_reels_views"
            r["expected_exposure"] = str(int(med))
            r["data_confidence"] = "low"          # organic_median_proxy，未经成交校准
            note = (f"2026-08-17 曝光口径采集：最近 {len(used)} 条非置顶 Reel 公开播放数"
                    f"中位数 {int(med):,}（均值 {int(sum(used)/len(used)):,}，"
                    f"爆款把均值拉高 {sum(used)/len(used)/med:.1f} 倍）。"
                    f"expected_exposure 暂取该中位数，标 organic_median_proxy、"
                    f"data_confidence=low；未经成交折损校准。"
                    f"⚠ 公开 views 含重播，不等于独立触达人数")
            r["notes"] = (r["notes"] + "｜" + note) if r["notes"] else note
            wrote.append(cid)

    if a.write and wrote:
        with open(a.db, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=hdr, lineterminator="\n")
            w.writeheader(); w.writerows(rows)
        print(f"\n✓ 已写入 {len(wrote)} 人: {wrote}")
    elif not a.write:
        print(f"\n（演练，未写库。加 --write 才写。）")
    if refused:
        print(f"  拒绝写入 {len(refused)}: {refused}")
    # cpm 仍留空是对的：schema 定义 cpm = budget_planned ÷ expected_exposure × 1000，
    # 分子是**实付全款**（人类列，含平台费），不是博主报价。曝光有了但预算未定，
    # 所以这里只报告"报价÷曝光"作参考，不往 cpm 列写——那一列有它自己的口径。
    print("  注：cpm 列仍为空。它的分子是 budget_planned（实付全款，人类列），"
          "不是博主报价；上面的每千次播放只是参考值。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
