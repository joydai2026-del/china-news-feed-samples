"""Offline tests for the stricter Deleted-today cut. Synthetic flags only; no network, no live files."""
import json, os, sqlite3, subprocess, sys
from datetime import datetime, timedelta, timezone

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, TOOLS)
import build_deleted_today as b  # noqa: E402

GEN = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)


def z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def flag(title, lst="baidu", trail=(2, 2, 2), on=60, gone_min_ago=120, status="likely_censored",
         signals=("abrupt_drop_while_hot", "live"), survived=(), tier="medium"):
    gone = GEN - timedelta(minutes=gone_min_ago)
    first = gone - timedelta(minutes=on + 5)
    return {
        "list": lst, "title": title, "status": status, "tier": tier, "peak_rank": min(trail),
        "rank_trail": list(trail), "time_on_list": {"minutes": on, "snapshots": 6},
        "first_seen_at": z(first), "last_seen_at": z(gone - timedelta(minutes=5)),
        "censored_at": {"first_missing": z(gone)}, "url": "https://example.invalid/s?wd=x",
        "evidence": [{"check": "rank_history", "signal": s} for s in signals],
        "survived_on": [{"where": w, "url": "https://example.invalid/"} for w in survived],
    }


def run(flags, **kw):
    fun = {}
    _, rows = b.select({"meta": {"generated_at": z(GEN)}, "flags": flags}, 24, {}, {}, funnel=fun, **kw)
    return [r["title_zh"] for r in rows], fun


def test_abrupt_top10_exit_is_kept():
    assert run([flag("某地突发事件通报")])[0] == ["某地突发事件通报"]


@pytest.mark.parametrize("kw, reason", [
    (dict(signals=("abrupt_drop_while_hot", "returned")), "came back once before"),
    (dict(gone_min_ago=30), "gone under 60 min"),
    (dict(trail=(12, 12, 12)), "not in the top 10 when it left"),
    (dict(trail=(2, 3, 9)), "slid down before leaving"),
    (dict(on=20), "on the list a normal length of time"),
    (dict(on=200), "on the list a normal length of time"),
    (dict(lst="bilibili", on=55), "inside the list's normal rotation"),
    (dict(survived=("weibo",)), "still on another hot list"),
])
def test_each_churn_rule_cuts(kw, reason):
    titles, fun = run([flag("某地突发事件通报", **kw)])
    assert titles == [] and fun[reason] == 1 and fun["kept"] == 0


def test_survival_on_a_news_site_is_not_another_hot_list():
    assert run([flag("某地突发事件通报", survived=("BBC News Chinese",))])[0] == ["某地突发事件通报"]


def test_bilibili_outside_rotation_band_is_kept():
    assert run([flag("某游戏版本更新公告", lst="bilibili", on=90)])[0] == ["某游戏版本更新公告"]


def test_batch_drop_of_unrelated_topics_is_cut():
    a, c = flag("某地突发事件通报"), flag("球队客场取胜晋级", trail=(5, 5, 5))
    titles, fun = run([a, c])
    assert titles == [] and fun["left with other flagged topics (batch drop)"] == 2


def test_batch_drop_with_a_returned_topic_is_cut():
    a = flag("法国多地骚乱持续")
    r = flag("法国骚乱最新进展", status="returned")
    assert run([a, r])[0] == []


def test_one_story_leaving_together_is_kept_once():
    a, c = flag("法国多地骚乱持续", trail=(1, 1, 1)), flag("法国骚乱致超市遭抢", trail=(4, 4, 4))
    titles, fun = run([a, c])
    assert titles == ["法国多地骚乱持续"] and fun["same story as a kept item"] == 1


def test_retitle_seen_in_flags_is_cut():
    old = flag("国家统计局：全年粮食有望再获丰收", gone_min_ago=300)
    new = flag("全年粮食有望再获丰收", on=400, gone_min_ago=100)
    new["first_seen_at"] = z(GEN - timedelta(minutes=600))  # already on the list when the long title left
    titles, fun = run([old, new])
    assert "国家统计局：全年粮食有望再获丰收" not in titles and fun["retitled"] >= 1


def test_same_event_on_two_lists_is_deduped():
    a = flag("绵阳地震", trail=(1, 1, 1))
    c = flag("四川北川县发生4级地震", lst="toutiao", trail=(2, 2, 2))
    c["censored_at"]["first_missing"] = z(GEN - timedelta(minutes=115))
    titles, _ = run([a, c])
    assert titles == ["绵阳地震"]


def test_all_flags_keeps_old_behavior():
    titles, _ = run([flag("某地突发事件通报", on=20), flag("另一个话题", trail=(30, 30))], strict=False)
    assert sorted(titles) == sorted(["某地突发事件通报", "另一个话题"])


def _history(path, rows):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE snapshots(id INTEGER PRIMARY KEY, list TEXT, ts INTEGER, ok INTEGER, n INTEGER, via TEXT, error TEXT)")
    c.execute("CREATE TABLE hot_items(snapshot_id INTEGER, list TEXT, ts INTEGER, rank INTEGER, title TEXT, heat REAL, url TEXT, label TEXT, key TEXT, via TEXT)")
    for i, (lst, ts, rank, title) in enumerate(rows, 1):
        c.execute("INSERT INTO snapshots VALUES (?,?,?,1,50,NULL,NULL)", (i, lst, ts))
        c.execute("INSERT INTO hot_items VALUES (?,?,?,?,?,0,'','','',NULL)", (i, lst, ts, rank, title))
    c.commit(); c.close()


def test_history_retitle_and_topic_checks(tmp_path):
    f1, f2, f3 = flag("帅气小伙倒追女孩半年成功求婚"), flag("马克龙谈法国街头冲突"), flag("某地突发事件通报")
    gone = int((GEN - timedelta(minutes=120)).timestamp())
    db = tmp_path / "history.sqlite"
    _history(db, [("baidu", gone + 300, 2, "帅气小伙追女孩半年成功求婚"),
                  ("baidu", gone + 600, 6, "马克龙谴责法国暴力事件"),
                  ("baidu", gone + 7200, 2, "某地突发事件后续")])  # outside the 60 min window
    h = b.open_history(str(db))
    assert h is not None
    t1, fun = run([f1], history=h)
    t2, fun2 = run([f2], history=h)
    t3, _ = run([f3], history=h)
    assert t1 == [] and fun["retitled"] == 1
    assert t2 == [] and fun2["topic still on the list"] == 1
    assert t3 == ["某地突发事件通报"]
    assert run([f1])[0] == ["帅气小伙倒追女孩半年成功求婚"]  # without history the edited headline is not seen


def test_history_is_read_only_and_bad_history_falls_back(tmp_path, capsys):
    db = tmp_path / "history.sqlite"
    _history(db, [("baidu", 1, 1, "x")])
    h = b.open_history(str(db))
    with pytest.raises(sqlite3.OperationalError):
        h.execute("INSERT INTO snapshots VALUES (99,'baidu',1,1,1,NULL,NULL)")
    assert b.open_history(str(tmp_path / "missing.sqlite")) is None
    assert "warning" in capsys.readouterr().err


def test_cli_writes_funnel_and_labels(tmp_path):
    src = tmp_path / "censored.json"
    src.write_text(json.dumps({"meta": {"generated_at": z(GEN)},
                               "flags": [flag("某地突发事件通报"), flag("长期在榜话题", on=500, gone_min_ago=200)]}, ensure_ascii=False))
    out = tmp_path / "docs"
    subprocess.run([sys.executable, os.path.join(TOOLS, "build_deleted_today.py"), str(src), str(out)],
                   check=True, capture_output=True, text=True)
    d = json.loads((out / "deleted-today.json").read_text())
    assert d["count"] == 1 and d["cut"]["flagged"] == 2 and d["cut"]["kept"] == 1
    assert all(i["label"] == "Likely censored" for i in d["items"])
    page = (out / "index.html").read_text()
    assert "某地突发事件通报" in page and "长期在榜话题" not in page and ">Censored<" not in page
