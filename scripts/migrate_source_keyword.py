#!/usr/bin/env python3
"""把散落在 notes 自由文本里的来源词与垂类匹配档位，迁进正式列。一次性迁移。

**为什么需要迁移**：SKILL.md 要求按 `source_keyword` 回算 `verified_precision`，
但三张表从来没有这一列，各批次自己在 notes 里发明写法——IG 线写 `keyword=overlanding`，
X 线写 `来源词：claude code｜…`。同一个信息两种写法、都在自由文本里，脚本读不出来，
于是那条关键词反馈闭环从落笔起就没跑过一次。

**迁移纪律：只搬运，不推断。**
  - notes 里明确写了的，搬进新列。
  - 没写的填 `unknown`，**绝不按"这批整体用了哪几个词"反推某一行来自哪个词**。
    知道一批用了四个词，不等于知道某行来自哪个词，填上去就是编数据，
    而且会直接污染 precision——那正是这两列要支撑的计算。
    SKILL.md 写着 `unknown` 不进分母，就是为这种情况留的。
  - 档位（强/中/弱匹配）同理：notes 里标了才搬，没标填 `unknown`，不从淘汰原因倒推。
    「因粉丝不足淘汰」不代表垂类不匹配，恰恰相反，那通常是词找对了人不合规。

用法:
  python3 migrate_source_keyword.py            # 演练，只报告
  python3 migrate_source_keyword.py --write
"""
import argparse, csv, os, re, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_COLS = ("source_keyword", "niche_match_grade")

# 两条线各自发明的写法，都要认。分隔符包含全角｜与半角|，以及分号。
PAT_SOURCE = [
    re.compile(r"来源词[：:]\s*([^｜|；;\n]+)"),                  # X 线（intl-expansion-20260810）
    # IG 线写的是 `source_keyword=overlanding`，字段名与 SKILL.md 要求的完全一致，
    # 只是存错了地方（notes 而不是列）。`source_` 前缀必须可选也必须能匹配：
    # 用 \bkeyword 会因为 `_keyword` 前面是下划线（单词字符、无词边界）而整批漏掉，
    # 2026-08-14 首次迁移就踩到，22 行 IG 记录一条没匹配上。
    # **带引号的整体捕获必须排在前面。** 2026-08-17 那批写的是
    # source_keyword="agent skills|SKILL.md|AGENTS.md"，值内部用 | 分隔三个词。
    # 若先用下面那条按 | 截断的规则，只会捕到第一个词，等于**凭空造出一个归因**，
    # 正是本脚本要防的事：一次三词联合检索，我们并不知道是哪个词带出了这个人。
    # 复合值原样保留（如 `agent skills|SKILL.md|AGENTS.md`），让它显式表示"来自这组词"。
    re.compile(r"(?:source_)?keyword\s*=\s*\"([^\"]+)\""),
    re.compile(r"(?:source_)?keyword\s*=\s*([^｜|；;\n]+)"),
]
PAT_GRADE = re.compile(r"(强匹配|中匹配|弱匹配)")


def extract(row):
    blob = row.get("notes") or ""
    kw = None
    for pat in PAT_SOURCE:
        m = pat.search(blob)
        if m:
            # 引号要剥：2026-08-17 那批写的是 source_keyword="agent skills"，
            # 带引号存进列会让同一个词出现 `agent skills` 和 `"agent skills"` 两种值，
            # 分组统计时算成两个词，precision 直接失真。
            kw = m.group(1).strip().strip("。，,").strip('"\'“”')
            break
    g = PAT_GRADE.search(blob)
    return kw, (g.group(1) if g else None)


def migrate(path, write):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        print(f"  {os.path.relpath(path, ROOT)}: 仅表头，跳过")
        return
    header = list(rows[0].keys())
    added = [c for c in NEW_COLS if c not in header]
    header += added                      # 新列一律加在表尾（schema 的列顺序原则）

    stats = Counter()
    kw_dist, grade_dist = Counter(), Counter()
    for r in rows:
        for c in NEW_COLS:
            r.setdefault(c, "")
        kw, grade = extract(r)
        # 已经有值的不覆盖：迁移是补历史，不是重写现状
        if not (r.get("source_keyword") or "").strip():
            r["source_keyword"] = kw or "unknown"
            stats["kw_migrated" if kw else "kw_unknown"] += 1
        if not (r.get("niche_match_grade") or "").strip():
            r["niche_match_grade"] = grade or "unknown"
            stats["grade_migrated" if grade else "grade_unknown"] += 1
        kw_dist[r["source_keyword"]] += 1
        grade_dist[r["niche_match_grade"]] += 1

    print(f"  {os.path.relpath(path, ROOT)}  共 {len(rows)} 行"
          f"{'（新增列 ' + '、'.join(added) + '）' if added else ''}")
    print(f"    source_keyword    : 迁移 {stats['kw_migrated']}，unknown {stats['kw_unknown']}")
    print(f"    niche_match_grade : 迁移 {stats['grade_migrated']}，unknown {stats['grade_unknown']}")
    top = [f"{k}×{v}" for k, v in kw_dist.most_common() if k != "unknown"]
    if top:
        print(f"    来源词分布: {'、'.join(top)}")
    gd = [f"{k}×{v}" for k, v in grade_dist.most_common() if k != "unknown"]
    if gd:
        print(f"    档位分布  : {'、'.join(gd)}")

    if write:
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="来源词/匹配档位迁进正式列（只搬运，不推断）")
    ap.add_argument("paths", nargs="*",
                    default=[os.path.join(ROOT, "data/db_intl.csv"),
                             os.path.join(ROOT, "data/db_cn.csv")])
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    for p in a.paths:
        if os.path.exists(p):
            migrate(p, a.write)
        else:
            print(f"  {p}: 不存在，跳过")
    print(f"\n{'✓ 已写回' if a.write else '（演练，未写文件。加 --write 才写。）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
