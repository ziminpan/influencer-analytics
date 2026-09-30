#!/usr/bin/env python3
"""脱敏导出：从公司完整版生成可公开的个人模板版。

产物 = 方法论 + 空脚手架，抽掉一切公司专有数据。发布前务必人工再过一遍。

用法:
    python export_template.py <输出目录>
规则:
  - SKILL.md / schema / scripts / playbooks / templates / analysis / LICENSE: 原样复制（通用方法论）
  - data/*.csv: 只保留表头
  - config.yaml: 不导出（含公司配置）；config.example.yaml 原样带上
  - presets/generic.yaml: 带上（空白脚手架）
  - presets/claude-skill.yaml: product 段清空、关键词库保留（关键词属通用方法论）
  - README.md: 换成 template edition 说明
"""
import sys, os, shutil, csv, re

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPAIGN_BLOCK_BEGIN = "    # BEGIN-CAMPAIGN" + "-SPECIFIC"
CAMPAIGN_BLOCK_END = "    # END-CAMPAIGN" + "-SPECIFIC"
EMPLOYER_BLOCK_BEGIN = "#/BEGIN-EMPLOYER" + "-SUBS"
EMPLOYER_BLOCK_END = "#/END-EMPLOYER" + "-SUBS"

# 结构化数据（data/*.csv、sentinels.yaml）好剔，散文里的真实账号名难剔：
# 哨兵 handle、实测结果表、CHANGELOG 里的"淘汰某某"都会原样带出去。
# 所以脱敏改成数据驱动——从公司数据文件反查真实身份，再逐个替换成代号，
# 而不是手写黑名单（手写的会漏掉以后新增的账号）。
IDENTITY_STOP = {"instagram", "collabstr", "xiaohongshu", "douyin", "youtube",
                 "小红书", "抖音", "蒲公英", "待触达", "已报价", "淘汰"}

# 显示名里的通用词。切词脱敏时必须排除，否则 `<账号80>` 会让
# playbook 正文里每个 `Travel` 都变成代号。宁可对名字漏一两个（由 find_leaks 兜住），
# 也不能把方法论正文替成筛子。
NAME_NOISE = {
    "Travel", "Travels", "Traveler", "Traveller", "Trip", "Trips", "Roadtrip",
    "Roadtrips", "Adventure", "Adventures", "Outdoor", "Outdoors", "Family",
    "Nomad", "Nomads", "Life", "Lifestyle", "Wander", "Wanders", "Explore",
    "Explorer", "Explorers", "Hike", "Hiking", "Camp", "Camps", "Camping",
    "Photo", "Photos", "Photography", "Media", "Studio", "Official", "Real",
    "Guide", "Guides", "Gear", "Vibes", "Diaries", "Diary", "Journal", "Stories",
    "World", "Global", "Wild", "Wildly", "Free", "Freedom", "Beyond",
    "Ontario", "Canada", "America", "States", "United", "North", "South",
    "East", "West",
    # 项目内部术语，不是人名；2026-09-30 发现 find_freetext_names 把 notes 里
    # "……name 列中不含真名，见 CHANGELOG v0.4.1 记录" 这句话的 CHANGELOG 当真名误判。
    "CHANGELOG",
}
HANDLE_RE = re.compile(
    r"(?:instagram\.com|x\.com|twitter\.com|douyin\.com/user|xiaohongshu\.com/user/profile)"
    r"/([A-Za-z0-9_.\-]+)")


def _significant(t):
    """够长才拿去替换，避免误伤常用词（含中文 ≥3 字，纯拉丁 ≥4 字符）。"""
    t = (t or "").strip()
    if not t or t.lower() in IDENTITY_STOP:
        return False
    cjk = any("一" <= c <= "鿿" for c in t)
    return len(t) >= 3 if cjk else len(t) >= 4


def collect_identities():
    """把同一账号的各种写法（昵称/括号内真名/handle/邮箱）归成一组，一组给一个代号。"""
    groups = []
    data_dir = os.path.join(SRC, "data")
    for fn in sorted(os.listdir(data_dir)) if os.path.isdir(data_dir) else []:
        if not fn.endswith(".csv"):
            continue
        with open(os.path.join(data_dir, fn), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                g = {p.strip() for p in re.split(r"[()（）]", row.get("name") or "")
                     if _significant(p)}
                for key in ("profile_url", "handle_or_url"):
                    m = HANDLE_RE.search(row.get(key) or "")
                    if m and _significant(m.group(1)):
                        g.add(m.group(1))
                email = (row.get("email") or "").strip()
                if email:
                    g.add(email)
                    if _significant(email.split("@")[0]):
                        g.add(email.split("@")[0])
                if g:
                    groups.append(g)
    # 发件地址：只在 preset 里存一份（preset 不导出），但它会零散出现在 CHANGELOG /
    # playbook 的叙述里。逐处手改必然漏——2026-08-11 就漏在 email-send.md 与
    # CHANGELOG 各一处——所以纳入同一套数据驱动脱敏。
    # 只抹**邮箱地址**，不抹 sender_name："Zora" 同时是 LICENSE/README 里的维护者署名，
    # 那是有意保留的归属信息，抹掉会把署名弄坏。
    for pf in sorted(os.listdir(os.path.join(SRC, "presets"))) \
            if os.path.isdir(os.path.join(SRC, "presets")) else []:
        if not pf.endswith((".yaml", ".yml")):
            continue
        txt = open(os.path.join(SRC, "presets", pf), encoding="utf-8").read()
        for m in re.finditer(r"^\s*sender_email:\s*[\"']?([^\"'\s#]+)", txt, re.M):
            addr = m.group(1)
            if "@" in addr:
                groups.append({addr, addr.split("@")[0]})

    # 哨兵文件用正则读，不引 pyyaml——模板版要保持零依赖
    sp = os.path.join(SRC, "tests", "sentinels.yaml")
    if os.path.exists(sp):
        for line in open(sp, encoding="utf-8"):
            m = re.match(r"\s*(?:name|handle):\s*([^#\n]+)", line)
            g = set()
            if m and _significant(m.group(1).strip().strip("\"'")):
                g.add(m.group(1).strip().strip("\"'"))
            mh = HANDLE_RE.search(line)
            if mh and _significant(mh.group(1)):
                g.add(mh.group(1))
            if g:
                groups.append(g)
    # 把每个写法再切成词，把"像人名"的词也纳进同一组。
    # 2026-08-18 事故：`name` 列存的是 `<handle> (<账号M> H)`，脱敏器把 `<账号M> H`
    # 整串当成一个 token，而替换是字面子串匹配——playbook 里自然书写成 `<账号M>`，
    # 匹配不上，于是真名连同她的报价一起进了导出物，而复验还打了 ✓（见 find_leaks 注释）。
    # 漏的不是"只存在于 notes 的名字"，是**任何被截短成名的形式**：<账号S>→<账号S>、
    # <账号66> Ol…→<账号66>、<账号80> | Travel…→<账号80> 全是同一个形态。
    # 只收纯字母、首字母大写、≥4 字符且不在通用词表里的词——`Travel`/`Outdoors` 这类
    # 显示名里的通用词若也拿去替换，会把 playbook 正文里的普通英文一起替掉。
    for g in list(groups):
        for t in list(g):
            for w in re.split(r"[^A-Za-z]+", t):
                if len(w) >= 4 and w[:1].isupper() and w not in NAME_NOISE:
                    g.add(w)

    # 同一个人可能同时出现在库和哨兵里，有交集就并成一组（跑到不再变化为止）
    merged, moved = groups, True
    while moved:
        moved, out = False, []
        for g in merged:
            for m in out:
                if m & g:
                    m |= g
                    moved = True
                    break
            else:
                out.append(set(g))
        merged = out
    return merged


def redact_identities(out):
    """把导出物里的真实身份替换成代号。返回 (写法→代号 映射, 被改写的文件)。"""
    mapping = {}
    for i, g in enumerate(collect_identities()):
        code = "<账号%s>" % (chr(65 + i) if i < 26 else str(i + 1))
        for t in g:
            mapping[t] = code
    # 长的先替换：全名要先于 handle 命中，否则会替出半截文本
    # （这里刻意不举真实账号当例子——本文件自己也会被导出并脱敏）
    terms = sorted(mapping, key=len, reverse=True)
    changed = []
    for root, _dirs, files in os.walk(out):
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, out)
            if rel == "LICENSE" or rel.split(os.sep)[0] == "data":
                continue
            if os.path.splitext(fn)[1] not in (".md", ".py", ".yaml", ".yml",
                                               ".json", ".qmd", ".txt"):
                continue
            s0 = open(p, encoding="utf-8").read()
            s = s0
            for t in terms:
                if t in s:
                    s = s.replace(t, mapping[t])
            if s != s0:
                open(p, "w", encoding="utf-8").write(s)
                changed.append(rel)
    return mapping, sorted(changed)


# 雇主与产品标识 → 占位符。2026-08-18 决定：模板版**不指名雇主**。
# 母本这一侧一个字都不改——CHANGELOG 里"DKIM d= 从 feishu.cn 换成 <发信域>"
# 是这套发信域认证的操作证据，删掉母本的记录等于毁掉真实信息。要脱的是导出物。
# 顺序即优先级：长的、更专指的先替，否则裸 `<公司>` 会先把 `<你的组织>` 咬掉半截。
# （母本在此处有雇主脱敏表，模板版已自动剔除；自建时把你自己的标识填进来）
EMPLOYER_SUBS = []

# DKIM 选择器带租户编号（`s=<DKIM选择器>`），是可反查的租户标识，抹掉编号但留下
# "选择器是服务商生成的"这个方法论要点。
DKIM_SELECTOR = re.compile(r"\bs=[a-z]+\d{6,}\b")


def redact_employer(out):
    """把雇主/产品标识换成占位符。返回被改写的文件列表。

    与 redact_identities 分开是因为两者性质不同：博主真名是**第三方隐私**，漏了是事故；
    雇主名是**归属选择**，是不是要指名由维护者定（2026-08-18 定为不指名）。
    LICENSE 不动——版权行写的是著作权归属，改它是法律陈述，不是脱敏。
    """
    changed = []
    for root, _dirs, files in os.walk(out):
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, out)
            if rel == "LICENSE" or rel.split(os.sep)[0] == "data":
                continue
            if os.path.splitext(fn)[1] not in (".md", ".py", ".yaml", ".yml",
                                               ".json", ".qmd", ".txt"):
                continue
            s0 = open(p, encoding="utf-8").read()
            s = s0
            for old, new in EMPLOYER_SUBS:
                s = s.replace(old, new)
            s = DKIM_SELECTOR.sub("s=<DKIM选择器>", s)
            if s != s0:
                open(p, "w", encoding="utf-8").write(s)
                changed.append(rel)
    return sorted(changed)


def version_mismatch():
    """比对 SKILL.md 的版本锚点与 CHANGELOG 最新条目；一致返回 None。

    一个没人核对的版本号迟早会漂——所以在导出（发版边界）顺手比一次。
    不引 pyyaml：模板版要保持零依赖，正则够用。
    """
    try:
        skill = open(os.path.join(SRC, "SKILL.md"), encoding="utf-8").read()
        log = open(os.path.join(SRC, "CHANGELOG.md"), encoding="utf-8").read()
    except OSError:
        return None
    fm = re.match(r"^---\n(.*?)\n---", skill, re.DOTALL)
    stamped = re.search(r"^\s+version:\s*(\S+)", fm.group(1), re.M) if fm else None
    newest = re.search(r"^##\s*(v[\d.]+)", log, re.M)
    a = stamped.group(1) if stamped else "(未标注)"
    b = newest.group(1) if newest else "(未找到)"
    return None if a == b else (a, b)


# 自由文本里的真名标记。`name` 列之外，核验时常把真名记进 notes（"真名 Xxx"），
# 那些列 collect_identities 从不读，所以这条通道是 mapping 结构上看不见的。
NAME_MARKER = re.compile(r"(?:真名|本名|名字)[：:， ]*([A-Z][a-zA-Z]{3,})")


def find_freetext_names(out):
    """独立复验：拿母本自由文本列里"真名 Xxx"式的名字，直接去导出物里搜。

    为什么必须独立：find_leaks 搜的是 mapping —— 脱敏器自己建的那份表。
    检查器与脱敏器共用同一个盲区，它只能发现脱敏器已经知道的东西，
    2026-08-18 就是这样在 7 个真名躺在导出物里的情况下打出了 ✓。
    这里的候选**不经过 mapping**，专治那条通道。
    """
    names = set()
    data_dir = os.path.join(SRC, "data")
    for fn in sorted(os.listdir(data_dir)) if os.path.isdir(data_dir) else []:
        if not fn.endswith(".csv"):
            continue
        with open(os.path.join(data_dir, fn), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for col in ("notes", "log_outreach", "quote_notes"):
                    names.update(m for m in NAME_MARKER.findall(row.get(col) or "")
                                 if m not in NAME_NOISE)
    hits = []
    for root, _dirs, files in os.walk(out):
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, out)
            if rel.split(os.sep)[0] == "data":
                continue
            try:
                s = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            hits += [(rel, n) for n in sorted(names)
                     if re.search(r"\b" + re.escape(n) + r"\b", s)]
    return hits


def find_employer_leaks(out):
    """复验雇主标识是否真的抹净（占位符本身不算残留）。"""
    hits = []
    for root, _dirs, files in os.walk(out):
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, out)
            if rel == "LICENSE" or rel.split(os.sep)[0] == "data":
                continue
            try:
                s = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for old, _new in EMPLOYER_SUBS:
                if old in s:
                    hits.append((rel, old))
    return hits


def find_leaks(out, mapping):
    """兜底复验：宁可不发布，也不发一个带真实身份的"脱敏版"。

    ⚠ 这一层只能发现 mapping 里已有的写法——它与脱敏器同源，不是独立校验。
    真正独立的那层在 find_freetext_names()，两层都过了才配打 ✓。
    """
    leaks = []
    for root, _dirs, files in os.walk(out):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), out)
            if rel == "LICENSE":
                continue
            try:
                s = open(os.path.join(root, fn), encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            leaks += [(rel, t) for t in mapping if t in s]
    return leaks


def main(out):
    os.makedirs(out, exist_ok=True)
    for item in ["SKILL.md", "schema", "scripts", "playbooks", "templates",
                 "analysis", "LICENSE", "config.example.yaml", "CHANGELOG.md",
                 "references"]:
        s = os.path.join(SRC, item)
        if not os.path.exists(s):
            continue
        d = os.path.join(out, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy(s, d)

    # 自净：导出的 export_template.py 里剔除"战役特定替换"代码块
    # （那段代码含公司战役原文字符串，只对公司母本有意义，模板版不需要也不该带）
    ep = os.path.join(out, "scripts", "export_template.py")
    if os.path.exists(ep):
        txt = open(ep, encoding="utf-8").read()
        b, e = txt.find(CAMPAIGN_BLOCK_BEGIN), txt.find(CAMPAIGN_BLOCK_END)
        if b != -1 and e != -1:
            txt = txt[:b] + "    # （公司母本在此处有战役特定替换块，模板版已自动剔除）\n" \
                  + txt[e + len(CAMPAIGN_BLOCK_END):]
        b, e = txt.find(EMPLOYER_BLOCK_BEGIN), txt.find(EMPLOYER_BLOCK_END)
        if b != -1 and e != -1:
            txt = txt[:b] + "# （母本在此处有雇主脱敏表，模板版已自动剔除；" \
                            "自建时把你自己的标识填进来）\nEMPLOYER_SUBS = []\n" \
                  + txt[e + len(EMPLOYER_BLOCK_END):]
        open(ep, "w", encoding="utf-8").write(txt)

    # data: 只留表头
    os.makedirs(os.path.join(out, "data"), exist_ok=True)
    for fn in os.listdir(os.path.join(SRC, "data")):
        if fn.endswith(".csv"):
            with open(os.path.join(SRC, "data", fn), encoding="utf-8") as f:
                header = f.readline()
            open(os.path.join(out, "data", fn), "w", encoding="utf-8").write(header)

    # tests: 只导出 example（sentinels.yaml 含真实账号，属公司数据，绝不导出）
    os.makedirs(os.path.join(out, "tests"), exist_ok=True)
    se = os.path.join(SRC, "tests", "sentinels.example.yaml")
    if os.path.exists(se):
        shutil.copy(se, os.path.join(out, "tests", "sentinels.example.yaml"))

    # presets
    os.makedirs(os.path.join(out, "presets"), exist_ok=True)
    shutil.copy(os.path.join(SRC, "presets", "generic.yaml"),
                os.path.join(out, "presets", "generic.yaml"))
    # claude-skill: 清 product 段，保留 discovery（关键词库=通用方法论）
    txt = open(os.path.join(SRC, "presets", "claude-skill.yaml"), encoding="utf-8").read()
    txt = re.sub(r'(brand_name:|repo_url:|pitch_one_liner:|repo_slug:|web_fallback:)\s*".*?"',
                 r'\1 ""', txt)
    open(os.path.join(out, "presets", "claude-skill.yaml"), "w", encoding="utf-8").write(txt)

    # （公司母本在此处有战役特定替换块，模板版已自动剔除）


    # README
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(TEMPLATE_README)

    # 真实身份脱敏 + 复验（README 的合规声明写着"不含任何真实博主数据"，得真的成立）
    mapping, changed = redact_identities(out)
    print(f"脱敏模板版已导出到 {out}/")
    print(f"已脱敏 {len(set(mapping.values()))} 个账号（{len(mapping)} 种写法），"
          f"改写 {len(changed)} 个文件：{changed}")
    emp = redact_employer(out)
    print(f"已抹除雇主/产品标识，改写 {len(emp)} 个文件：{emp}")

    # 三层复验，任一层不过就中止：①mapping 同源兜底 ②雇主标识 ③自由文本真名（独立）
    leaks = find_leaks(out, mapping)
    if leaks:
        print("✗ 复验失败：导出物仍残留真实身份，已中止发布。补脱敏规则后重跑：")
        for rel, t in leaks[:20]:
            print(f"   {rel}: {t!r}")
        sys.exit(1)
    eleaks = find_employer_leaks(out)
    if eleaks:
        print("✗ 复验失败：雇主/产品标识未抹净，已中止发布：")
        for rel, t in eleaks[:20]:
            print(f"   {rel}: {t!r}")
        sys.exit(1)
    fnames = find_freetext_names(out)
    if fnames:
        print("✗ 独立复验失败：母本自由文本里的真名出现在导出物里，已中止发布。")
        print("   （这一层不走 mapping，命中说明脱敏器根本没见过这个名字）")
        for rel, t in fnames[:20]:
            print(f"   {rel}: {t!r}")
        sys.exit(1)
    print("✓ 复验通过（三层）：库内/哨兵身份、雇主标识、自由文本真名均未见残留")
    vm = version_mismatch()
    if vm:
        print(f"⚠ 版本锚点不一致：SKILL.md metadata.version={vm[0]}，"
              f"CHANGELOG 最新={vm[1]}——发版前先对齐。")
    else:
        print("✓ 版本锚点与 CHANGELOG 一致")
    print("⚠ 发布前仍需人工确认：真实报价金额、蒲公英刊例价、GitHub 星数等数字仍作为"
          "方法论实测例子留在 CHANGELOG / playbooks 里（已与账号身份解绑）。")


TEMPLATE_README = """# influencer-analytics (template edition)

**EN** | [中文见下方](#中文说明)

Data-driven KOL scouting, screening, outreach and pricing analytics for
Xiaohongshu / Douyin, packaged as a Claude Agent Skill.

**Born from a real campaign** promoting a Claude skill (50-creator database,
all 50 contacted, live pricing data). This template edition ships the full
methodology and an empty scaffold — bring your own preset & data.
The full configured edition is proprietary to **<公司>**.

## Install

Requires Python 3.9+ and `pyyaml` (`merge_seed.py` and `check_sentinel.py` need
it; `calibrate.py` reads config with it and falls back to defaults without it).
Everything else is stdlib-only — the HTML report is dependency-free by design.

```bash
pip install --user pyyaml
git clone https://github.com/ziminpan/influencer-analytics.git ~/.claude/skills/influencer-analytics
cd ~/.claude/skills/influencer-analytics && cp config.example.yaml config.yaml
cp tests/sentinels.example.yaml tests/sentinels.yaml   # then fill in your own benchmark accounts
```

Fill the `product` block in `config.yaml`, pick a preset in `presets/`, then tell
Claude: *"用 influencer-analytics 跑一轮"*.

## What's inside
- Median-based screening — never trust one viral post
- Search-boosted-account detection; two-stage scoring with no fabricated precision
  (missing dimensions stay blank, weights renormalize)
- Human-in-the-loop by design: the skill drafts outreach lists, **you send them**
- Sample-tiered price calibration (refuses regression under n=20); zero-dependency
  HTML report + optional R/Quarto analytics module
- Sentinel health-check (`tests/`): two benchmark creators per platform tell
  "site redesign" from "one weird profile" in a single run
- Official-backend reconciliation (XHS Pgy / 蒲公英): audit estimates against
  platform ground truth, correct coefficients once ≥8 paired samples exist

## Data integrity by design（数据可信设计：防止 AI 临时编造数据）
Numbers you can audit, not numbers you must trust:
- **Every median must recompute** — `ingest.py` rejects any `median_engagement`
  that cannot be re-derived from the stored `raw_samples` (anti-fabrication audit;
  a median with no raw evidence is refused outright).
- **Every number carries its measuring stick** — `engagement_basis` labels whether
  a figure is ground truth (`likes_saves`/`plays`) or inferred (`*_inferred`), and
  the cost-aware precision ladder (backend screenshot > per-account sampling >
  category prior) is an explicit, configurable trade-off against platform
  rate-limits — not a shortcut.
- **Small samples degrade loudly** — profiles with fewer than 10 posts are
  auto-flagged `data_confidence=low` with the sample count written into notes;
  vague follower buckets ("1万+") never enter the followers column.

## Compliance
Sending is always manual. Collection covers only publicly visible information at
human pace, respecting each platform's terms.

**What this repo does and does not contain.** Data CSVs ship as headers only, and
no creator identity appears anywhere: `export_template.py` redacts every real
handle, display name and email it finds in the company edition's data files and
sentinel config, then re-scans its own output and refuses to publish if anything
survives. Figures from real campaigns — quoted prices, rate-card values, star
counts — are kept as methodology examples in `CHANGELOG.md` and the playbooks,
decoupled from the accounts they came from.

---

## 中文说明

把「找博主 → 数据核验 → 建库 → 触达 → 报价评估 → 校准 → 复盘」做成一条可复用的
流水线，以 Claude Agent Skill 形式封装。诞生于一次真实的 Claude skill 推广投放
（50 人博主库 / 50 全量触达 / 真实报价数据）。本仓库为**脱敏模板版**：只含方法论与
空脚手架，数据 CSV 只留表头，**不含任何真实博主身份**——导出时会按公司版的数据文件与
哨兵配置逐个抹除昵称/handle/邮箱，并对产物复验，有残留就拒绝发布。真实战役的报价、
刊例价、GitHub 星数等数字作为方法论实测例子保留在 `CHANGELOG.md` 与 playbooks 中，
已与具体账号解绑。完整配置版归 <公司> 所有。

**方法论亮点**：中位数抗爆款筛选、原始样本留档可复算（防止 AI 临时编造数据）、
搜索流型账号识别、缺失维度不填想象值的两阶段打分、按样本量分级的报价校准
（样本不足拒绝回归）、哨兵健康检查（一次运行分清"平台改版"还是"个例奇葩"）、
蒲公英官方数据对账（估算值向官方值收敛）、风控节奏与人机分工红线内建（发送永远人工）。

**安装**（需 Python 3.9+ 与 `pyyaml`；其余脚本只用标准库）：

```bash
pip install --user pyyaml
git clone https://github.com/ziminpan/influencer-analytics.git ~/.claude/skills/influencer-analytics
cd ~/.claude/skills/influencer-analytics && cp config.example.yaml config.yaml
cp tests/sentinels.example.yaml tests/sentinels.yaml   # 再填入你自己的标杆账号
```

填好 `config.yaml` 的 product 段，选一个 `presets/`，对 Claude 说"用
influencer-analytics 跑一轮"。版本变更见 `CHANGELOG.md`。

Author & Maintainer: Zimin "Zora" Pan (@ziminpan) · Built at <公司>
License: MIT
"""


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
