# 数据字典（db_cn.csv / db_intl.csv / results.csv）

原则：**英文 snake_case 表头**（代码友好、可公开）；**粉丝等计数存绝对值**
（"万"单位是历史数据事故的帮凶，只在导出层出现）；派生值不存储（量级标签由 followers
现算，避免"粉丝改了标签没改"的脏数据）。

## db_cn.csv / db_intl.csv 公共字段

| 字段 | 类型 | 所有权 | 说明 |
|---|---|---|---|
| id | str | 机器 | CN-001 / INTL-001，前缀区分市场 |
| platform | str | 机器 | 小红书 / 抖音 |
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
| score_fit / score_engagement / score_audience / score_content / score_value | int | 机器 | 五维分，缺的留空 |
| score_total | float | 机器 | 按可用维度归一化 |
| status | str | 人类 | 待触达/已私信/已回复/已报价/洽谈中/待老板审批/已签约/已发布/婉拒放弃/无回应 |
| first_contact_date / last_followup_date | date | 人类 | 触达/跟进日期 |
| quote_image / quote_video | int | 人类 | 报价，**纯数字，只存博主底价** |
| quote_notes | str | 人类 | "+200平台费"这类说明 |
| expected_exposure | int | 机器 | 预期阅读/播放 |
| budget_planned | int | 人类 | 实付全款 = 报价×(1+platform_fee_rate) |
| cpm | float | 机器 | = budget_planned ÷ expected_exposure × 1000 |
| approval | str | 人类 | 待审/✔通过/✘否决/暂缓 |
| log_outreach | str | 追加 | `YYYY-MM-DD 事件`，永不改写 |
| notes | str | 人类 | 内部判断、风险标记、口径调整原因 |
| profile_url | str | 机器 | 主页链接 |

## db_intl.csv 额外字段（海外，v0.1 预留不启用）

| 字段 | 说明 |
|---|---|
| email | 商务邮箱（海外主触达渠道） |
| language | 内容语言 → 决定中文话术还是英文邮件模板 |
| country | 时区/结算/合规判断 |
| currency | 报价币种（校准分币种进行的前提） |

## results.csv（效果事实表，与决策表分离）

| 字段 | 说明 |
|---|---|
| result_id | 自增 |
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
（score_* 及 raw_samples/engagement_basis 等诊断列导出时可隐藏）
