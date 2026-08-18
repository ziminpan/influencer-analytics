#!/usr/bin/env python3
"""把平行会话产出的"种子"候选 CSV（如另一会话深研产物 db_intl_seed_v1.csv）
合并进博主库 CSV，处理跨会话常见的三个问题：

1. 序号体系不同（种子用 I0xx，库内用 CN-0xx/INTL-0xx）→ 重编号，旧序号入 notes 溯源。
2. 去重键不是精确匹配——种子的 name 常缺后缀（"janedoe" vs
   "janedoe (Jane Doe)"），改用 handle 归一化（取 @handle 或 name 首词
   小写 + profile_url 域名后缀）做模糊匹配，撞上就跳过，不撞就当新增处理。
   （例子刻意用虚构账号：本文件会被导出到公开模板版。）
3. 粉丝数超筛选上限时不再现拍——按 preset 的 screening 分级规则自动标注：
   容忍内标"略超线"；更高档写 `approval=待审` 或 notes 放大器标签，
   但 direction-only 政策下统一 `status=待触达`。

本脚本只做去重、重编号、粉丝分级标注——geo/垂类是否符合、数据是否完整这类需要
判断内容的检查，仍打"[提示]"要求人工复核，不自动淘汰或自动通过。

用法:
    python merge_seed.py <种子CSV> <目标库CSV> <preset.yaml>
例:
    python merge_seed.py ../海外社媒/db_intl_seed_v1.csv data/db_intl.csv presets/roadtrip-intl.yaml
"""
import sys, csv, os, re

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml --break-system-packages")


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames or [], list(r)


def norm_handle(name, profile_url):
    """粗归一化：优先取 @handle，否则取 name 首个词，小写去空格。"""
    m = re.search(r"@([A-Za-z0-9_.]+)", str(name) or "")
    if m:
        return m.group(1).lower()
    if profile_url:
        m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)/?", str(profile_url))
        if m:
            return m.group(1).lower()
    first = re.split(r"[\s(（]", str(name).strip())[0]
    return first.lower()


def screening_tier(followers, screening):
    """返回 (status_suffix, approval, note)；direction-only 下 status_suffix 始终为 None。"""
    if followers in (None, "", 0):
        return None, "", "[提示] 粉丝数缺失，需先核验再打分/入待触达队列"
    fmax = screening.get("followers_max")
    tol = screening.get("over_cap_tolerance", 0.15)
    esc = screening.get("over_cap_escalation_max", tol)
    if fmax is None or followers <= fmax:
        return None, "", ""
    over_ratio = followers / fmax - 1
    if over_ratio <= tol:
        # SKILL.md §2 要求这一档必须标「略超线」并留痕，不能静默放过——
        # 否则人工看表时无法区分"正好在带内"和"超了但在容忍内"。
        return None, "", f"[标注] 粉丝超上限{over_ratio:.0%}，在容忍{tol:.0%}内 → 入库标「略超线」"
    if over_ratio <= esc:
        return None, "待审", f"[提示] 粉丝超上限{over_ratio:.0%}（容忍{tol:.0%}~{esc:.0%}档），status 保持待触达；出价前需审批"
    return None, "待审", f"[提示] 粉丝超上限{over_ratio:.0%}（超{esc:.0%}档），status 保持待触达；优先考虑放大器/关系合作"


def main(seed_path, db_path, preset_path):
    preset = yaml.safe_load(open(preset_path, encoding="utf-8"))
    screening = preset.get("screening", {})

    seed_header, seed_rows = load_csv(seed_path)
    db_header, db_rows = load_csv(db_path)
    if not db_header:
        sys.exit(f"目标库缺表头: {db_path}")

    existing_keys = {norm_handle(r.get("name"), r.get("profile_url")) for r in db_rows}
    next_num = max([int(re.sub(r"\D", "", r["id"])) for r in db_rows if re.search(r"\d", r.get("id", ""))], default=0) + 1
    prefix = "CN" if "cn" in os.path.basename(db_path) else "INTL"

    added, skipped, warnings = [], [], []

    for s in seed_rows:
        key = norm_handle(s.get("name"), s.get("profile_url"))
        if key in existing_keys:
            skipped.append(f"{s.get('id')} {s.get('name')} → 已在库内(handle={key})，跳过")
            continue

        followers = None
        try:
            followers = int(float(s["followers"])) if s.get("followers") not in (None, "", "nan") else None
        except (ValueError, TypeError):
            pass

        status_suffix, approval, note = screening_tier(followers, screening)
        over_tag = "略超线" if note.startswith("[标注]") else ""

        row = {h: "" for h in db_header}
        for f in ("platform", "name", "niche", "profile_url"):
            if f in s:
                row[f] = s[f]
        row["platform"] = row["platform"].strip().title() if row.get("platform") else row["platform"]
        row["followers"] = followers if followers is not None else ""
        row["id"] = f"{prefix}-{next_num:03d}"
        next_num += 1
        row["status"] = status_suffix or s.get("status") or "待触达"
        row["approval"] = approval
        row["data_confidence"] = "low"
        row["collected_at"] = s.get("collected_at", "")
        src_note = (str(s.get("notes", "")) or str(s.get("quote_notes", ""))).strip()
        row["notes"] = "｜".join(x for x in [
            src_note, over_tag,
            "来自 " + os.path.basename(seed_path) + f"（原序号 {s.get('id')}）"] if x)
        row["log_outreach"] = f"由 {os.path.basename(seed_path)} 种子合并入库"

        db_rows.append(row)
        added.append(f"{row['id']} {s.get('name')}")
        existing_keys.add(key)
        if note:
            warnings.append(f"{row['id']} {s.get('name')}: {note}")

    with open(db_path, "w", encoding="utf-8", newline="") as f:
        # lineterminator 必须显式给 "\n"：csv 默认写 "\r\n"，会把整个库的行尾从 LF
        # 翻成 CRLF，于是"合并了 0 行"也产生一个全文件 diff，真实改动被埋掉。
        w = csv.DictWriter(f, fieldnames=db_header, lineterminator="\n")
        w.writeheader()
        w.writerows(db_rows)

    print(f"新增 {len(added)}: {added}")
    print(f"跳过(已在库) {len(skipped)}: {skipped}")
    if warnings:
        print("⚠ 需人工复核:")
        for x in warnings:
            print("  -", x)
    print("下一步：人工确认新增行的 niche/geo；只有方向明确不符才改淘汰，"
          "粉丝/价格风险只写 approval/notes。本脚本不做内容层判断。")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
