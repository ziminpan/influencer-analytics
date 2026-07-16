#!/usr/bin/env python3
"""从内容 ID 解码发布时间，用于自动统计近30天更新条数（免逐篇点开，零额外访问）。

小红书 noteId、抖音/TikTok video id 的高位段均嵌入 unix 时间戳。
本脚本对小红书 noteId（前 8 位十六进制 = unix 秒）做解码，抖音见 playbook 说明。

用法:
    python decode_note_time.py 6a54514a000000001100616c [69d0788a...] ...
    python decode_note_time.py --count-30d --now 2026-07-15 <id1> <id2> ...
"""
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def xhs_note_time(note_id: str):
    """小红书 noteId 前 8 hex → 发布时间（东八区）。失败返回 None。"""
    try:
        ts = int(note_id[:8], 16)
        # 合理性校验：2018-01-01 ~ 2035（防把非时间戳 ID 误解码）
        if not (1514736000 <= ts <= 2051222400):
            return None
        return datetime.fromtimestamp(ts, CST)
    except (ValueError, IndexError):
        return None


def count_within_30d(ids, now=None):
    now = now or datetime.now(CST)
    cutoff = now - timedelta(days=30)
    n = 0
    for i in ids:
        t = xhs_note_time(i)
        if t and t >= cutoff:
            n += 1
    return n


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--count-30d" in sys.argv:
        now = None
        if "--now" in sys.argv:
            now = datetime.strptime(
                sys.argv[sys.argv.index("--now") + 1], "%Y-%m-%d"
            ).replace(tzinfo=CST)
            args = [a for a in args if a != now.strftime("%Y-%m-%d")]
        print(count_within_30d(args, now))
    else:
        for i in args:
            t = xhs_note_time(i)
            print(f"{i}\t{t.strftime('%Y-%m-%d %H:%M') if t else 'UNPARSEABLE'}")
