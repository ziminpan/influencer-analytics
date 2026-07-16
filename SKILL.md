---
name: influencer-analytics
description: >-
  Data-driven KOL scouting, screening, outreach and pricing analytics for
  Xiaohongshu (小红书) and Douyin (抖音) campaigns. Use this skill whenever the
  user wants to 找博主/挖达人/建博主库/达人建联/继续挖/补齐博主库, asks to 统计中位赞藏、
  反推播放量、算预期曝光或 CPM, wants 私信话术/触达清单 generated, sends quote
  screenshots or chat logs to be parsed into the database (报价解析/更新触达状态),
  asks 报价贵不贵/该还价多少 (run calibration), or wants a campaign report from the
  creator CSVs. Also trigger when the user mentions KOL outreach, influencer
  discovery, creator database, 蒲公英/星图报价, 蒲公英对账, 中位数筛选, asks to
  跑健康检查/哨兵测试 (sentinel sanity check), or asks to repair a broken
  collection playbook (采集失效/选择器失效).
---

# Influencer Analytics（达人建联与数据分析）

把「找博主 → 数据核验 → 建库 → 触达 → 报价评估 → 校准 → 复盘」做成一条可重复的流水线。
核心信条：**中位数不信爆款、口径永远随数字、机器不碰人类的列、发送永远由人来点。**

## 0. 开工前置（每轮必做，顺序执行）

1. **读配置**：加载 `config.yaml`（无则复制 `config.example.yaml` 并让用户填 product 段）。
   加载 `presets/` 中用户选定的预设；预设值覆盖 config 同名项。
2. **确认市场**：`market: cn` 用 `data/db_cn.csv`；`intl` 用 `db_intl.csv`。
   两个市场的数据、校准、报告**永远分开**——不同货币的 CPM 混在一起毫无意义。
3. **登录态检查**：用浏览器打开目标平台首页，按 playbook 里的「登录态检查」段验证。
   未登录就停下来请用户扫码——**登出状态采集到的粉丝数是模糊桶值（如"1千+"），
   会污染整个库**（这是真实发生过两次的事故）。
4. **风控预算确认**：向用户报告本轮计划访问量；遵守 pacing 配置（详见第 6 节红线）。

## 1. 工作流总览

```
发现 discovery ──▶ 采集 collect ──▶ 初筛 screen ──▶ 入库 ingest ──▶ 打分 score
                                                                      │
   复盘 report ◀── 校准 calibrate ◀── 报价解析 parse ◀── 触达 outreach ◀─┘
```

| 阶段 | 怎么做 | 详细说明 |
|---|---|---|
| 发现 | 按预设关键词站内搜索，提取作者与主页 ID | playbook 各平台文件 |
| 采集 | 逐主页抓粉丝数、近期作品赞藏/点赞、代表作标题 | 同上 |
| 初筛 | 硬性门槛过滤（下方第 2 节） | 本文件 |
| 入库 | `scripts/ingest.py`（去重、字段所有权保护） | `schema/schema.md` |
| 打分 | `scripts/scoring.py` 两阶段打分 | 本文件第 3 节 |
| 触达 | 用模板生成个性化清单，**用户手动发送** | `templates/` |
| 报价解析 | 用户丢截图/聊天记录 → 提取报价、更新状态、追加沟通记录 | 第 4 节 |
| 校准 | `scripts/calibrate.py` 分级输出 | 第 5 节 |
| 复盘 | `scripts/report_html.py` 零依赖 HTML 报告 | — |

## 2. 硬性门槛（初筛，任一不满足即不入正式库）

以 config/preset 的数值为准，默认：

- **粉丝区间**：`followers_min` ~ `followers_max`（默认 1,000–10,000，存**绝对数**）。
  略超上限 ≤15% 的优质候选可入库，`notes` 标"略超线"，让老板拍板。
- **中位互动 ≥ `median_floor`**（默认 30）。小红书口径 = 近 10 篇非置顶「赞+藏」中位；
  抖音口径 = 近 10 条非置顶点赞中位。**置顶一律剔除**——置顶是账号的橱窗，不是日常。
- **互动/粉丝比 ≥ `fan_ratio_floor`**（默认 1%）：低于此疑似买粉或流量枯竭。
- **近 30 天更新 ≥ `posts_30d_min`**（默认 4 条）：用作品 ID 时间戳解码统计
  （`scripts/decode_note_time.py`，见 playbook），不要逐篇点开看日期。
- **内容匹配**：近期作品标题至少 3 条命中 `niche_match_terms`。
- **搜索流型识别**（重要）：小号若中位互动 ≥ 粉丝数 × `search_boosted_ratio`（默认 50%），
  标 `traffic_type=search_boosted`，并**改用与商单同类型的垂类作品子集**重算中位——
  热点贴的流量复制不到商单上。原始数据存 `raw_samples`，重算永远可复现。

淘汰的候选不静默丢弃：在轮次总结里列名单和淘汰原因（一票否决项），用户可推翻。

## 3. 两阶段打分（缺数据的维度留空，不填想象值）

权重：垂类匹配 30 / 互动质量 25 / 粉丝画像 20 / 内容质量 15 / 商单性价比 10。

- **初筛期**只打三个可观测维度：score_fit（内容与预设垂类的重合度）、
  score_engagement（中位 vs 门槛的倍数 + 爆款率）、score_content（教程讲解能力）。
  score_total = 可用维度加权后**按可用权重归一化**（scoring.py 自动处理）。
- **画像与性价比**：拿到后台截图/media kit 才填 score_audience；拿到报价才填 score_value。
  为什么不许预估：精确数字会制造虚假精度，排序被想象值污染比留空更危险。

## 4. 报价与沟通解析（用户丢材料进来时）

用户粘贴聊天记录或截图后：提取报价 → 写入 `quote_image`/`quote_video`（**纯数字，
只存博主报价底价**）；平台报备费不并入报价：`budget_planned` = 实付全款
（走报备 = 报价 × (1+`platform_fee_rate`)），CPM 一律用 `budget_planned` 算。
"2000+200"这类表述：2000 进 quote，说明进 `quote_notes`。
同时：`status` 按流转更新，`log_outreach` **追加**一行 `YYYY-MM-DD 事件`（永不改写历史），
主观判断写 `notes`。解析完立即回报：CPM、与基准的对比、建议动作（可谈/砍价/放弃）。

## 5. 校准（随时可跑，输出按样本量自动分级）

运行 `scripts/calibrate.py`。分级规则（阈值在 config）：

- **n < 8 份报价**：不给结论。只列原始散点 + 行业参考区间，明说"样本不足"。
- **8 ≤ n < 20**：分档位（按粉丝量级）输出中位 CPM，**每档 ≥3 个样本才显示该档**，
  绝不跨档混算——头部一个报价就能把 KOC 档带歪。
- **n ≥ 20 且至少两个档位各 ≥5**：log-log 回归 + 区间。
- 校准**只在单一市场内进行**（cn/intl 各自跑）。

## 6. 红线（违反任何一条都算 skill 用错了）

1. **发送永远人工**：skill 生成话术清单，用户复制粘贴发送。不代发私信、不代发邮件、
   不操作发送按钮。原因：平台风控 + 责任边界。
2. **验证码/扫码永远人工**：遇到即停，通知用户处理，从断点继续（每采一人立即落盘，
   中断不丢数据）。
3. **节奏**：两次页面访问间隔 ≥ `min_interval_seconds`（默认 45s，加随机抖动）；
   每 `batch_break_every` 个主页休息 `batch_break_minutes` 分钟；
   单日主页访问 ≤ `daily_profile_cap`；触发"频繁"提示或验证码，**当日停止采集**。
4. **首条触达不带任何链接**、单日新私信 ≤ `daily_dm_cap`（默认 20）——写在生成的
   每份触达清单顶部。
5. 只采集公开页面上人眼可见的信息；不绕过任何访问限制。

## 7. 字段所有权（ingest.py 强制执行）

- **机器列**（采集与计算类：followers、median_engagement、raw_samples、score_*、
  expected_exposure、cpm 等）：脚本可刷新，刷新时在轮次总结中报告变化。
- **人类列**（status、报价、budget_planned、approval、notes、日期）：脚本**永不覆盖**，
  冲突时警告并保留人类值。
- **log_outreach**：追加式，双方都只许追加。
- 每轮结束建议用户把 CSV 提交 git（或保存副本），diff 即审计。
- 完整字段字典、口径与市场子集：读 `schema/schema.md`。

## 8. 预期曝光估算（系数全部在 config，来源写进 AD 备注）

- 小红书：`预期阅读 = 中位赞藏 × xhs_read_multiplier × commercial_discount`（默认 33 × 0.7）。
  "藏"数优先实测（抽 1-2 篇同类笔记算藏赞比）；未抽样时用 `xhs_save_like_ratio_default`
  （默认 1.29，AI 工具类目抽样先验）并在 `engagement_basis` 标注 `likes_inferred`。
- 抖音：`中位播放 = 非置顶点赞中位 × douyin_play_per_like`（默认 26.5），
  `预期播放 = 中位播放 × commercial_discount`。拿到后台截图后用真实值替换，
  `engagement_basis` 从 `plays_inferred` 改为 `plays`。
- 博主后台数据、蒲公英/星图官方数据**永远优先于**一切估算值。
- **蒲公英对账（品牌号已开通时优先执行）**：在蒲公英按昵称查已入库博主，官方
  「阅读中位数」写入 `official_reads_median` 并覆盖 `expected_exposure`
  （data_confidence=high，AD 备注"蒲公英官方值 YYYY-MM"）；刊例价进 quote_*，
  `quote_notes` 标"蒲公英刊例"。凑够 ≥8 个「官方值 vs 估算值」对照后，用**比值中位数**
  修正 `xhs_read_multiplier`（人工确认后写回 config，CHANGELOG 记一行）。
  搜不到 = 未入驻或粉丝 <1000，保持估算值。操作手册：`playbooks/pgy.md`。

## 9. 平台细节与采集脚本

按平台读对应 playbook（含可直接执行的 JS 片段、登录态检查、已知坑与修复经验）：

- 小红书：`playbooks/xiaohongshu.md`
- 抖音：`playbooks/douyin.md`
- 蒲公英（小红书官方商单平台，品牌视角官方数据）：`playbooks/pgy.md`
- 海外平台（Instagram/TikTok）：v0.1 未实现。插槽已预留，不要临场发挥去采集
  海外平台——未经实测的流程不写、不跑。

## 10. 采集失效了怎么办（哨兵 → 定位 → 有界自修）

平台改版会让选择器失效，这是预期内的正常损耗，不是 bug。

**第 0 步永远是跑哨兵**：`tests/sentinels.yaml`（模板 `tests/sentinels.example.yaml`）
存着每平台 1 主 1 备"粉丝稳定、从不出爆文"的标杆账号。哨兵能正常出数 = 核心流程没坏，
刚才失败的账号是个例（特殊字符/未公开数据/被限流）；哨兵也挂 = 平台改版，进修复流程。
哨兵断言只写**结构性区间**（粉丝为纯数字且落在区间、可见作品 ≥N、中位可复算、无桶值），
不写精确值——标杆账号自己也会涨粉发文。用户说"跑一次健康检查"= 单独执行本步。

**哨兵怎么挑/换**：建库 ≥10 人后，按各行 `raw_samples` 的 最大值/中位数（爆文比）排序，
取每平台最低的 1 主 1 备（更新规律者优先）；用户说"重选哨兵"即按此推荐、经确认后更新
`sentinels.yaml`。冷启动期（库还空着）先用任意 2 个更新规律的垂类账号顶上，满 10 人再换。

修复流程：

1. 先跑登录态检查——**九成"失效"其实是被登出了**。
2. 打开哨兵主页，对照 playbook 里的选择器逐个在控制台验证，找出失效的那个。
3. 用浏览器工具查看新 DOM，更新 playbook 中对应 JS 片段，**只改选择器不改流程**。
4. 修好后在 playbook 文件顶部的 changelog 里记一行（日期 + 改了什么）。
5. ID 时间戳解码（decode_note_time.py）基于底层数据结构，几乎不会失效——
   当 DOM 全面失效时，它是最后的可靠数据源。

**自修边界（三条，越界即停）**：

1. 红线参数（pacing、每日上限、样本门槛）**永远不许自调**——靠"重试更快"来自愈的
   采集器，就是封号的标准路径。
2. 同一目标重试 ≤2 次，之后必须停下报告，不许换姿势硬试。
3. playbook 修改以 changelog 提案形式给用户过目后落盘，不做静默自改。

**日志三级**（scripts 与轮次报告统一使用，每条必须带"下一步"）：
`[停]` 触发红线（验证码/登录态丢失 → 当日停采）；`[降级]` 继续跑但 data_confidence=low；
`[拒绝]` 有意不输出（如样本 <8 不给校准结论）。
示例：`[停] 小红书出现扫码验证。下一步：今日停采，明天先跑哨兵再恢复。`

用户在任何终端/Cowork 会话里说"采集失效了，帮我修"，按上述流程执行即可。

## 11. 报告与交付物

- 每轮采集后：更新 CSV + 轮次总结（新增/淘汰/待复核清单 + 风控事件）。
- 用户要报告时：跑 `scripts/report_html.py` 生成自包含 HTML（漏斗、分档 CPM、
  互动分布、数据新鲜度告警——`collected_at` 超 30 天的行标"待复核"）。
- R 用户可选：`analysis/report.qmd`（Quarto，读同一份 CSV，非必需）。
- 需要给老板 xlsx 时，从 CSV 导出并映射中文表头（映射表在 schema.md）。

## 12. 脱敏导出（维护者专用）

`scripts/export_template.py` 从本仓库生成公开模板版：清空示例话术中的公司内容、
保留通用方法论与关键词库、数据文件只留表头。发布前人工过一遍产物再推送。
