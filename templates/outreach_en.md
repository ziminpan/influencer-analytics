# Outreach templates · EN (intl market)

> **草案 v0.2（2026-07-30）。发件身份已定；A1 措辞待一项平台确认；发送前仍需维护者过一遍。**
>
> **发件身份**：占位符 `{{sender_name}}` / `{{sender_email}}` / `{{sender_display}}`，
> 真实值在 `presets/<preset>.yaml` 的 `outreach.sender` 段（预设不参与模板导出）。
> 显示名必须与发件地址一致（Google 显示名规则要求）。
> ⚠ **发第一封前必须确认 DMARC PASS，且 SPF 或 DKIM 至少一路与 From 域对齐**：
> 这是本项目的冷邮件发信硬门禁，而本库博主邮箱几乎全是 @gmail.com。自查方法见文末「发送前检查」。
> 占位符同中文版：`{{name}}` `{{work}}` `{{brand}}` `{{product_pitch}}` `{{repo_slug}}`
> `{{web_fallback}}`。发送永远由人手动完成。
>
> **与中文版的三处结构性差异**（不是翻译，是渠道差异）：
> 1. **Collabstr 是首选渠道**（`primary_channel: collabstr`）——平台内有担保和明码价，
>    第一条消息不需要问"接不接商务合作"，直接按其 listing 下单意向谈；冷邮件才需要自我介绍。
> 2. **不要求后台数据截图**。v0.1 口径 IG 不采中位互动，且海外博主对"发后台数据"
>    的接受度低于国内；改为洽谈中自然索取 recent reels 播放中位（模板 B 里是可选项）。
> 3. **无报备费概念**。不问"报备价/非报备价"，直接问 flat rate + usage rights。

## A1 · Collabstr「Negotiate a Package」提案（首选，2026-07-30 实测定稿）

> 走博主主页的 **Negotiate a Package** 按钮（Collabstr 无自由私信）。提案内容：

```
Hi {{name}}. I came across your profile while looking for creators covering
North American road trips, and your {{work}} really stood out.

I'm with {{brand}}. {{product_pitch}}

Proposing one {{package_name}} at {{offer_usd}}. Three things I'd like to confirm
before we finalize:

1) Earliest availability.
2) Whether that rate is still current.
3) Usage rights. We'd like to repost on our own channels and project page with
   credit and a link back to you. Included, or priced separately? (Organic
   reposting only, not paid ads.)

We supply the demo material, so production effort on your end is low, and we're
not looking to change how you normally post.
```

> `{{package_name}}` / `{{offer_usd}}` 按主页套餐表填——**议价前必看主页全表**，
> 卡片起步价可能远低于主页实际套餐价（collabstr.md 第 10 坑）。
> 提案被 Accept 后才 Add to Cart，不要直接下单。

## A2 · 冷邮件首次触达（无 Collabstr listing 时，2026-08-11 定稿版）

> `{{feature_pitch}}` 取自 `presets/<preset>.yaml` 的 `product.feature_pitch_email`
> ——2026-08-11 已核实产品实际功能（读 GitHub README + 官网），不要凭印象改写：
> 是"预订倒计时+指向官方系统"，不是"帮你订";是"季节性规划时规避封路"，
> 不是"实时封路提醒"。写错会在冷邮件里对博主做出产品不具备的承诺。

```
Subject: Quick one about a road-trip collab, {{brand}}

Hi {{name}},

I've been going through a lot of road-trip / outdoors accounts this week, and
{{hook}} was one of the ones that actually stopped my scroll.

I'm {{sender_name}}, I work on {{product_name}} at {{brand}}. It's a free,
open-source AI trip planner ({{web_fallback}}, code at {{repo_url}}).
{{feature_pitch}}

If you're open to it, three quick things:

1. Flat rate for one piece (whichever format you'd usually recommend: Reel,
   static, whatever fits your feed).
2. Earliest slot you've got.
3. Usage rights. We'd want to repost on our own channels with credit, is that
   in the rate or separate? Asking upfront so nobody gets surprised later.

We hand you the demo material so it's low-lift on your end, and we're not
trying to change how you normally post. If it doesn't feel like you, it's not
worth either of our time.

Either way, love what you're putting out there.

{{sender_name}}
{{sender_title}}, {{brand}}
{{sender_email}}
```

> 批量生成用 `scripts/outreach_batch.py generate`（只生成草稿，不发送，见脚本内
> docstring）；发送后用同脚本的 `mark-sent` 子命令登记 `log_outreach`，两步不合并，
> 发送键永远由人手动按（SKILL.md 红线 1）。

## B · 询价与细节确认（对方表示有兴趣后）

```
Great. A few things to confirm:

1) Flat rate for one piece: Reel vs. static post / carousel, whichever you'd
   normally recommend for this kind of content.
2) Earliest available slot.
3) Usage rights: we'd like to repost the piece on our own channels and project
   page, with credit and a link back to you. Is that included at the rate above,
   or priced separately? (Asking now so there are no surprises later, and we're not
   asking for paid-ad usage, just organic reposting.)
4) Optional, only if you're comfortable: a rough sense of recent Reel view
   numbers helps us size the budget. Not a requirement.

Once the rate and timing work, internal approval takes 2–3 business days and
then we can lock the slot.
```

## C · 跟进（一次即止，带新信息，不复读）

```
Hi {{name}}, following up once in case this got buried.

One thing I should have mentioned: the angle doesn't have to be a product demo.
What's worked better is a real trip planned with it. Something like "I let an AI plan three
days through {{region}} and drove it," in your own voice and format.

If it's not a fit, no problem at all, and I won't keep pinging you.
```

## D · 议价（报价超预算，参考 $2,500 级异常值处理）

```
Thanks for getting back with that. Being straight with you: it's above what we
budgeted per piece this round. A couple of options, if you're open to either:

- We run one piece at {{X}} this round; we supply all the demo material so your
  production time is minimal. If it performs, we come back at your full rate
  with a larger buy.
- Or we start with a lower-lift format (a single Reel rather than a full set)
  at a rate that fits.

Also happy to include repost rights with credit either way. If neither works,
completely understood.
```

## E · 合作确认 + 内容 Brief（成交后）

```
Locked in, sending the material pack over today. A few specifics, everything
else is yours to shape:

1) Core moment to show: going from one sentence to a full planned itinerary page.
   Use our screen recording, or run it yourself in about two minutes.
2) Please include: GitHub search for "{{repo_slug}}" on screen briefly, plus a
   spoken or captioned "it's free and open source if you want to try it."
3) We'd like one look before it goes live, checking factual things only
   (command names, spelling). We won't touch your style or edit.
4) Please mark it as sponsored, using Instagram's "Paid partnership" label or a
   clear #ad in the caption. This is a requirement on our side, not a preference.
5) Seven days after posting, a screenshot of the post's view/reach numbers if
   that's easy for you.

Anything unclear, just ask.
```

## F · 婉拒备库（不烧桥）

```
Thanks for the quote, and for the quick reply. Budget's tight this round so we're
going a different direction, but I'd like to keep you on our shortlist for the
next one.

Separate from any paid work: the project is open source and free, so if you ever
have a road-trip planning piece on your own schedule, you're welcome to the demo
material with no strings.
```

## G · 分发渠道联系（awesome 列表上榜，非付费合作 — 见 data/channels.csv）

```
Subject: Submission for {{list_name}}

Hi {{name}},

You maintain {{list_name}}. Thanks for keeping it current, it's how I found
several tools I now use.

I'd like to submit {{repo_slug}}: {{product_pitch}} It's MIT licensed and free.

Happy to open a PR following your contribution format rather than asking you to
do the work. <账号51> let me know if it fits the list's scope first.

{{sender_name}}
```

> 注：G 类联系对象在 `data/channels.csv`，**不是**付费博主库成员。
> 这类账号的价值是免费上榜位，不要按报价流程处理，也不要计入投放预算。

## 已定项（2026-07-30 维护者决策）

1. **发件身份**：真人署名 + 团队可收信箱，值见 preset `outreach.sender`。
   建议该地址设成共享信箱或加团队委派——署名真人提高回复率，共享收件保证休假不断线。
2. **usage rights 在报价阶段一次问清**（模板 B 第 3 项），不等发布后再谈：
   发完再要授权就没有议价权了。本轮只要自然流转发权，**不要 paid-ad 授权**
   （后者行业加价常在原价 30%–100% 以上，本轮预算不覆盖）。
3. **披露要求进 Brief**（模板 E 第 4 项）：要求博主用 IG「Paid partnership」标签或
   明确 #ad。美国 FTC 背书指引要求披露实质关联，加拿大竞争局类似——
   这是**品牌方的合规风险**，不是博主的偏好问题，所以写成 requirement 而非 request。

## 待确认（一项，不阻塞其余）

- **A1 措辞**：Collabstr 是否允许**下单前**免费私信尚未实测确认
  （playbook 只写了"平台内下单/沟通有担保"，未区分先后）。
  若不支持下单前私信，A1 需改为下单后的第一条消息，或改走 A2 冷邮件。
  确认后定稿。

## 发送前检查（每次波段第一封之前）

1. **域名认证自查**（2 分钟）：用 `{{sender_email}}` 给任一外部 Gmail 地址发一封测试信 →
   在 Gmail 里打开 → 右上「⋮」→「显示原始邮件」。必须看结果和域名，不只看 PASS 字样：
   - `DMARC=PASS`；
   - DKIM `d=` 或 SPF `MAIL FROM/Return-Path` 至少一个与 `From` 域对齐。
   不满足时保持 preset 的 `domain_auth_verified: false`，冷邮件不发。SPF PASS 但
   Return-Path 是服务商域，仍不能为 DMARC 提供对齐。
   （Google Workspace 的 DKIM 默认是关的，需在管理后台手动开启；
   走飞书/第三方邮箱的，需在其后台配「自有域 DKIM」，否则签名域是服务商域名、
   与 From 域不对齐 → DMARC 判 FAIL，即使 SPF/DKIM 各自都 PASS。）
   SPF 只保留一条 `v=spf1` TXT，不得猜测 include；DMARC 新开通先用 `p=none`。
2. **不需要向 Google「注册」或申请白名单**——Google 明确不受理白名单申请。
   可选：注册 Google Postmaster Tools 监控本域垃圾投诉率（要求 <0.3%），
   这是监控工具，不是发信许可。
3. **节奏**：18 人分数天发完，不要一次群发。域名此前若无发信历史，
   突然的批量会被当异常。
4. **每封都要能对应到来源**：该邮箱是从哪儿取的（IG bio / Collabstr 主页），
   记进 `log_outreach`——加拿大 CASL 下"公开发布的商务邮箱"构成默示同意的前提是
   能说清来源。本库有 4 位加拿大博主（INTL-003/004/005/012）。
