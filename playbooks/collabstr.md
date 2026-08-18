# Playbook · Collabstr（海外创作者市场平台，发现层首选）

> changelog
> - 2026-07-30（v0.2）：新增第 8/9 坑（登出态主页粉丝归零、真实 IG 链接需登录）与
>   「触达入口」章节（Negotiate a Package = 下单前协商路径，非自由私信）。
> - 2026-07-28（v0.1）：首版。road trip / vanlife / overlanding / hiking 四轮共 ~160 卡
>   实测定稿；national parks 关键词分词坑、Location 筛选失效、username≠IG handle
>   失配等 7 个坑全部来自实测。

## 这是什么、为什么是海外发现层首选

Collabstr = 海外创作者接单市场（collabstr.com），创作者自报垂类 + 明码标价 + 粉丝数。
**IG 5 标签限制（2025-12）后 hashtag 检索面萎缩，市场平台取代标签搜索成为 IG 找号主路径**
（2026-07-28 关键词验证报告的核心结论，见 海外社媒/ 文件夹 docx）。

三个实测优势：
- **粉丝数可信**：7/7 抽查与 IG 实测一致（误差 <10%），可直接用于粉丝段筛选，
  IG 核验的价值是核内容方向，不是核数字。
- **报价透明**：$50–$600 主带正好覆盖 3千–5万粉层；$50 档大量存在，试错成本低。
- **触达内建**：平台内下单/沟通有担保，可替代冷邮件（发送仍永远人工）。

## 登录态检查

打开 collabstr.com，右上角出现头像字母 = 已登录。未登录部分筛选器受限，停下请用户处理。

## 发现流程（实测）

1. **直达 URL**（跳过表单交互，最快）：
   `https://collabstr.com/influencers?p=instagram&c=<关键词>`（多词用 `+` 连接）。
   打开后**必须确认 `<h1>` 标题含目标关键词**（如 "Instagram Vanlife Influencers"）——
   这是关键词生效的唯一可靠信号。
2. **采集卡片**（滚动 8 轮 ×1700px，约 40 卡见底）：
   ```js
   window.__coll = {};
   const seen = window.__coll;
   function harvest() {
     document.querySelectorAll('.profile-listing-holder').forEach(card => {
       const followers = card.querySelector('.profile-listing-followers')?.textContent.trim() || '?';
       const link = card.querySelector('a[href]');
       const href = link ? link.getAttribute('href').split('?')[0] : null;  // 必须去 query string
       const full = card.innerText.replace(/\n+/g, ' | ').slice(0, 200);
       const key = href || full.slice(0, 60);
       if (!seen[key]) seen[key] = { followers, full, href };
     });
   }
   for (let i = 0; i < 8; i++) { harvest(); window.scrollBy(0, 1700); await new Promise(r => setTimeout(r, 1200)); }
   harvest();
   'TITLE=' + document.querySelector('h1')?.innerText + ' COUNT=' + Object.keys(seen).length;
   ```
3. **分块导出**：一次输出 40 行会被截断，按 slice 分 2–3 次导出；
   每轮采完立即落盘到本地文件（中断不丢数据）。
4. 卡片文本结构 `昵称 | (评分5.0) | bio | $价格 | 城市, 州, 国家`——评分行会顶掉 bio 位，
   解析时先剔除 `/^5\.0$|^4\.\d$/` 再取 bio。

## 已知坑（全部实测）

1. **关键词分词坑**：`national parks` 被分词匹配成 `parks` → 结果全是主题公园/迪士尼/
   跑酷博主，整轮报废。多词关键词跑完第一屏先人工看 5 张卡再继续。
   实测可用：`road trip` / `vanlife` / `overlanding` / `hiking`；报废：`national parks`。
2. **Location 筛选器不生效**：选了 United States 结果照样混欧洲账号。
   放弃筛选器，用卡片末位的城市字段手工过滤（`, US` / `, CA` 后缀）。
3. **Followers 滑杆无精确输入**：0–100万拖杆，3千/5万这种精确值拖不准。
   放弃滑杆，直接读卡片粉丝数过滤。
4. **前松后紧的排序**：每轮约前 15 卡与关键词强相关，之后逐渐退化为泛 lifestyle 填充。
   尾部卡片的垂类判断必须依赖 IG 核验，不能信卡片。
5. **username ≠ IG handle**（高频！）：Collabstr 主页路径 `/username` 与其 IG handle
   经常不同（首轮 25 个 IG 直连中 12 个失配）。**尾部填充卡失配率显著更高**。
   失配处理：进 `collabstr.com/<username>` 主页，从社交链接区取真实 IG 地址——
   不要按用户名瞎猜 IG。

   ⚠ **进了主页就必须把整页采完，不能只取 IG 链接**（2026-08-17 立，代价见下）。
   原流程只写了"取 IG 地址"，于是首轮 12 个失配账号的主页**都真的打开过**，
   而受众地域、均播、互动率、全套餐档位就在同一页的社交链接区下方，**一个都没被记**。
   直到两周后、发出 26 封邮件之后才回头看，发现三个人的受众根本不在北美：
   INTL-011 俄29/乌17/哈12、INTL-057 巴西 94%、INTL-072 印度 71%——
   而她们的注册城市分别是 Greenville SC、Las Vegas NV、Calgary AB，全部通过了
   按"博主城市"做的地域门槛。**页面就在眼前，多采这些是零额外风控成本。**

   主页必采清单：

   | 采什么 | 存到哪 | 为什么 |
   |---|---|---|
   | **Analytics → Audience Location** top3 及占比 | `audience_geo_top3` + `audience_geo_source=collabstr_analytics` | **决定这单有没有用**；平台核验、免费 |
   | Audience Age / Gender | `notes` | 画像分与内容角度判断 |
   | **Average Views / Engagement** | `notes` | ⚠ 是**均值不是中位数**，爆款会拉高数倍，**不可直接写 expected_exposure**（schema 要求近 10 条同类型公开播放的中位数） |
   | **全部套餐档位与价格**（不只起步价） | `quote_notes` | 只记起步价会让后续拿"图文起步价"去比"Reel 直报价"，得出错误的价差结论 |
   | 平台评价数与星级 | `notes` | 有成交历史的比零评价的可信 |
   | 是否有 "Negotiate a Package" | `notes` | 平台支持自定义条款，走平台与要定制不是二选一 |

   **失配分两类（2026-07-30 对 12 人全量回捞后归纳，12/12 成功）**：

   | 类型 | 占比 | 规律 | 能否离线推导 |
   |---|---|---|---|
   | **标点被吞** | 7/12 | Collabstr 把 IG handle 里的 `.` `_` 全部删掉：<br>`<账号28>`→<账号28>、`<账号29>`→<账号29>、<br>`<账号30>`、`<账号31>`、`<账号36>`、<br>`<账号37>`、`<账号38>` | **可以**：在字母间插 `.`/`_` 枚举再验证 |
   | **完全改名** | 5/12 | Collabstr 用真名、IG 用品牌名（或反之）：<br>`<账号32>`→<账号32>、`<账号33>`→<账号33>、<br>`<账号35>`→<账号35>、`<账号39>`→<账号39>；<br>或缩写：`<账号34>`→<账号34> | **不可以**：必须进主页取链接 |

   实务顺序：先按「标点被吞」规律枚举猜测（零访问成本），猜不中的才进主页取链接，
   能省掉约六成的主页访问预算。

   **失配类型能预测垂类命中率（2026-07-30 全量 IG 核验后发现，强信号）**：

   | 失配类型 | n | 可触达 | 边缘 | 淘汰 | 淘汰率 |
   |---|---|---|---|---|---|
   | 标点被吞 | 7 | 5 | 1 | 1 | **14%** |
   | 完全改名 | 5 | 0 | 1 | 4 | **80%** |

   机理：Collabstr 用户名若是**内容品牌 handle 去标点**，说明此人以该垂类立号、
   listing 是本业；若用户名是**真名**而 IG 是另一个品牌名，往往是泛人设创作者
   把自己挂进多个类目，被关键词当噪音扫进来（实测淘汰的是美妆号、普拉提工作室、
   人生教练号、印度自驾号各一——后者垂类完美但地域不符）。

   **据此排序**：回捞时先做标点类（命中率高），改名类放到最后甚至可跳过——
   若预算紧张，改名类的期望产出约为标点类的 1/5。

   **副产品**：IG handle 本身常泄露垂类，回捞时顺手当垂类信号用——
   `<账号33>`（普拉提）、`<账号37>`（西高地白梗，疑宠物号）、
   `<账号39>`（摩托）三个据此直接标回「待查」等 IG 核验，不进待触达队列。
6. **输出含 query string 会被安全层拦截**：卡片 href 带 `?ph_id=...`，直接输出会触发
   "[BLOCKED: Cookie/query string data]"。`href.split('?')[0]` 后再输出。
7. **URL 参数 `platform=/category=` 无效**，生效的参数名是 `p=` / `c=`（见第 1 步）。
8. **登出态博主主页粉丝数全归零**（实测显示 `0.0k Followers` ×3，且提示
   "Create a free account to unlock analytics"）——与国内「登出态桶值事故」同类。
   **主页取数必须登录**；发现层的列表卡片粉丝数不受此影响（卡片仍出真值），
   两处状态要分别确认。落库前仍按纯数字断言，`0.0k` 一律视为无效值不入库。
9. **登出态主页的社交链接区只有 Collabstr 自己的 IG/TikTok**，取不到博主真实 IG 地址。
   第 5 坑的「回主页取真实 IG 链接」修正流程**必须在登录态下执行**。
10. **主页套餐价可能远高于列表卡片起步价**：卡片显示的是最低档（如 $50-460 带），
   主页展开后按形式分档可能高一个量级（实测 <账号T> 卡片无价、主页 Reel $2,500）。
   **粗筛用卡片价排序、议价前必看主页套餐全表**，否则预算估算会系统性偏低。

## 触达入口（2026-07-30 实测）

Collabstr **没有自由私信功能**（页面无 Message 入口）。下单前的沟通路径是博主主页的
**「Negotiate a Package」**按钮，平台自述："Tailor a collaboration to your needs:
propose custom terms, pricing, or requirements."——即提交自定义条款/价格/要求的提案。

因此触达顺序确定为：**Negotiate a Package 提案 →（对方接受/回价）→ Add to Cart 下单**。
不要直接 Add to Cart，那等于按刊例价全额承诺付款。
主页同时可见 `Decline` / `Accept` 按钮，说明协商是双向可否决的正式流程，不是聊天。

套餐是**按形式分行明码标价**的（如 2 Instagram Stories / 1 Instagram Photo Feed Post /
1 Instagram Reel(45s) / UGC 档若干），所以报价阶段不需要问价，只需确认档期 +
授权范围 + 该价是否仍有效。

## 与 IG 核验的衔接

Collabstr 卡片 bio 粗筛（秒级、零访问成本）→ 北美 + 粉丝段 + 垂类命中者进
`playbooks/instagram.md` 核验流程。粗筛淘汰理由记轮次总结（可复议），不静默丢弃。
