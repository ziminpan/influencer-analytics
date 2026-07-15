# influencer-analytics (template edition)

**EN** | [中文见下方](#中文说明)

Data-driven KOL scouting, screening, outreach and pricing analytics for
Xiaohongshu / Douyin, packaged as a Claude Agent Skill.

**Born from a real campaign** promoting a Claude skill (50-creator database,
40+ outreach, live pricing data). This template edition ships the full
methodology and an empty scaffold — bring your own preset & data.
The full configured edition is proprietary to **Waybox**.

## What's inside
- Median-based screening — never trust one viral post
- Search-boosted-account detection; two-stage scoring with no fabricated precision
  (missing dimensions stay blank, weights renormalize)
- Human-in-the-loop by design: the skill drafts outreach lists, **you send them**
- Sample-tiered price calibration (refuses regression under n=20); zero-dependency
  HTML report + optional R/Quarto analytics module

## Data integrity by design（数据可信设计）
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
（50 人博主库 / 40+ 触达 / 真实报价数据）。本仓库为**脱敏模板版**：只含方法论与
空脚手架，不含任何真实博主数据、报价与话术原文；完整配置版归 Waybox 所有。

**方法论亮点**：中位数抗爆款筛选、原始样本留档可复算（防拍脑袋）、搜索流型账号
识别、缺失维度不填想象值的两阶段打分、按样本量分级的报价校准（样本不足拒绝回归）、
风控节奏与人机分工红线内建（发送永远人工）。

使用：复制 `config.example.yaml` 为 `config.yaml`，选一个 `presets/`，把整个
文件夹放进 `~/.claude/skills/`，对 Claude 说"用 influencer-analytics 跑一轮"。

Author & Maintainer: Zimin "Zora" Pan (@ziminpan) · Built at Waybox
License: MIT
