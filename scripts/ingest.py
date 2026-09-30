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
    "profile_url", "official_reads_median",
    # 2026-08-14 新增，发现层写入：source_keyword 是这个候选从哪个搜索词来的，
    # niche_match_grade 是验证层给的垂类匹配档位。两者缺一，SKILL.md 的关键词
    # 反馈闭环（verified_precision = (强匹配+中匹配) / 已判定人数）就算不出来——
    # 只有来源词没有档位，分子拿不到；只有档位没有来源词，分不到词头上。
    "source_keyword", "niche_match_grade",
    # 2026-08-17 新增：受众地域。与 country 是两件事——country 是**博主**在哪
    # （管时区结算），这一列是**受众**在哪（管这单值不值得做）。把前者当后者的
    # 代理，是 2026-08-17 复盘查出来的系统性错误：三个注册地在美加的博主，
    # 受众主体分别在俄语区、巴西和印度。
    "audience_geo_top3", "audience_geo_source",
    # 每个无法填充的核心机器字段都必须在这里留结构化原因，禁止无解释空白。
    "machine_gaps",
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
        warnings.append(f"[拒绝] {name}: 有中位数但无 raw_samples 凭据，中位数不入库。下一步：补采原始样本后重跑")
        c["median_engagement"] = ""
        c["data_confidence"] = "low"
        return
    m = st.median(vals)
    basis = c.get("engagement_basis", "")
    try:
        med_f = float(med)
    except ValueError:
        c["median_engagement"] = ""; c["data_confidence"] = "low"
        warnings.append(f"[拒绝] {name}: 中位数非数字，不入库。下一步：检查采集输出格式")
        return
    if basis.endswith("_inferred"):
        ratio = med_f / m if m else 0
        if not (1.0 <= ratio <= 40.0):
            warnings.append(f"[降级] {name}: 推断口径系数异常({ratio:.1f}x)，标 low。下一步：人工复核该行系数来源")
            c["data_confidence"] = "low"
    else:
        if abs(med_f - m) > 1:
            warnings.append(f"[降级] {name}: 中位数{med_f}与样本复算值{m}不符，已改用复算值。下一步：排查该行中位数从何而来")
            c["median_engagement"] = int(m)
    if len(vals) < 10:
        c["data_confidence"] = "low"
        c["notes"] = (str(c.get("notes", "")) + f"；仅{len(vals)}条样本，中位数波动大").strip("；")


def main(cand_path, csv_path):
    with open(cand_path, encoding="utf-8") as handle:
        cands = json.load(handle)
    header, rows = load(csv_path)
    if not header:
        sys.exit(f"目标 CSV 缺表头: {csv_path}")
    if "machine_gaps" not in header:
        header.append("machine_gaps")
        for row in rows:
            row["machine_gaps"] = ""
    index = {(r["platform"], r["name"]): r for r in rows}

    added, refreshed, warnings = [], [], []
    next_num = max([int(r["id"].split("-")[1]) for r in rows if "-" in r.get("id", "")], default=0) + 1
    prefix = "CN" if "cn" in os.path.basename(csv_path) else "INTL"

    for c in cands:
        fol, ok = assert_followers(c.get("followers"))
        c["followers"] = fol
        if not ok:
            c["data_confidence"] = "low"
            warnings.append(f"[降级] {c.get('name')}: 粉丝数非纯数字（疑似登出态桶值），置空并标 low。下一步：确认登录态后重采")
        audit_median(c, warnings)
        key = (c.get("platform"), c.get("name"))
        if key in index:                       # 已存在 → 只刷机器列
            row = index[key]
            for k, v in c.items():
                if k in MACHINE_COLS and v not in (None, "") and str(row.get(k, "")) != str(v):
                    refreshed.append(f"{key[1]}.{k}: {row.get(k)!r}→{v!r}")
                    row[k] = v
                elif k in HUMAN_COLS and row.get(k) not in (None, "") and v not in (None, ""):
                    warnings.append(f"[提示] {key[1]}.{k}: 人类列已有值，保留 {row.get(k)!r}，忽略 {v!r}")
            if c.get("log_append") and c["log_append"] not in row.get("log_outreach", ""):
                row["log_outreach"] = (row.get("log_outreach", "") + "；" + c["log_append"]).strip("；")
        else:                                  # 新增
            c["id"] = f"{prefix}-{next_num:03d}"; next_num += 1
            c.setdefault("status", "待触达")
            if c.pop("log_append", None):
                c["log_outreach"] = c.get("log_outreach", "")
            rows.append({h: c.get(h, "") for h in header})
            added.append(c["id"] + " " + c.get("name", ""))

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        # 显式 "\n"：csv 默认 "\r\n" 会把整库行尾翻成 CRLF，一次入库产生全文件 diff
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    print(f"新增 {len(added)}: {added}")
    print(f"刷新机器列 {len(refreshed)} 处" + (": " + "; ".join(refreshed[:10]) if refreshed else ""))
    if warnings:
        print("⚠ 警告:")
        for x in warnings:
            print("  -", x)
        print("下一步总览：低置信行请人工复核；怀疑采集逻辑整体坏了，先跑哨兵（SKILL.md 第10节第0步）。")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
