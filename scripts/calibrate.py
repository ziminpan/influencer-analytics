#!/usr/bin/env python3
"""报价校准：用真实报价回推真实 CPM，输出按样本量自动分级。

诚实优先于花哨：样本不足就不给结论，绝不用 9 个点画出一条看着很科学但没意义的回归线。
单一市场内运行（人民币/美元 CPM 不混算）。

用法:
    python calibrate.py data/db_cn.csv [--config config.yaml]
"""
import sys, csv, statistics as st

TIERS = [("KOC", 0, 10000), ("初级", 10000, 50000),
         ("腰部", 50000, 200000), ("头部", 200000, 10**12)]
DEFAULTS = dict(min_samples_for_output=8, min_samples_per_tier=3, min_samples_for_regression=20)


def load_cfg(path):
    cfg = dict(DEFAULTS)
    if not path:
        return cfg
    try:
        import yaml
        y = yaml.safe_load(open(path, encoding="utf-8")) or {}
        cfg.update({k: v for k, v in (y.get("calibration") or {}).items() if k in cfg})
    except Exception:
        pass
    return cfg


def tier_of(followers):
    for name, lo, hi in TIERS:
        if lo <= followers < hi:
            return name
    return "?"


def main(path, cfg_path=None):
    cfg = load_cfg(cfg_path)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    pts = []
    for r in rows:
        try:
            cpm = float(r["cpm"]); fol = int(r["followers"])
            if cpm > 0 and fol > 0:
                pts.append((fol, cpm, r["name"], tier_of(fol)))
        except (ValueError, KeyError):
            continue

    n = len(pts)
    print(f"=== 报价校准 · 有效样本 {n} 份 ===\n")
    if n < cfg["min_samples_for_output"]:
        print(f"[拒绝] 样本不足（< {cfg['min_samples_for_output']}），有意不输出校准 CPM。原始散点：")
        for fol, cpm, name, t in sorted(pts):
            print(f"  {name}({t}, {fol}粉): CPM {cpm}")
        print("\n下一步：继续收集报价，达到门槛后重跑。当前仍用 config 里的行业参考区间。")
        return

    # 分档中位
    print("分档中位 CPM（每档需 ≥{} 样本才显示）：".format(cfg["min_samples_per_tier"]))
    for name, lo, hi in TIERS:
        vals = [cpm for fol, cpm, _, _ in pts if lo <= fol < hi]
        if len(vals) >= cfg["min_samples_per_tier"]:
            print(f"  {name}: 中位 CPM {st.median(vals):.1f}（n={len(vals)}, "
                  f"范围 {min(vals):.0f}–{max(vals):.0f}）")
        elif vals:
            print(f"  [拒绝] {name}: 档内样本仅 {len(vals)}，有意不给档位值")

    # 回归（样本充足时）
    tiers_ok = sum(1 for _, lo, hi in TIERS
                   if len([1 for fol, _, _, _ in pts if lo <= fol < hi]) >= 5)
    if n >= cfg["min_samples_for_regression"] and tiers_ok >= 2:
        import math
        xs = [math.log10(f) for f, _, _, _ in pts]
        ys = [math.log10(c) for _, c, _, _ in pts]
        mx, my = sum(xs) / n, sum(ys) / n
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        a = my - b * mx
        print(f"\nlog-log 回归: CPM ≈ {10**a:.2f} × followers^{b:.3f}")
    else:
        print(f"\n[拒绝] 样本达 {cfg['min_samples_for_regression']} 且两档各≥5 才做回归，当前有意不做。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cfg = sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else None
    main(sys.argv[1], cfg)
