# Playbook · 小红书

> changelog
> - 2026-07-15 初版，基于当前 xiaohongshu.com Web 结构

## 登录态检查（每轮第一件事）

打开 `https://www.xiaohongshu.com/explore`。页面顶部出现搜索框与「我」= 已登录。
若跳到 `/login` 或出现二维码/「登录后查看」= 未登录：**停下，请用户用小红书 App 扫码**，
不要在登出态采集——登出态主页粉丝数只显示模糊桶值（"1千+""1万+"），会污染库。

## 发现（搜索）

逐个预设关键词打开：
`https://www.xiaohongshu.com/search_result?keyword=<URL编码词>&source=web_explore_feed`
提取结果作者与主页 ID：

```js
const seen=new Map();
document.querySelectorAll('a[href*="/user/profile/"]').forEach(a=>{
  const name=(a.innerText||'').trim().split('\n')[0];
  const id=a.href.match(/profile\/([0-9a-f]+)/)?.[1];
  if(name&&id&&name!=='我'&&!seen.has(name))seen.set(name,id);
});
[...seen.entries()].map(([n,id])=>n+'|'+id).join('\n');
```

## 采集单个主页

`https://www.xiaohongshu.com/user/profile/<id>`，等待 7 秒后取：

```js
const g=s=>document.querySelector(s)?.innerText?.trim()||'';
const stats=[...document.querySelectorAll('.user-interactions > div')].map(d=>d.innerText.replace(/\s+/g,' ').trim());
// 优先从 __INITIAL_STATE__ 拿结构化笔记（含 noteId、真实点赞、是否置顶）
let notes=[];
try{
  const arr=window.__INITIAL_STATE__.user.notes;
  const flat=Array.isArray((arr._value||arr)[0])?(arr._value||arr)[0]:(arr._value||arr);
  notes=flat.slice(0,12).map(n=>{const c=n.noteCard||n;return{
    id:n.id||c.noteId, tk:(n.xsecToken||c.xsecToken||''),
    like:c.interactInfo?.likedCount, sticky:!!c.interactInfo?.sticky,
    t:(c.displayTitle||'').slice(0,30)};});
}catch(e){
  notes=[...document.querySelectorAll('section.note-item')].slice(0,12).map(s=>({
    t:(s.querySelector('.title')?.innerText||'').slice(0,30),
    like:(s.querySelector('.count')?.innerText||'').trim(),
    sticky:/置顶/.test(s.innerText)}));
}
JSON.stringify({name:g('.user-name'),desc:g('.user-desc').slice(0,80),stats,notes});
```

- `stats` 里「粉丝」项就是粉丝数——**转成绝对数存**（"1.3万"→13000）。
  登出态出现"1千+"这类桶值：拒绝入库，标 data_confidence=low。
- **中位口径 = 赞+藏**。列表页只给赞；藏数要点进 1-2 篇同类笔记补：
  打开 `https://www.xiaohongshu.com/explore/<noteId>?xsec_token=<tk>&xsec_source=pc_user`，
  取 `.collect-wrapper .count`。算出该账号「藏赞比」后套用到中位赞上（存 raw_samples）。
- 近30天条数：把 note id 列表喂给 `scripts/decode_note_time.py --count-30d`。

## 已知坑

- 连续快速开多个主页 → "请求太频繁" → 稍后升级为扫码验证。**务必遵守 pacing**，
  每主页间隔 ≥45s；一旦出验证码当日停采。
- `__INITIAL_STATE__` 偶发 `[BLOCKED: Cookie/query string data]`——重取一次或退回 DOM 选择器。
- 搜索页在登出态只显示登录框——回到登录态检查。
- 「编辑于 X」笔记的 noteId 仍是**首发**时间戳，符合"近30天是否活跃"的判断意图。
