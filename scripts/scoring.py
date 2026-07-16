#!/usr/bin/env python3
"""两阶段打分：缺数据的维度留空，score_total 按可用维度归一化。

为什么归一化而不是当 0：一个还没拿到报价的博主，score_value 是"未知"不是"零分"。
把未知当零会systematically低估所有未询价的候选，排序失真。

用法:
    python scoring.py data/db_cn.csv          # 就地回填 score_total
"""
import sys, csv

WEIGHTS = {
    "score_fit": 30, "score_engagement": 25, "score_audience": 20,
    "score_content": 15, "score_value": 10,
}


def score_row(row):
    num = den = 0.0
    for col, w in WEIGHTS.items():
        v = row.get(col, "")
        if v not in (None, ""):
            try:
                num += float(v) * w
                den += w
            except ValueError:
                pass
    if den == 0:
        return ""
    return round(num / den, 2)      # 归一到 0-100 尺度


def main(path):
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        header, rows = r.fieldnames, list(r)
    updated = 0
    for row in rows:
        s = score_row(row)
        if str(row.get("score_total", "")) != str(s):
            row["score_total"] = s
            updated += 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader(); w.writerows(rows)
    print(f"score_total 更新 {updated} 行")
    # 顺带列出"仅初筛分"的行（缺画像或性价比），提醒补数据
    partial = [row["name"] for row in rows
               if row.get("score_total") and (not row.get("score_audience") or not row.get("score_value"))]
    if partial:
        print(f"仅初筛分(待补画像/报价) {len(partial)} 行: {partial[:15]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
