# influencer-analytics (template edition)

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
