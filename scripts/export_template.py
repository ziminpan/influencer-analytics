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
    print(f"脱敏模板版已导出到 {out}/")
    print("⚠ 发布前请人工检查：templates/outreach.md、playbooks/*.md 是否残留公司专有表述。")


TEMPLATE_README = """# influencer-analytics (template edition)

**EN** | [中文见下方](#中文说明)

Data-driven KOL scouting, screening, outreach and pricing analytics for
Xiaohongshu / Douyin, packaged as a Claude Agent Skill.

**Born from a real campaign** promoting a Claude skill (50-creator database,
all 50 contacted, live pricing data). This template edition ships the full
methodology and an empty scaffold — bring your own preset & data.
The full configured edition is proprietary to **Waybox**.

## Install

```bash
git clone https://github.com/ziminpan/influencer-analytics.git ~/.claude/skills/influencer-analytics
cd ~/.claude/skills/influencer-analytics && cp config.example.yaml config.yaml
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
Sending is always manual. This repo contains **no real creator data, quotes, or
chat logs**. Collection covers only publicly visible information at human pace,
respecting each platform's terms.

---

## 中文说明

把「找博主 → 数据核验 → 建库 → 触达 → 报价评估 → 校准 → 复盘」做成一条可复用的
流水线，以 Claude Agent Skill 形式封装。诞生于一次真实的 Claude skill 推广投放
（50 人博主库 / 50 全量触达 / 真实报价数据）。本仓库为**脱敏模板版**：只含方法论与
空脚手架，不含任何真实博主数据、报价与话术原文；完整配置版归 Waybox 所有。

**方法论亮点**：中位数抗爆款筛选、原始样本留档可复算（防止 AI 临时编造数据）、
搜索流型账号识别、缺失维度不填想象值的两阶段打分、按样本量分级的报价校准
（样本不足拒绝回归）、哨兵健康检查（一次运行分清"平台改版"还是"个例奇葩"）、
蒲公英官方数据对账（估算值向官方值收敛）、风控节奏与人机分工红线内建（发送永远人工）。

**安装**：

```bash
git clone https://github.com/ziminpan/influencer-analytics.git ~/.claude/skills/influencer-analytics
cd ~/.claude/skills/influencer-analytics && cp config.example.yaml config.yaml
```

填好 `config.yaml` 的 product 段，选一个 `presets/`，对 Claude 说"用
influencer-analytics 跑一轮"。版本变更见 `CHANGELOG.md`。

Author & Maintainer: Zimin "Zora" Pan (@ziminpan) · Built at Waybox
License: MIT
"""


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
