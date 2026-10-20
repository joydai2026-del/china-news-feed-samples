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
    assert all(i["label"] == "Dropped off" and i["label_zh"] == "已下榜" for i in d["items"])  # no hard evidence
    page = (out / "index.html").read_text()
    assert "某地突发事件通报" in page and "长期在榜话题" not in page and ">Censored<" not in page


# ---- Copy: "Dropped off today 今日下榜" (Product Scope, 2026-10-19) ----
from html.parser import HTMLParser  # noqa: E402


class _Visible(HTMLParser):
    """Text a reader can see or a crawler/share card can show: body text, <title>, meta content, alt/title/aria."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        a = dict(attrs)
        if tag == "meta" and a.get("content"):
            self.parts.append(a["content"])
        for k in ("alt", "title", "aria-label", "placeholder"):
            if a.get(k):
                self.parts.append(a[k])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def visible(page):
    v = _Visible()
    v.feed(page)
    return " ".join(" ".join(v.parts).split())


def _text_of(page, pattern):
    import re
    m = re.search(pattern, page, re.S)
    assert m, pattern
    return visible(m.group(1))


def build(tmp_path, flags):
    src = tmp_path / "censored.json"
    src.write_text(json.dumps({"meta": {"generated_at": z(GEN)}, "flags": flags}, ensure_ascii=False))
    out = tmp_path / "docs"
    subprocess.run([sys.executable, os.path.join(TOOLS, "build_deleted_today.py"), str(src), str(out)],
                   check=True, capture_output=True, text=True)
    return out, (out / "index.html").read_text(), json.loads((out / "deleted-today.json").read_text())


def _cards(page):
    import re
    return re.findall(r'<article class="card".*?</article>', page, re.S)


def _label(card):
    return _text_of(card, r'<span class="lab[^"]*">(.*?)</span>')


def test_heading_and_subtitles(tmp_path):
    _, page, _ = build(tmp_path, [flag("某地突发事件通报")])
    assert _text_of(page, r"<h1>(.*?)</h1>") == "Dropped off today 今日下榜"
    assert _text_of(page, r'<p class="sub" id="sub-en">(.*?)</p>') == \
        "Topics that left a hot list abruptly and didn't return. Some may be normal rotation."
    assert _text_of(page, r'<p class="sub" id="sub-zh" lang="zh">(.*?)</p>') == "今日突然从热榜消失且未再出现的话题。部分可能属于正常轮换。"
    assert _text_of(page, r"<title>(.*?)</title>").startswith("Dropped off today · 今日下榜")


def test_evidence_label_vs_no_evidence_label(tmp_path):
    hard = flag("某地突发事件通报", trail=(1, 1, 1))
    hard["hard_evidence"] = ["url_dead"]
    high = flag("球队客场取胜晋级", lst="weibo", trail=(3, 3, 3), tier="high")  # tier high, no hard_evidence
    plain = flag("另一则热点新闻", lst="toutiao", trail=(5, 5, 5))
    empty = flag("明星演唱会门票开售", lst="zhihu", trail=(6, 6, 6))
    empty["hard_evidence"] = []
    for g, mins_ago in ((high, 130), (plain, 140), (empty, 150)):  # different snapshots: not a batch drop
        g["censored_at"]["first_missing"] = z(GEN - timedelta(minutes=mins_ago))
    _, page, d = build(tmp_path, [hard, high, plain, empty])
    by_title = {i["title_zh"]: i for i in d["items"]}
    assert set(by_title) == {"某地突发事件通报", "球队客场取胜晋级", "另一则热点新闻", "明星演唱会门票开售"}
    assert (by_title["某地突发事件通报"]["label"], by_title["某地突发事件通报"]["label_zh"]) == ("Likely censored", "疑似被删")
    for t in ("球队客场取胜晋级", "另一则热点新闻", "明星演唱会门票开售"):
        assert (by_title[t]["label"], by_title[t]["label_zh"]) == ("Dropped off", "已下榜")
    labels = {}
    for c in _cards(page):
        title = _text_of(c, r'<p class="zh">(.*?)</p>')
        labels[title] = _label(c)
        assert "Stronger evidence" not in c and "Standard evidence" not in c and "证据较强" not in c
        gone = by_title[title]["first_missing_et"]
        assert _text_of(c, r'<div class="times">(.*?)</div>') == f"Dropped off at: {gone} 下榜时间：{gone}"
    assert labels == {"某地突发事件通报": "Likely censored 疑似被删", "球队客场取胜晋级": "Dropped off 已下榜",
                      "另一则热点新闻": "Dropped off 已下榜", "明星演唱会门票开售": "Dropped off 已下榜"}
    assert "url_dead" not in visible(page) and "404/410" in visible(page)


def test_merged_card_has_evidence_if_any_member_does(tmp_path):
    a, c = flag("法国多地骚乱持续", trail=(1, 1, 1)), flag("法国骚乱致超市遭抢", trail=(4, 4, 4))
    c["hard_evidence"] = ["cdt_match"]
    _, page, d = build(tmp_path, [a, c])
    assert [i["title_zh"] for i in d["items"]] == ["法国多地骚乱持续"]
    assert d["items"][0]["label"] == "Likely censored"
    assert [_label(x) for x in _cards(page)] == ["Likely censored 疑似被删"]
    _, page2, d2 = build(tmp_path, [flag("法国多地骚乱持续", trail=(1, 1, 1)), flag("法国骚乱致超市遭抢", trail=(4, 4, 4))])
    assert d2["items"][0]["label"] == "Dropped off" and [_label(x) for x in _cards(page2)] == ["Dropped off 已下榜"]


@pytest.mark.parametrize("flags", [
    [],  # empty page
    [flag("某地突发事件通报", trail=(1, 1, 1), tier="high")],
    [flag("某地突发事件通报", trail=(1, 1, 1))],
])
def test_no_visible_deleted_text(tmp_path, flags):
    for f in flags:
        f["hard_evidence"] = ["url_dead", "censor_notice", "cdt_match", "deleted (not found)", "deleted_other"]
    _, page, _ = build(tmp_path, flags)
    text = visible(page)
    assert "deleted" not in text.lower(), [w for w in text.split() if "delet" in w.lower()]
    assert "今日被删" not in page


def test_filename_url_and_json_keys_unchanged(tmp_path):
    out, page, d = build(tmp_path, [flag("某地突发事件通报")])
    assert sorted(p.name for p in out.iterdir()) == [".nojekyll", "deleted-today.json", "index.html"]
    assert 'href="deleted-today.json"' in page
    assert set(d) == {"generated_at_et", "window_hours", "label", "note", "count", "cut", "items"}
    assert set(d["items"][0]) == {"platform", "platform_name", "title_zh", "title_en", "label", "label_zh",
                                  "evidence_strength", "peak_rank", "first_seen_et", "last_seen_et", "first_missing_et",
                                  "minutes_on_list", "url", "official_line", "official_line_zh", "evidence"}
    pub = open(os.path.join(TOOLS, "publish_deleted_today.sh")).read()
    assert "build_deleted_today.py" in pub and " docs " in pub
    assert "https://joydai2026-del.github.io/china-news-feed-samples/" in pub


def test_tier_high_without_hard_evidence_is_dropped_off_and_hard_evidence_is_likely_censored(tmp_path):
    for tier in ("high", "medium"):
        f = flag("某地突发事件通报", tier=tier)
        assert not b.has_evidence(f)
        f["hard_evidence"] = []
        assert not b.has_evidence(f)
        for code in ("url_dead", "censor_notice", "cdt_match"):
            f["hard_evidence"] = [code]
            assert b.has_evidence(f)
    _, page, d = build(tmp_path, [flag("某地突发事件通报", tier="high")])
    assert d["items"][0]["label"] == "Dropped off" and [_label(c) for c in _cards(page)] == ["Dropped off 已下榜"]
    f = flag("某地突发事件通报", tier="high")
    f["hard_evidence"] = ["censor_notice"]
    _, page, d = build(tmp_path, [f])
    assert d["items"][0]["label"] == "Likely censored" and [_label(c) for c in _cards(page)] == ["Likely censored 疑似被删"]
    # merged card: a tier-high member without hard_evidence does not make the card Likely censored
    a, c = flag("法国多地骚乱持续", trail=(1, 1, 1)), flag("法国骚乱致超市遭抢", trail=(4, 4, 4), tier="high")
    _, page, d = build(tmp_path, [a, c])
    assert [i["label"] for i in d["items"]] == ["Dropped off"]
    assert "tier" not in visible(page).lower()


def test_meta_description_and_readme_say_hourly(tmp_path):
    import re
    _, page, _ = build(tmp_path, [flag("某地突发事件通报")])
    desc = re.search(r'<meta name="description" content="([^"]*)">', page).group(1)
    assert "Updated hourly." in desc and "daily" not in desc.lower()
    assert "daily" not in visible(page).lower()
    readme = open(os.path.join(TOOLS, "..", "README.md")).read()
    assert "rebuilt hourly" in readme and "rebuilt daily" not in readme


def test_no_evidence_line_hook(tmp_path, monkeypatch):
    import re
    assert hasattr(b, "NO_EVIDENCE_LINE")
    plain = [flag("某地突发事件通报")]
    hard = flag("某地突发事件通报")
    hard["hard_evidence"] = ["url_dead"]
    gen = GEN
    def page_for(flags):
        _, rows = b.select({"meta": {"generated_at": z(gen)}, "flags": flags}, 24, {}, {})
        return b.render(gen, rows, 24)
    # empty string (current value until Product Scope sends the wording) renders nothing
    monkeypatch.setattr(b, "NO_EVIDENCE_LINE", "")
    assert 'id="no-evidence"' not in page_for(plain) and 'class="no-evidence"' not in page_for([])
    monkeypatch.setattr(b, "NO_EVIDENCE_LINE", "Test line for zero Likely censored.")
    for flags in (plain, []):
        p = page_for(flags)
        m = re.search(r'<p class="no-evidence" id="no-evidence">(.*?)</p>', p)
        assert m and m.group(1) == "Test line for zero Likely censored."
        assert p.index('id="no-evidence"') < p.index('class="note"')  # at the top of the page body
    assert 'id="no-evidence"' not in page_for([hard])  # hidden when a card is Likely censored


NO_EVIDENCE_TEXT = 'No topic met our evidence bar for "likely censored" today. The topics below dropped off abruptly, which is a signal, not proof. 今日没有话题达到"疑似被删"的证据标准。以下话题突然下榜，仅为信号，并非证据。'


def test_no_evidence_line_is_the_product_scope_string():
    assert b.NO_EVIDENCE_LINE == NO_EVIDENCE_TEXT


def test_no_evidence_line_shows_when_zero_likely_censored(tmp_path):
    import re
    _, page, d = build(tmp_path, [flag("某地突发事件通报", tier="high")])  # tier high alone is not evidence
    assert d["count"] == 1 and d["items"][0]["label"] == "Dropped off"
    m = re.search(r'<p class="no-evidence" id="no-evidence">(.*?)</p>', page, re.S)
    assert m and visible(m.group(1)) == NO_EVIDENCE_TEXT
    assert "<" not in m.group(1) and ">" not in m.group(1)  # plain, escaped text content
    assert page.index('id="no-evidence"') < page.index('<section class="grid">')  # above the cards
    (tmp_path / "e").mkdir()
    _, empty_page, _ = build(tmp_path / "e", [])
    assert 'id="no-evidence"' in empty_page


@pytest.mark.parametrize("n_hard", [1, 2])
def test_no_evidence_line_absent_when_any_likely_censored(tmp_path, n_hard):
    flags = [flag("某地突发事件通报", trail=(1, 1, 1)), flag("球队客场取胜晋级", lst="weibo", trail=(3, 3, 3)),
             flag("另一则热点新闻", lst="toutiao", trail=(5, 5, 5))]
    for g, mins_ago in zip(flags[1:], (130, 140)):
        g["censored_at"]["first_missing"] = z(GEN - timedelta(minutes=mins_ago))
    for g in flags[:n_hard]:
        g["hard_evidence"] = ["url_dead"]
    _, page, d = build(tmp_path, flags)
    assert sum(i["label"] == "Likely censored" for i in d["items"]) == n_hard
    assert 'id="no-evidence"' not in page and NO_EVIDENCE_TEXT not in visible(page)


def test_apify_footer_uses_product_scope_wording():
    page = b.render(GEN, [], 24)
    assert "The live feed on Apify, with English where available and the deletion watch, costs $8 per 1,000 rows." in page
    assert "Get today's live data" in page
    assert "155 sources" not in page
    assert "7 hot lists" not in page
