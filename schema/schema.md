# 数据字典（db_cn.csv / db_intl.csv / channels.csv / results.csv）

原则：**英文 snake_case 表头**（代码友好、可公开）；**粉丝等计数存绝对值**
（"万"单位是历史数据事故的帮凶，只在导出层出现）；派生值不存储（量级标签由 followers
现算，避免"粉丝改了标签没改"的脏数据）。

四张表的分工：`db_cn.csv` / `db_intl.csv` 是**付费投放决策表**（按市场分开）；
`channels.csv` 是**免费分发渠道池**（不进博主库、不计投放预算，见下）；
`results.csv` 是**效果事实表**（发布后回填，喂二代校准）。

> **列顺序原则上是追加式的**：新增字段一律加在表尾（`official_reads_median` 就是这么进来的，
> 在 db_cn.csv 是第 32 列、db_intl.csv 是第 36 列，而不是本文档表格里的相对位置）。
> 所有脚本按字段名寻址（`csv.DictReader` / `DictWriter`），所以文档表格按语义分组排列，
> 与物理列序不一致是正常的，**不要为了对齐文档去重排 CSV 列**。唯一例外是海外库的
> `contact_methods`：为便于人工审核，物理位置固定紧跟 `email`。

## db_cn.csv / db_intl.csv 公共字段

| 字段 | 类型 | 所有权 | 说明 |
|---|---|---|---|
| id | str | 机器 | CN-001 / INTL-001，前缀区分市场 |
| platform | str | 机器 | cn 库：小红书 / 抖音；intl 库：Instagram / X（值区分大小写，按平台官方写法） |
| name | str | 机器 | 昵称 |
| niche | str | 人类 | 垂类 |
| followers | int | 机器 | 粉丝绝对数。**非纯数字禁止入库**（防"1千+"桶值事故） |
| posts_30d | int | 机器 | 近30天条数，ID时间戳解码得到 |
| median_engagement | int | 机器 | 中位赞藏(小红书)/中位播放(抖音) |
| engagement_basis | str | 机器 | likes_saves / plays / plays_inferred / likes_inferred |
| raw_samples | str | 机器 | 原始10篇数据(分号分隔)，口径重算的依据 |
| traffic_type | str | 机器 | fan_based / search_boosted |
| data_confidence | str | 机器 | high / low（登出桶值、样本过少自动置 low） |
| collected_at | date | 机器 | 采集日期，报告据此算新鲜度 |
| machine_gaps | str | 机器 | 无法填充的机器字段及原因，格式 `字段:reason_code|字段:reason_code`；只能使用英文 snake_case 原因码。核心机器字段必须“有值或有原因”二选一，禁止无解释空白 |
| score_fit / score_engagement / score_audience / score_content / score_value | int | 机器 | 五维分，缺的留空 |
| score_total | float | 机器 | 按可用维度归一化 |
| status | str | 人类 | **漏斗阶段**：待触达/已私信/已回复/**已拒绝**/已报价/洽谈中/待老板审批/已签约/已发布/婉拒放弃/无回应。`已拒绝`=对方明确谢绝（2026-08-17 起用），与 `婉拒放弃` 分开：前者是对方关了门、后续动作只剩换品类或换时机，后者含「我们主动放弃」，两者后续动作不同，不该共用一个值。取值须与 `report_html.py` 的 order 列表逐字一致；**筛选结论态**：淘汰。`roadtrip-intl` 采用 direction-only：只有垂类/目标地域明确不符才淘汰，其余用待触达；待审/备选/观察/放大器池为待迁移的历史状态，风险应写 `approval/notes` |
| first_contact_date / last_followup_date | date | 人类（`first_contact_date` 例外见下） | 触达/跟进日期 |
| quote_image / quote_video | int | 人类 | 报价，**纯数字，只存博主底价** |
| quote_notes | str | 人类 | "+200平台费"这类说明 |
| expected_exposure | int | 机器 | 预期阅读/播放。**官方值优先**：有 official_reads_median 时以其覆盖 |
| official_reads_median | int | 机器 | 平台官方后台口径的阅读/播放中位数（蒲公英/星图/后台截图），估算系数校正的对照锚点 |
| budget_planned | int | 人类 | 实付全款 = 报价×(1+platform_fee_rate) |
| cpm | float | 机器 | = budget_planned ÷ expected_exposure × 1000 |
| approval | str | 人类 | 待审/✔通过/✘否决/暂缓/拒绝（"拒绝"用于报价或门槛双重不合格的改判，见 v0.3.3 INTL-014） |
| log_outreach | str | 追加 | `YYYY-MM-DD 事件`，永不改写 |
| notes | str | 人类 | 内部判断、风险标记、口径调整原因 |
| source_keyword | str | 机器 | **发现层写入**：这个候选是从哪个搜索词找到的，原样存词、不归一化。取不到写 `unknown` |
| niche_match_grade | str | 机器 | **验证层写入**：`强匹配`/`中匹配`/`弱匹配`/`unknown`。是 `verified_precision` 的分子来源 |
| profile_url | str | 机器 | 主页链接 |

### 例外：`status` / `first_contact_date` 在触达登记时由脚本代写（2026-08-11 起）

`outreach_batch.py mark-sent` 会在登记"已发送"的同时改这两列。这是对"机器不碰人类的列"
的一处**有意开的口子**，原因：审计日志说已发、库里还写「待触达」会让漏斗虚高，
并让下一批 `generate` 重复选中同一个人。两条保护写在代码里，缺一不可：

- **只从「待触达」推进到「已私信」。** 已回复/已报价/洽谈中等后段状态一律不动，
  并在输出里告警——否则重跑一次 mark-sent 会把人从「已回复」倒退回「已私信」，属于毁数据。
- **`first_contact_date` 只在为空时填，永不覆盖**（它是"首次"触达日）。

其余人类列（`quote_*`、`approval`、`notes`、`last_followup_date`）仍然脚本永不写。

## db_intl.csv 额外字段（海外，2026-07-28 起已启用）

四列都在实际使用中，不再是预留位（截至 2026-07-31，库内 23 行的填充情况见下）。

| 字段 | 说明 | 填充 |
|---|---|---|
| email | 商务邮箱（原定海外主触达渠道；**当前发件域 DMARC 未通过，邮件线阻塞中**，首选 Collabstr 站内提案） | 6/23 |
| language | 内容语言 → 决定中文话术还是英文邮件模板 | 18/23 |
| country | **博主本人**所在国：时区/结算/合规判断（值用 ISO 两字母：US / CA）。**不是受众地域**，两者常年不一致，见下 | 13/23 |
| audience_geo_top3 | 机器 | **受众**地域 top3 及占比，形如 `US 95 / DE 1 / AU 1`；未知写 `unknown`（按不合格处理） | 采集时必填 |
| audience_geo_source | 机器 | 取值来源：`creator_insights` / `collabstr_analytics` / `pillar_media_kit` / `unknown`，来源不同可信度不同 | 同上 |
| currency | 报价币种（校准分币种进行的前提，海外恒为 USD） | 18/23 |
| contact_methods | `email` 以外的所有已知公开触达路径，物理列紧跟 `email`；使用 `类型:值`、多项以 ` | ` 分隔。允许类型包括 `collabstr_proposal`、`instagram_dm_candidate`、`x_dm_candidate`、`telegram`、`website_form`、`website`、`link_in_bio`、`booking_link`、`manager_email`、`discord_business`。邮箱只写 `email` 专栏，禁止在这里重复。其中 `*_dm_candidate` 仅表示主页可作为候选入口，DM 是否开放仍需逐主页确认 | 采集时增量补充 |
| contact_source | 联系方式来源与置信说明；不得只存联系方式而不留来源 | 采集时增量补充 |
| contact_verified_at | 最后核验公开联系方式的日期。历史回填沿用原 `collected_at`，不冒充当天重新访问 | 采集时增量补充 |

### source_keyword / niche_match_grade（2026-08-14 补列）

这两列共同支撑 SKILL.md 的关键词反馈闭环：
`verified_precision = (强匹配 + 中匹配) ÷ 已判定人数`，`unknown` 不进分母。
**缺任何一列该计算都做不出来**——只有来源词没有档位，分子拿不到；只有档位没有来源词，
算出来的数分不到具体词头上。

补列前这两个信息一直写在 `notes` 自由文本里，且两条线各写各的：IG 线写
`source_keyword=overlanding`（字段名正确、存错地方），X 线写 `来源词：claude code｜…`。
2026-08-14 用 `scripts/migrate_source_keyword.py` 迁进正式列，迁移纪律是**只搬运不推断**：
notes 里明确写了的才搬，没写的填 `unknown`。**已知某一批整体用了哪几个搜索词，不构成
把某一行归给其中某个词的依据**——那样填出来的 precision 是自己造的。

`niche_match_grade` 也不从淘汰原因倒推：「因粉丝不足淘汰」通常意味着**词找对了、人不合规**，
把它记成垂类不匹配会让好词被误判成 `weak_keyword` 而停用。

迁移后现状：db_intl 100 行中 `source_keyword` 有值 32 行、`niche_match_grade` 有值 18 行，
其余为 `unknown`。样本量足够前不要跑 precision 下停用词的结论。

未填充的行都是从种子文件合并进来、尚未登录态复核的候选——**留空是正确状态**，
按纪律不填想象值。海外线 v0.1 口径不采 IG 中位互动，所以
`median_engagement` / `engagement_basis` / `traffic_type` / `expected_exposure` /
`cpm` / `official_reads_median` 在 intl 库**全库为空是设计如此**，不是漏采；
`data_confidence` 全库为 `low`，洽谈阶段补采播放中位后才逐个升级。

### 海外平台预期曝光口径（Instagram / X）

不得用粉丝数乘固定比例直接生成 `expected_exposure`。海外线只接受可复算的播放/浏览样本：

- **Instagram Reel**：取最近 10 条非置顶、同类型 Reel 的公开 views，写入
  `raw_samples`，其中位数写 `median_engagement`，`engagement_basis=ig_reels_views`。
  在没有成交结果校准系数前，`expected_exposure` 暂等于该中位数，并在 notes 标
  `organic_median_proxy`、`data_confidence=low`。公开 views 含重播，不等于独立触达人数。
- **Instagram 图文/Carousel**：公开页面没有同口径播放数，不用点赞数反推曝光。
  只有博主提供 Insights 后，取最近同类型内容的 `accounts reached` 中位数，写入
  `official_reads_median` 并覆盖 `expected_exposure`；否则保持空值。
- **X**：取最近 10 条非置顶、非回复、非转发、与合作形式相近的原创帖公开 view counts，
  写入 `raw_samples`，中位数写 `median_engagement`，`engagement_basis=x_post_views`；
  `expected_exposure` 暂等于该中位数并标 `organic_median_proxy`、`data_confidence=low`。
  X view counts 不是独立用户数，重复查看和作者自看都可能计数。
- 样本不足 10 条或平台不显示 view counts 时保持空值，不用 followers/likes 补猜。
- `results.csv` 对同市场累计至少 8 个 `views_d7 / expected_exposure` 对照后，才计算
  商单折损系数（比值中位数），经人工确认后写入 preset。届时
  `expected_exposure = organic_median × commercial_discount_intl`。
- CPM 仍为 `budget_planned / expected_exposure × 1000`；曝光为空时 CPM 必须为空。

## channels.csv（分发渠道池 · 与博主库彻底分开）

**为什么单独一张表**：技术圈的影响力与粉丝数弱相关——实测出现过 13.8k 星 awesome
列表维护者 X 仅 42 粉、90.9k 星列表作者仅 1,017 粉。这类对象**粉丝不达付费门槛，
但持有免费上榜位**（awesome 列表、导航站、社群等），价值真实却不是投放位。

纪律（SKILL.md 第 2 节红线，2026-07-30 立）：

- **不进博主库**：不写入 `db_*.csv`，不占 CN-/INTL- 编号，用独立的 `CH-0xx`。
- **不计投放预算**：不走报价流程，`quote_*` / `budget_planned` / `cpm` 概念在这里不存在，
  成本列通常是"免费"。
- **不参与打分排序**：免费位和付费位混进同一张表排序会互相污染，所以从记录起就分开。
- **触达走另一套话术**：`templates/outreach_en.md` 的 G 类「awesome 列表上榜」，
  提交 PR / issue 而非议价。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str | `CH-001` 起，与 db 的 CN-/INTL- 编号空间隔离 |
| channel_type | str | 渠道形态，如 `awesome_list`（后续可扩导航站/社群/newsletter） |
| name | str | 维护者姓名或组织名 |
| platform | str | 渠道所在平台（如 GitHub），**不是**博主的社媒平台 |
| asset | str | 具体资产名，即那个上榜位本身（如 `awesome-claude-skills`） |
| reach_proxy | str | 影响力代理指标，**带单位存字符串**（如 `13800 stars`）。故意不存 int：<br>星数与粉丝量不可比，存成数字容易被误当 followers 参与计算 |
| handle_or_url | str | 维护者主页/社媒链接 |
| contact | str | 可用联系路径（GitHub / 个站 / 邮箱） |
| status | str | 待联系 / 待评估 / 已提交 / 已上榜 / 放弃（评估指先判断该列表的收录标准值不值得投工） |
| cost | str | 通常"免费"；留字符串以容纳"需赞助"这类非金额条件 |
| notes | str | 淘汰出博主库的原因、上榜价值判断、原 INTL 编号溯源 |
| logged_at | date | 记录日期 |

> 一个对象可以**先在 db 里被淘汰、再进 channels**（CH-001/002 就是这么来的，
> notes 里保留原 INTL 编号）。反过来不成立：channels 里的对象不会因为涨粉自动回到博主库，
> 要回去得重新按门槛采一次粉丝数入库。

## results.csv（效果事实表，与决策表分离）

| 字段 | 说明 |
|---|---|
| result_id | 自增 |
| campaign | 战役标识（如 `roadtrip-2026Q3`）。博主库是跨战役的关系资产，效果行按战役归属 |
| creator_id | 外键 → db 的 id |
| market | cn / intl |
| post_url | 已发布内容链接 |
| format | 图文 / 视频 |
| publish_date | 发布日 |
| views_d1 / views_d7 | D1/D7 播放或阅读 |
| engagement_d7 | D7 赞评藏转合计 |
| github_uv_7d | 归因到该内容的 GitHub UV |
| cost_actual | 实际结算金额 |
| notes | 备注 |

> results 表喂第二代校准：对比 expected_exposure 与真实 views_d7，回归出估算偏差系数，
> 修正第 8 节的乘数——这才是曝光公式的终极校准。

## 导出 xlsx 的中文表头映射（给老板看时用）

id→编号, platform→平台, name→昵称, niche→垂类, followers→粉丝数,
posts_30d→近30天条数, median_engagement→中位赞藏/播放, status→触达状态,
quote_image→图文报价, quote_video→视频报价, expected_exposure→预期曝光,
budget_planned→拟投预算, cpm→预估CPM, approval→老板审批, notes→备注,
profile_url→主页链接, log_outreach→沟通记录
（score_* 及 raw_samples/engagement_basis 等诊断列导出时可隐藏；`collected_at` 和
`machine_gaps` 必须导出为「资料采集日」「机器缺口原因」，不得只埋在备注里）
