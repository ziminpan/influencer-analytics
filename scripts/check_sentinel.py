#!/usr/bin/env python3
"""哨兵断言校验：把 tests/sentinels.yaml 里的断言真正跑起来。

在此之前四段哨兵（sentinels / pgy_sentinels / ig_sentinels / x_sentinels）只有人肉
比对，"出问题先跑哨兵"这一步没有可执行的一端。本脚本补的就是校验这一端。

**本脚本不抓网页。** 抓取由带浏览器的那一端做（按 playbook 的登录态检查与 pacing
纪律），把采到的字段整理成一个 dict 交给这里；这里只做纯校验。两端分开的原因：
校验逻辑要能离线重跑、能进 CI、能在不消耗任何风控预算的情况下测试自己。

用法:
    python check_sentinel.py X --result '{"followers": 18800, "bio": "...", "posts": 3}'
    python check_sentinel.py 蒲公英 --result-file collected.json --json
    python check_sentinel.py --self-test          # 用 yaml 里的 baseline 自测

退出码 0 = 全部断言通过；1 = 有 fail/missing/unknown（可直接用于自动化守门）。
"""
import sys, os, json, re, argparse, statistics

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml --break-system-packages")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SENTINELS = os.path.join(ROOT, "tests", "sentinels.yaml")

# 采集端字段名不统一（中文列名/平台叫法各异），这里做别名归一
FIELD_ALIASES = {
    "followers": ["followers", "fans", "follower_count", "粉丝数"],
    "fans": ["fans", "followers", "follower_count", "粉丝数"],
    "quote_image": ["quote_image", "图文笔记一口价"],
    "quote_video": ["quote_video", "视频笔记一口价"],
    "reads_median": ["reads_median", "阅读中位数"],
    "recent_posts": ["recent_posts", "posts", "posts_count", "recent_post_count"],
    "notes_visible": ["notes_visible", "notes_count", "notes", "posts"],
    "bio": ["bio", "biography", "简介"],
    "median": ["median_engagement", "median", "互动中位数"],
    "detail_url": ["detail_url", "url", "profile_url"],
}

# 桶值：登出态/改版后平台把精确数字换成量级显示（"18.8K"、"1千+"、"0.0k"）。
# 这类值绝不能进库——这是真实发生过两次的事故，也是哨兵存在的首要理由。
BUCKET_PATTERNS = [
    re.compile(r"^\s*\d+(?:\.\d+)?\s*(?:[kKmMbBwW]|万|千|亿)\s*\+?\s*$"),
    re.compile(r"^\s*\d+(?:\.\d+)?\s*\+\s*$"),
]


def looks_like_bucket(v):
    return isinstance(v, str) and any(p.match(v) for p in BUCKET_PATTERNS)


def as_number(v):
    """纯数字才返回数值；桶值与其他字符串返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str) and not looks_like_bucket(v):
        try:
            return float(v.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def lookup(result, field):
    """按别名找字段。返回 (命中的键, 值)；没提供则 (None, None)。"""
    for key in FIELD_ALIASES.get(field, [field]):
        if key in result:
            return key, result[key]
    return None, None


def _r(name, status, expected, actual, note=""):
    return {"assert": name, "status": status, "expected": expected,
            "actual": actual, "note": note}


# ---- 断言实现：每个返回一条结果记录 ----

def _check_numeric(name, field, _exp, result):
    key, v = lookup(result, field)
    if key is None:
        return _r(name, "MISSING", "纯数字", None, f"采集端未提供 {field}")
    n = as_number(v)
    if n is None:
        hint = "桶值（登出态或平台改版？）" if looks_like_bucket(v) else "非数字"
        return _r(name, "FAIL", "纯数字（非桶值）", v, hint)
    return _r(name, "PASS", "纯数字", n)


def _check_range(name, field, exp, result):
    if not (isinstance(exp, (list, tuple)) and len(exp) == 2):
        return _r(name, "UNKNOWN", exp, None, "range 断言需要 [lo, hi] 两个值")
    lo, hi = exp
    key, v = lookup(result, field)
    if key is None:
        return _r(name, "MISSING", f"[{lo}, {hi}]", None, f"采集端未提供 {field}")
    n = as_number(v)
    if n is None:
        return _r(name, "FAIL", f"[{lo}, {hi}]", v, "取不到纯数字，无法判断区间")
    if not (lo <= n <= hi):
        return _r(name, "FAIL", f"[{lo}, {hi}]", n, "超出结构性区间")
    return _r(name, "PASS", f"[{lo}, {hi}]", n)


def _check_min(name, field, exp, result):
    key, v = lookup(result, field)
    if key is None:
        return _r(name, "MISSING", f">= {exp}", None, f"采集端未提供 {field}")
    n = as_number(v)
    if n is None:
        return _r(name, "FAIL", f">= {exp}", v, "取不到纯数字")
    return _r(name, "PASS" if n >= exp else "FAIL", f">= {exp}", n)


def _check_max(name, field, exp, result):
    key, v = lookup(result, field)
    if key is None:
        return _r(name, "MISSING", f"<= {exp}", None, f"采集端未提供 {field}")
    n = as_number(v)
    if n is None:
        return _r(name, "FAIL", f"<= {exp}", v, "取不到纯数字")
    return _r(name, "PASS" if n <= exp else "FAIL", f"<= {exp}", n)


def _check_non_empty(name, field, _exp, result):
    key, v = lookup(result, field)
    if key is None:
        return _r(name, "MISSING", "非空", None, f"采集端未提供 {field}")
    if v is None or str(v).strip() == "":
        return _r(name, "FAIL", "非空", repr(v), "字段存在但为空")
    return _r(name, "PASS", "非空", (str(v)[:40] + "…") if len(str(v)) > 40 else v)


def _check_no_bucket_values(name, exp, result):
    if exp is False:
        return _r(name, "PASS", "不检查", None, "断言值为 false，跳过")
    bad = {k: v for k, v in result.items() if looks_like_bucket(v)}
    if bad:
        return _r(name, "FAIL", "所有字段均非桶值", bad, "桶值不得入库")
    return _r(name, "PASS", "所有字段均非桶值", f"已扫描 {len(result)} 个字段")


def _check_median_recomputable(name, exp, result):
    if exp is False:
        return _r(name, "PASS", "不检查", None, "断言值为 false，跳过")
    _, samples = lookup(result, "raw_samples")
    mkey, claimed = lookup(result, "median")
    if samples is None:
        return _r(name, "MISSING", "raw_samples + 中位数", None,
                  "采集端未提供 raw_samples，中位数无法复算")
    if isinstance(samples, str):
        parts = [p for p in re.split(r"[;,；]", samples) if p.strip()]
    else:
        parts = list(samples)
    nums = [as_number(p) for p in parts]
    if not nums or any(n is None for n in nums):
        return _r(name, "FAIL", "raw_samples 全为数字", samples, "样本含非数字")
    recomputed = statistics.median(nums)
    if mkey is None:
        return _r(name, "MISSING", f"中位数 == {recomputed:g}", None,
                  "采集端未提供中位数字段，无法对账")
    c = as_number(claimed)
    if c is None:
        return _r(name, "FAIL", f"中位数 == {recomputed:g}", claimed, "中位数非数字")
    if abs(c - recomputed) > max(1e-6, abs(recomputed) * 0.01):
        return _r(name, "FAIL", f"可从 raw_samples 复算得 {recomputed:g}", c,
                  "中位数与样本不符（防编数审计）")
    return _r(name, "PASS", f"复算 {recomputed:g}", c)


def _check_fields_present(name, exp, result):
    if not isinstance(exp, (list, tuple)):
        return _r(name, "UNKNOWN", exp, None, "fields_present 需要字段名列表")
    missing = [f for f in exp
               if lookup(result, f)[0] is None
               or str(lookup(result, f)[1]).strip() == ""]
    if missing:
        return _r(name, "FAIL", f"{len(exp)} 个字段齐全", f"缺 {missing}",
                  "页面字段缺失＝改版信号")
    return _r(name, "PASS", f"{len(exp)} 个字段齐全", "全部命中")


def _check_url_pattern(name, exp, result):
    key, v = lookup(result, "detail_url")
    if key is None:
        return _r(name, "MISSING", exp, None, "采集端未提供 detail_url")
    # yaml 里写的是 'blogger-detail/<24hex>' 这类占位式模式，转成正则
    rx = re.escape(str(exp))
    rx = rx.replace(re.escape("<24hex>"), r"[0-9a-fA-F]{24}")
    rx = re.sub(r"\\<\w+\\>", r"[^/]+", rx)
    if not re.search(rx, str(v)):
        return _r(name, "FAIL", exp, v, "URL 结构不符（改版信号）")
    return _r(name, "PASS", exp, v)


def _check_flag(name, exp, result):
    """能力型布尔断言：采集端必须显式回报同名布尔值。"""
    if name not in result:
        return _r(name, "MISSING", exp, None,
                  f"采集端未回报 {name}（这项只有抓取的一端能判定）")
    v = result[name]
    if not isinstance(v, bool):
        return _r(name, "FAIL", exp, v, "该断言要求布尔值")
    return _r(name, "PASS" if v == exp else "FAIL", exp, v)


EXACT = {
    "no_bucket_values": _check_no_bucket_values,
    "median_recomputable": _check_median_recomputable,
    "fields_present": _check_fields_present,
    "detail_url_pattern": _check_url_pattern,
}
# 长后缀优先：followers_range 要走 _range 而不是被别的截到
SUFFIX = [("_non_empty", _check_non_empty), ("_numeric", _check_numeric),
          ("_range", _check_range), ("_min", _check_min), ("_max", _check_max)]


def evaluate(asserts, result):
    out = []
    for name, exp in (asserts or {}).items():
        if name in EXACT:
            out.append(EXACT[name](name, exp, result))
            continue
        if name == "min_notes_visible":          # 前缀式命名，单独接
            out.append(_check_min(name, "notes_visible", exp, result))
            continue
        for suf, fn in SUFFIX:
            if name.endswith(suf):
                out.append(fn(name, name[: -len(suf)], exp, result))
                break
        else:
            if isinstance(exp, bool):
                out.append(_check_flag(name, exp, result))
            else:
                # 静默跳过等于假绿：不认识的断言必须显式报出来
                out.append(_r(name, "UNKNOWN", exp, None,
                              "unknown assert：本脚本不认识这个断言类型，"
                              "请在 check_sentinel.py 里补实现或改 yaml 用已支持的类型"))
    return out


def load_sentinels(path):
    if not os.path.exists(path):
        # 模板版只带 sentinels.example.yaml（真实哨兵属公司数据不导出）。
        # 这时给一句能照着做的话，而不是抛 FileNotFoundError traceback。
        example = os.path.join(os.path.dirname(path), "sentinels.example.yaml")
        if os.path.exists(example):
            sys.exit(f"找不到 {path}。\n"
                     f"这是模板版的正常状态：真实哨兵含账号信息，不进公开仓库。\n"
                     f"请先 cp {example} {path} 并填入你自己的标杆账号"
                     f"（每平台 1 主 1 备），再跑本脚本。")
        sys.exit(f"找不到哨兵配置 {path}（也没有同目录的 sentinels.example.yaml）")
    doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
    found = []
    for section, entries in doc.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and "platform" in e:
                found.append({"section": section, **e})
    return found


def pick(sentinels, platform, role=None, name=None):
    out = [s for s in sentinels
           if str(s.get("platform", "")).lower() == str(platform).lower()]
    if role:
        want = None if role == "primary" else role
        out = [s for s in out if s.get("role") == want] if want \
            else [s for s in out if not s.get("role")]
    if name:
        out = [s for s in out if s.get("name") == name]
    return out


def check(sentinel, result):
    rows = evaluate(sentinel.get("asserts"), result)
    tally = {k: sum(1 for r in rows if r["status"] == k)
             for k in ("PASS", "FAIL", "MISSING", "UNKNOWN")}
    return {
        "sentinel": sentinel.get("name"),
        "platform": sentinel.get("platform"),
        "role": sentinel.get("role", "primary"),
        "section": sentinel.get("section"),
        "passed": tally["FAIL"] == 0 and tally["MISSING"] == 0 and tally["UNKNOWN"] == 0,
        "tally": tally,
        "checks": rows,
    }


# ---- 自测：用 yaml 自己的 baseline 合成一份"应当全通过"的采集结果 ----

def synth_result(sentinel):
    """从 baseline / 断言反推一份合法采集结果。缺 baseline 的用区间中点等价值。"""
    res = {}
    base = sentinel.get("baseline") or {}
    for k, v in base.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            res[k] = v
    asserts = sentinel.get("asserts") or {}
    for name, exp in asserts.items():
        if name in ("no_bucket_values",):
            continue
        if name == "median_recomputable" and exp:
            res.setdefault("raw_samples", "10;20;30")
            res["median_engagement"] = 20
            continue
        if name == "fields_present" and isinstance(exp, list):
            for f in exp:
                res.setdefault(f, "已采到")
            continue
        if name == "detail_url_pattern":
            res.setdefault("detail_url",
                           str(exp).replace("<24hex>", "a" * 24))
            continue
        if name == "min_notes_visible":
            res.setdefault("notes_visible", exp)
            continue
        for suf in ("_non_empty", "_numeric", "_range", "_min", "_max"):
            if name.endswith(suf):
                field = name[: -len(suf)]
                target = FIELD_ALIASES.get(field, [field])[0]
                if suf == "_non_empty":
                    res.setdefault(target, "非空占位")
                elif suf == "_range" and isinstance(exp, (list, tuple)):
                    # 不能只在缺值时填：断言的遍历顺序不定，_numeric 可能先塞了个
                    # 占位 1 进去，那样这里就跳过了、区间断言反而自测不过。
                    cur = as_number(res.get(target))
                    if cur is None or not (exp[0] <= cur <= exp[1]):
                        res[target] = (exp[0] + exp[1]) / 2
                elif suf == "_min":
                    if as_number(res.get(target)) is None or \
                            as_number(res.get(target)) < exp:
                        res[target] = exp
                elif suf == "_max":
                    if as_number(res.get(target)) is None or \
                            as_number(res.get(target)) > exp:
                        res[target] = exp
                elif suf == "_numeric":
                    res.setdefault(target, 1)
                break
        else:
            if isinstance(exp, bool):
                res[name] = exp
    return res


def render(reports, as_json=False):
    if as_json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return
    icon = {"PASS": "✓", "FAIL": "✗", "MISSING": "?", "UNKNOWN": "!"}
    for rep in reports:
        head = "PASS" if rep["passed"] else "FAIL"
        print(f"\n[{head}] {rep['platform']} / {rep['sentinel']} "
              f"({rep['role']} · {rep['section']})")
        for c in rep["checks"]:
            line = (f"  {icon[c['status']]} {c['assert']:<28} "
                    f"期望 {str(c['expected']):<24} 实际 {c['actual']}")
            print(line.rstrip())
            if c["note"]:
                print(f"      └─ {c['note']}")
        t = rep["tally"]
        print(f"  小结：{t['PASS']} pass / {t['FAIL']} fail / "
              f"{t['MISSING']} missing / {t['UNKNOWN']} unknown")


def main():
    ap = argparse.ArgumentParser(description="哨兵断言校验（纯校验，不抓取）")
    ap.add_argument("platform", nargs="?", help="平台名，如 X / Instagram / 蒲公英 / 小红书")
    ap.add_argument("--result", help="采集结果 JSON 字符串")
    ap.add_argument("--result-file", help="采集结果 JSON 文件")
    ap.add_argument("--role", choices=["primary", "backup"], help="只校验主/备哨兵")
    ap.add_argument("--name", help="只校验指定名字的哨兵")
    ap.add_argument("--sentinels", default=DEFAULT_SENTINELS)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--self-test", action="store_true",
                    help="用 yaml 的 baseline 合成结果自测，应当全 pass")
    a = ap.parse_args()

    sentinels = load_sentinels(a.sentinels)
    if not sentinels:
        sys.exit(f"没从 {a.sentinels} 读到任何哨兵")

    if a.self_test:
        reports = [check(s, synth_result(s)) for s in sentinels]
        render(reports, a.as_json)
        bad = [r for r in reports if not r["passed"]]
        print(f"\n自测：{len(reports) - len(bad)}/{len(reports)} 枚哨兵的 baseline 全通过")
        return 1 if bad else 0

    if not a.platform:
        sys.exit("需要平台名（或用 --self-test）。可用平台："
                 + ", ".join(sorted({str(s['platform']) for s in sentinels})))
    if a.result:
        result = json.loads(a.result)
    elif a.result_file:
        result = json.load(open(a.result_file, encoding="utf-8"))
    else:
        sys.exit("需要 --result 或 --result-file（本脚本不抓取，采集由浏览器那一端做）")

    matched = pick(sentinels, a.platform, a.role, a.name)
    if not matched:
        sys.exit(f"没有匹配 platform={a.platform} 的哨兵。可用："
                 + ", ".join(sorted({str(s['platform']) for s in sentinels})))
    reports = [check(s, result) for s in matched]
    render(reports, a.as_json)
    return 0 if all(r["passed"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
