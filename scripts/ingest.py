#!/usr/bin/env python3
"""把采集到的候选(JSON)增量合并进博主库 CSV。

强制字段所有权（SKILL.md 第 7 节）：
- 机器列可刷新（刷新时报告变化）
- 人类列永不覆盖（冲突则警告、保留人类值）
- log_outreach 追加式
去重键 = (platform, name)。粉丝数做纯数字断言（防桶值污染）。

用法:
    python ingest.py candidates.json data/db_cn.csv
候选 JSON: 见 templates/candidate.example.json
"""
import sys, json, csv, os

MACHINE_COLS = {
    "platform", "name", "niche", "followers", "posts_30d", "median_engagement",
    "engagement_basis", "raw_samples", "traffic_type", "data_confidence",
    "collected_at", "score_fit", "score_engagement", "score_audience",
    "score_content", "score_value", "score_total", "expected_exposure", "cpm",
    "profile_url",
}
HUMAN_COLS = {
    "status", "first_contact_date", "last_followup_date", "quote_image",
    "quote_video", "quote_notes", "budget_planned", "approval", "notes",
    "email", "language", "country", "currency",
}


def load(path):
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames or [], list(r)


def assert_followers(v):
    """粉丝数必须是纯数字；'1千+' 这类桶值拒绝入库。"""
    if v in (None, ""):
        return "", True
    s = str(v).strip()
    if s.isdigit():
        return int(s), True
    return "", False   # 非法值 → 空 + 标记低置信


def audit_median(c, warnings):
    """防编数对账：median_engagement 必须能从 raw_samples 复算出来。

    - raw_samples 为空却有中位数 → 拒绝中位数（无凭据不入库）
    - 精确口径(likes_saves/plays)：中位数必须等于样本中位（±1 容差）
    - 推断口径(*_inferred)：中位数 = 样本中位 × 系数，系数须在 1~40 合理区间
    - 样本 < 10 条 → data_confidence=low，notes 追加"仅N条样本"
    """
    import statistics as st
    med, raw = c.get("median_engagement"), c.get("raw_samples", "")
    if med in (None, ""):
        return
    vals = [float(x) for x in str(raw).replace("；", ";").split(";") if str(x).strip().replace(".", "").isdigit()]
    name = c.get("name")
    if not vals:
        warnings.append(f"{name}: 有中位数但无 raw_samples 凭据，中位数已拒绝入库")
        c["median_engagement"] = ""
        c["data_confidence"] = "low"
        return
    m = st.median(vals)
    basis = c.get("engagement_basis", "")
    try:
        med_f = float(med)
    except ValueError:
        c["median_engagement"] = ""; c["data_confidence"] = "low"
        warnings.append(f"{name}: 中位数非数字，已拒绝")
        return
    if basis.endswith("_inferred"):
        ratio = med_f / m if m else 0
        if not (1.0 <= ratio <= 40.0):
            warnings.append(f"{name}: 推断口径系数异常({ratio:.1f}x)，标 low 请复核")
            c["data_confidence"] = "low"
    else:
        if abs(med_f - m) > 1:
            warnings.append(f"{name}: 中位数{med_f}与样本复算值{m}不符，以复算值为准")
            c["median_engagement"] = int(m)
    if len(vals) < 10:
        c["data_confidence"] = "low"
        c["notes"] = (str(c.get("notes", "")) + f"；仅{len(vals)}条样本，中位数波动大").strip("；")


def main(cand_path, csv_path):
    cands = json.load(open(cand_path, encoding="utf-8"))
    header, rows = load(csv_path)
    if not header:
        sys.exit(f"目标 CSV 缺表头: {csv_path}")
    index = {(r["platform"], r["name"]): r for r in rows}

    added, refreshed, warnings = [], [], []
    next_num = max([int(r["id"].split("-")[1]) for r in rows if "-" in r.get("id", "")], default=0) + 1
    prefix = "CN" if "cn" in os.path.basename(csv_path) else "INTL"

    for c in cands:
        fol, ok = assert_followers(c.get("followers"))
        c["followers"] = fol
        if not ok:
            c["data_confidence"] = "low"
            warnings.append(f"{c.get('name')}: 粉丝数非纯数字，置空并标 low")
        audit_median(c, warnings)
        key = (c.get("platform"), c.get("name"))
        if key in index:                       # 已存在 → 只刷机器列
            row = index[key]
            for k, v in c.items():
                if k in MACHINE_COLS and v not in (None, "") and str(row.get(k, "")) != str(v):
                    refreshed.append(f"{key[1]}.{k}: {row.get(k)!r}→{v!r}")
                    row[k] = v
                elif k in HUMAN_COLS and row.get(k) not in (None, "") and v not in (None, ""):
                    warnings.append(f"{key[1]}.{k}: 人类列已有值，保留 {row.get(k)!r}，忽略 {v!r}")
            if c.get("log_append"):
                row["log_outreach"] = (row.get("log_outreach", "") + "；" + c["log_append"]).strip("；")
        else:                                  # 新增
            c["id"] = f"{prefix}-{next_num:03d}"; next_num += 1
            c.setdefault("status", "待触达")
            if c.pop("log_append", None):
                c["log_outreach"] = c.get("log_outreach", "")
            rows.append({h: c.get(h, "") for h in header})
            added.append(c["id"] + " " + c.get("name", ""))

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    print(f"新增 {len(added)}: {added}")
    print(f"刷新机器列 {len(refreshed)} 处" + (": " + "; ".join(refreshed[:10]) if refreshed else ""))
    if warnings:
        print("⚠ 警告:")
        for x in warnings:
            print("  -", x)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
