# Playbook · 抖音

> changelog
> - 2026-07-15 初版，基于当前 douyin.com Web 结构

## 登录态检查

抖音首页 `https://www.douyin.com` 登出态也能看视频，但**搜索(尤其 type=user)会拦截**
弹登录框。用户搜索前先确认已登录（App 扫一扫）。注意：抖音 Web session 不太稳，
中途可能掉登录，掉了重扫即可，已采数据不受影响（每人即时落盘）。

## 发现

- 用户搜索：`https://www.douyin.com/search/<词>?type=user`——直接看到粉丝/获赞，最省事。
- 视频搜索：`.../search/<词>?type=video`——从爆款视频找作者，再回到用户页取粉丝数。

提取（用户搜索结果页）：

```js
const out=[];
document.querySelectorAll('a[href*="/user/"]').forEach(a=>{
  const u=(a.href.match(/user\/([\w-]+)/)||[])[1]||'';
  const card=a.closest('li,div[class*="item"],div[class*="card"]')||a;
  const t=(card.innerText||'').replace(/\s+/g,' ').trim();
  if(u&&u!=='self')out.push({u,t:t.slice(0,80)});
});
JSON.stringify(out.slice(0,10));   // t 内含"抖音号/获赞/粉丝/简介"
```

## 采集单个主页

`https://www.douyin.com/user/<sec_uid>`，等待 8-9 秒（抖音渲染慢，可能要二次 wait）：

```js
const bt=document.body.innerText.replace(/\s+/g,' ');
const head=bt.match(/关注 (\d[\d.]*万?) 粉丝 (\d[\d.]*万?) 获赞/);  // 粉丝、获赞
const vids=[...document.querySelectorAll('a[href*="/video/"]')].slice(0,14).map(a=>{
  const li=a.closest('li')||a;
  return {t:((li.querySelector('img')?.alt)||'').slice(0,30),
          n:(li.innerText||'').replace(/\s+/g,' ').trim().slice(0,12)};  // n 前缀是点赞数
});
JSON.stringify({head:head?head.slice(1,3):null, vids});
```

- **中位口径 = 播放量**。抖音主页作品墙只显示点赞不显示播放：
  - 有后台截图 → 直接用真实中位播放，engagement_basis=`plays`。
  - 只有公开数据 → 非置顶点赞中位 × `douyin_play_per_like`(默认26.5) 反推，
    engagement_basis=`plays_inferred`，拿到截图后替换。
- **置顶剔除**：主页前几条常是置顶爆款（"置顶"字样在 n 里），算中位时排除。
- 视频 id 同样嵌时间戳（字节 snowflake，高位段为毫秒）；近30天活跃度也可从
  "作品 N"和最新几条日期估。decode 逻辑与小红书不同，需要时在此补充实现。

## 已知坑

- 星图个人达人接单门槛约 1 万粉——1 万以下抖音号多数只能私下合作，
  报备类预算优先给小红书侧。
- 部分账号私信关闭（简介写"资料见其他平台"）→ contact 标注、走评论区或全网同名号。
- 主页 innerText 有时首取为空（渲染未完）→ 再 wait 6-7 秒重取。
