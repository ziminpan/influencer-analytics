#!/usr/bin/env python3
"""把 CSV 库同步进运营管理表 xlsx（CSV 是唯一权威，xlsx 是给人看的视图）。

背景：管理表一直是人工维护的，于是必然漂移——实测 2026-08-11，v0.8 表里少了 60 个人，
已有 40 行里还有 11 处触达状态与 CSV 不一致（多数是 direction_only 政策迁移后没同步）。
人工同步 100 行不现实，所以做成脚本。

三条设计约束：

1. **按编号定位，绝不整表覆写。** 整表重写会毁掉你在表里的人工内容。
2. **只写"CSV 里有对应字段"的列。** xlsx 独有的人工列（如「人工核验发现」）永不触碰——
   它们在 CSV 里没有归宿，覆写等于凭空销毁信息。
3. **默认写新版本文件，不动原文件。** 沿用你既有的 v0.N 命名习惯，出错随时回到上一版。
   要就地覆盖得显式加 --in-place。

⚠ openpyxl 会丢图表/图片/部分格式。本表实测无公式、无合并单元格、无图表，所以安全；
   将来若在表里加了图表，先确认再跑，或改用 --in-place 之外的方式。

用法:
  python3 sync_xlsx.py --csv data/db_intl.csv --xlsx "../海外社媒/…v0.8.xlsx"        # 演练，只报差异
  python3 sync_xlsx.py --csv data/db_intl.csv --xlsx "…v0.8.xlsx" --write            # 写出 v0.9
  python3 sync_xlsx.py --csv data/db_intl.csv --xlsx "…v0.8.xlsx" --write --in-place # 就地覆盖
"""
import argparse, csv, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import openpyxl
    from openpyxl.styles import PatternFill
except ImportError:
    sys.exit("需要 openpyxl：pip install openpyxl --break-system-packages")

# xlsx 中文表头 → CSV 字段。只有出现在这里的列才会被脚本写。
# 没列进来的（如「人工核验发现」）属于 xlsx 独有的人工列，永不触碰。
COLMAP = {
    "编号": "id", "平台": "platform", "昵称": "name", "垂类": "niche",
    "粉丝数": "followers", "触达状态": "status", "起步价(USD)": "quote_image",
    "视频报价(USD)": "quote_video",
    "报价说明": "quote_notes",
    # Collabstr 平台徽章（top / fast / top+fast / none）。2026-08-27 建列。
    # 为什么必须成列而不写在备注里：它是**筛选判据**——「私信未回 + 邮件未回 + 无徽章 → 不合作」
    # 要能机械跑，判据就不能埋在自由文本里。同一个毛病在 source_keyword 和 quote_source 上
    # 各修过一次（信息埋在 notes 里，脚本读不出来，闭环从没跑过），第三次就说不过去了。
    "交付信号": "delivery_signal",
    "预期曝光": "expected_exposure",
    "拟投预算": "budget_planned", "预估CPM": "cpm", "老板审批": "approval",
    "国家": "country", "邮箱": "email", "备注": "notes",
    "主页链接": "profile_url", "沟通记录": "log_outreach",
}
# 报价来源高亮：哪一列的值要按哪一列的来源标记上色。
# **只给「博主本人报出的价」上色**——平台挂牌价和本人直接报价是两种东西，
# 混在一张表里看会把挂牌价当成谈判基线。实测差距极大：INTL-010 平台图文 $275 / 本人视频 $800，
# INTL-011 平台 $60 / 本人 $900，方向和倍数都不固定，不能互相推算。
#
# 判据取自 quote_source_* 列，**不去 quote_notes 里搜关键字**。同一个毛病刚在
# source_keyword 上修过一轮（信息埋在自由文本里，脚本读不出来，闭环从没跑过），
# 刚建完列就再犯一次说不过去。
QUOTE_HIGHLIGHT = {
    "起步价(USD)": "quote_source_image",
    "视频报价(USD)": "quote_source_video",
}
DIRECT_FILL = PatternFill("solid", start_color="FFF2CC", end_color="FFF2CC")  # 浅琥珀


# 行序：让"要处理的"浮到上面，"已经了结的"沉到下面。
# 表是人扫的，100+ 行里真正要动作的只有个位数，让它们埋在中间等于没排序。
STATUS_RANK = {
    "已签约": 1, "已发布": 1, "洽谈中": 1, "待老板审批": 1, "已报价": 1,
    "已回复": 2,
    "已私信": 3,
    "待触达": 4,
    "待查": 5,
    "无回应": 6,
    "已拒绝": 7, "婉拒放弃": 7,
    "淘汰": 8,
}
UNKNOWN_RANK = 4      # 没见过的状态排在待触达一档，不沉底也不置顶


def sort_key(src):
    """已报价的绝对置顶，其余按漏斗阶段，淘汰与拒绝沉底，同档按编号。

    **已报价置顶用的是「本人真的报了价」而不是 status**：库里 status 走到「已报价」
    这一档的人目前是 0，实际报了价的五个人 status 都还停在「已回复」。
    按 status 排会把他们和没报价的混在一起，而他们恰恰是唯一要立刻决策的一批。
    """
    quoted = "creator_direct" in (src.get("quote_source_image", "") +
                                  src.get("quote_source_video", ""))
    rank = STATUS_RANK.get((src.get("status") or "").strip(), UNKNOWN_RANK)
    return (0 if quoted else 1, rank, src.get("id", ""))

KEY_HEADER = "编号"
INT_FIELDS = {"followers", "expected_exposure", "budget_planned", "quote_image",
              "quote_video"}


def derive_cost_per_1k(row, ctx):
    """每千粉成本 = 报价 ÷ 粉丝 × 1000。视频报价优先，没有才用图文起步价。

    **不要和「预估CPM」混为一谈。** schema 的 cpm 分母是 expected_exposure（实际播放
    中位数），海外线在补采到每人近 10 条同类型内容的播放样本之前一律为空——那是硬
    口径，不能用粉丝数凑。粉丝数是个更差的分母（粉丝 ≠ 看到的人），但它现在就有，
    能横向比出谁贵谁便宜，所以单独一列、单独一个名字，免得两个数被当成一回事。
    """
    q = (row.get("quote_video") or row.get("quote_image") or "").strip()
    f = (row.get("followers") or "").strip()
    try:
        q, f = float(q), float(f)
    except ValueError:
        return None
    return round(q / f * 1000, 2) if f else None


def derive_dossier(row, ctx):
    """档案文件名。让表里的人能直接找到那份 md，两个产物才算真的对接上。"""
    return (ctx.get("dossiers") or {}).get(row["id"])


# 派生列：值不在 CSV 里，由 CSV 现算。写进 xlsx 是为了给人看，CSV 不存冗余副本。
DERIVED = {
    "每千粉成本(USD/千粉)": derive_cost_per_1k,
    "档案文件": derive_dossier,
}


def next_version_path(path):
    """…v0.8.xlsx → …v0.9.xlsx；无版本号则加 -synced 后缀。"""
    d, base = os.path.split(path)
    m = re.search(r"v(\d+)\.(\d+)(?=\.xlsx$)", base)
    if not m:
        return os.path.join(d, base.replace(".xlsx", "-synced.xlsx"))
    major, minor = int(m.group(1)), int(m.group(2))
    # minor 到 9 就进位：v0.9 → v1.0，而不是 v0.10。
    # 语义上 0.10 没错，但文件按名称排序时 v0.10 会卡在 v0.1 和 v0.2 中间，
    # 而这些表是人在 Finder 里翻的，排序不直观比版本号语义更要命。
    major, minor = (major + 1, 0) if minor >= 9 else (major, minor + 1)
    return os.path.join(d, base[:m.start()] + f"v{major}.{minor}" + base[m.end():])


def coerce(field, value):
    v = (value or "").strip()
    if v == "":
        return None
    if field in INT_FIELDS:
        try:
            return int(float(v))
        except ValueError:
            return v          # 存不下数字就原样写字符串，不猜、不丢
    return v


def main():
    ap = argparse.ArgumentParser(description="CSV → 管理表 xlsx 单向同步")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--sheet", default="2-博主库")
    ap.add_argument("--write", action="store_true", help="不加则只报告差异（默认演练）")
    ap.add_argument("--in-place", action="store_true", dest="in_place",
                    help="就地覆盖原文件；默认写出版本号 +1 的新文件")
    ap.add_argument("--allow-clear", action="store_true", dest="allow_clear",
                    help="允许用 CSV 的空值清掉表里已有内容（默认不清，避免擦掉人工填的东西）")
    ap.add_argument("--add-columns", action="store_true", dest="add_columns",
                    help="表里缺少的已知列/派生列追加到表头末尾（默认不加，改表结构要显式要求）")
    ap.add_argument("--no-sort", action="store_true", dest="no_sort",
                    help="不重排行序（默认按「已报价置顶、淘汰沉底」重排）")
    ap.add_argument("--dossier-dir", dest="dossier_dir",
                    default=os.path.abspath(os.path.join(ROOT, "..", "海外社媒", "博主档案")),
                    help="博主档案目录，用于填「档案文件」列")
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.csv, encoding="utf-8")))
    by_id = {r["id"]: r for r in rows}

    # 档案文件名索引：只认真实存在的文件，没有就留空，不写一个点不开的链接
    dossiers = {}
    if os.path.isdir(a.dossier_dir):
        for fn in os.listdir(a.dossier_dir):
            m = re.match(r"((?:INTL|CN)-\d+)_", fn)
            if m and fn.endswith(".md"):
                dossiers[m.group(1)] = fn
    ctx = {"dossiers": dossiers}

    wb = openpyxl.load_workbook(a.xlsx)      # data_only=False：保留公式
    if a.sheet not in wb.sheetnames:
        sys.exit(f"表里没有工作表「{a.sheet}」，现有：{wb.sheetnames}")
    ws = wb[a.sheet]

    headers = [c.value for c in ws[1]]
    if KEY_HEADER not in headers:
        sys.exit(f"工作表首行找不到「{KEY_HEADER}」列，无法定位行")

    # 表里还没有的已知列/派生列。追加表头是改表结构，要显式 --add-columns 才做。
    #
    # **新列插在 COLMAP 声明的位置，不再追加到最右边**（2026-08-27 改）。
    # 原来是 headers.append()，于是 `视频报价(USD)` 落在第 19 列、`人工核验发现` 之后，
    # 而它在 COLMAP 里明明声明在 `起步价(USD)` 与 `报价说明` 之间——表结构和声明对不上，
    # 看表的人得横拉过 11 列才能把两个报价放在一起看。
    # 只改表结构不改这里，下次加列会复发同一个毛病（"修产物不修生成器"）。
    ORDER = list(COLMAP) + list(DERIVED)          # 声明顺序 = 期望列序
    wanted = [h for h in ORDER if h not in headers]
    if wanted:
        if a.add_columns:
            for h in wanted:
                # 找该列在 ORDER 里的下一个「表中已存在」的列，插在它前面；
                # 找不到（说明它该在末尾）就追加。
                after = None
                for nxt in ORDER[ORDER.index(h) + 1:]:
                    if nxt in headers:
                        after = headers.index(nxt) + 1
                        break
                if after is None:
                    headers.append(h)
                    if a.write:
                        ws.cell(row=1, column=len(headers), value=h)
                else:
                    headers.insert(after - 1, h)
                    if a.write:
                        ws.insert_cols(after)
                        ws.cell(row=1, column=after, value=h)
            print(f"  新增列：{'、'.join(wanted)}（按 COLMAP 声明位置插入，非追加到末尾）")
        else:
            print(f"  ⓘ 表里缺 {len(wanted)} 个已知列（{'、'.join(wanted)}），"
                  f"本次不动表结构；要加请带 --add-columns")

    key_col = headers.index(KEY_HEADER) + 1
    # 只处理认识的列；未知列（含 xlsx 独有人工列）记下来报告，但不写
    known = {h: (headers.index(h) + 1, COLMAP[h]) for h in headers if h in COLMAP}
    derived = {h: (headers.index(h) + 1, DERIVED[h]) for h in headers if h in DERIVED}
    untouched = [h for h in headers if h and h not in COLMAP and h not in DERIVED]

    changes, appended, skipped_clear, highlighted = [], [], [], []
    seen = set()
    for r in ws.iter_rows(min_row=2):
        cid = r[key_col - 1].value
        if not cid:
            continue
        cid = str(cid).strip()
        seen.add(cid)
        src = by_id.get(cid)
        if not src:
            changes.append((cid, "(整行)", "CSV 里已无此人", "保留不动"))
            continue
        row_no = r[0].row
        for h, (col, field) in known.items():
            if field == "id":
                continue
            new = coerce(field, src.get(field))
            # 用 ws.cell 而不是 r[col-1]：新加的列可能超出这一行现有的单元格范围，
            # 索引取值会 IndexError（演练时表头没真写进去，更会越界）。
            cell = ws.cell(row=row_no, column=col)
            old = cell.value
            if (str(old or "").strip()) == (str(new or "").strip()):
                continue
            # 空值不清人工内容：CSV 该字段为空、而表里有值时默认跳过。
            # "CSV 是权威"指的是取值权威，不该让一个空字段把人工填的东西擦掉
            # （实测会踩到：INTL-015 的老板审批在 CSV 里已空，表里还是「待审」）。
            if new is None and str(old or "").strip() and not a.allow_clear:
                skipped_clear.append((cid, h, old))
                continue
            changes.append((cid, h, old, new))
            if a.write:
                cell.value = new

        # 报价来源高亮：值写完之后再上色，与是否发生值变更无关——
        # 颜色反映的是"这个数从哪来"，即使数字没变、来源标注补上了也要染色。
        for h, srccol in QUOTE_HIGHLIGHT.items():
            if h not in known:
                continue
            col = known[h][0]
            if (src.get(srccol) or "").strip() == "creator_direct":
                highlighted.append((cid, h))
                if a.write:
                    ws.cell(row=row_no, column=col).fill = DIRECT_FILL

        # 派生列：现算现写。**空值直接清，不受 --allow-clear 约束。**
        # 「空值不清」那条保护是为了不擦掉人工填的东西；派生列没有人工作者，
        # 唯一作者就是脚本，保护它等于把过期值永久留在表里。实测踩到过：档案 md 删掉后
        # 「档案文件」列还指着已不存在的文件，成了死链——过期值比空值更坏，因为它看着像真的。
        for h, (col, fn) in derived.items():
            new = fn(src, ctx)
            cell = ws.cell(row=row_no, column=col)
            old = cell.value
            if (str(old or "").strip()) == (str(new if new is not None else "").strip()):
                continue
            changes.append((cid, h, old, new))
            if a.write:
                cell.value = new

    missing = [r for r in rows if r["id"] not in seen]
    for src in missing:
        appended.append(src["id"])
        if a.write:
            ws.append([coerce(COLMAP[h], src.get(COLMAP[h])) if h in COLMAP
                       else DERIVED[h](src, ctx) if h in DERIVED else None
                       for h in headers])

    # ---- 行重排：值写完、补录完之后再排，否则新补的行不参与排序 ----
    reordered = 0
    if a.write and not a.no_sort:
        body = list(ws.iter_rows(min_row=2))
        # 连样式一起搬。只搬值会丢掉刚打上的报价高亮，以及表里任何人工填的底色/字体——
        # 那属于"整表覆写毁掉人工内容"，正是本脚本第 1 条设计约束要防的事。
        snapshot = [[(c.value, c._style) for c in row] for row in body]
        keyed = []
        for cells in snapshot:
            cid = str(cells[key_col - 1][0] or "").strip()
            src = by_id.get(cid)
            # CSV 里已无此人的行保持原相对位置沉在最后，不猜它该排哪
            keyed.append((sort_key(src) if src else (2, 99, cid), cells))
        ordered = [c for _, c in sorted(keyed, key=lambda x: x[0])]
        if ordered != snapshot:
            for i, cells in enumerate(ordered, start=2):
                for j, (val, style) in enumerate(cells, start=1):
                    cell = ws.cell(row=i, column=j)
                    cell.value = val
                    cell._style = style
            reordered = len(ordered)
        print(f"  行重排：{'已按「已报价置顶 / 淘汰沉底」重排 ' + str(reordered) + ' 行' if reordered else '顺序已正确，未改动'}")

    if highlighted:
        print(f"  博主本人报价高亮 {len(highlighted)} 处（浅琥珀底）: "
              f"{'、'.join(f'{c} {h}' for c, h in highlighted)}")
    print(f"CSV {len(rows)} 行 ← → xlsx「{a.sheet}」{len(seen)} 行")
    print(f"  字段差异 {len(changes)} 处，需补录 {len(appended)} 人")
    if untouched:
        print(f"  不触碰的 xlsx 独有列：{untouched}")
    if changes:
        print("\n  差异明细（前 25 条）:")
        for cid, h, old, new in changes[:25]:
            o, n = str(old or ""), str(new or "")
            if len(o) > 30 or len(n) > 30:
                # 截断会让"其实不同"的长文本看起来一样，所以定位到首个差异字符
                i = next((k for k in range(min(len(o), len(n))) if o[k] != n[k]),
                         min(len(o), len(n)))
                print(f"    {cid:<10} {h:<12} 第 {i} 字起不同（{len(o)}→{len(n)} 字）")
                print(f"       旧 …{o[max(0,i-12):i+26]!r}")
                print(f"       新 …{n[max(0,i-12):i+26]!r}")
            else:
                print(f"    {cid:<10} {h:<12} {o!r} → {n!r}")
        if len(changes) > 25:
            print(f"    …另有 {len(changes) - 25} 处")
    if skipped_clear:
        print(f"\n  ⚠ 跳过 {len(skipped_clear)} 处「CSV 空值会清掉表里内容」（要清加 --allow-clear）:")
        for cid, h, old in skipped_clear[:8]:
            print(f"    {cid:<10} {h:<12} 表里保留 {str(old)[:24]!r}")
    if appended:
        print(f"\n  补录: {appended[:8]}{'…' if len(appended) > 8 else ''}")

    if not a.write:
        print("\n（演练，未写任何文件。加 --write 才写。）")
        return 0

    out = a.xlsx if a.in_place else next_version_path(a.xlsx)
    wb.save(out)
    print(f"\n✓ 已写入：{out}")
    if not a.in_place:
        print("  原文件未改动——核对新版无误后再决定是否替换。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
