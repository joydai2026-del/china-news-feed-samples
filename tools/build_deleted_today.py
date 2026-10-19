#!/usr/bin/env python3
"""Build the "Dropped off today / 今日下榜" GitHub Pages page from the live censored.json.

Usage: build_deleted_today.py <censored.json> <out_dir> [--hours 24] [--feed-en feed_en.json]
                              [--history history.sqlite] [--all-flags]
Writes <out_dir>/index.html and <out_dir>/deleted-today.json (URL, filename and JSON keys are unchanged).
A card with evidence (a non-empty hard_evidence list; tier alone does not count) is labeled "Likely censored 疑似被删";
every other card is labeled "Dropped off 已下榜". Hot-list headlines and public links only; no user data.

Only abrupt exits are shown, not ordinary list churn (see why_cut). --history, when given, is opened
read-only and adds the retitle / topic-still-on-the-list checks. --all-flags shows every flag (old behavior).
"""
import argparse, html, json, re, sqlite3, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ACTOR = "https://apify.com/china.unofficial/china-news-feed"
HF = "https://huggingface.co/datasets/freedom-press/china-news-feed-sample"
X402 = "https://ownly-cmf-x402.joyd-ai-2026.workers.dev/"
REPO = "https://github.com/joydai2026-del/china-news-feed-samples"

PLATFORMS = {
    "weibo": "Weibo 微博", "baidu": "Baidu 百度", "zhihu": "Zhihu 知乎", "toutiao": "Toutiao 今日头条",
    "douyin": "Douyin 抖音", "bilibili": "Bilibili 哔哩哔哩", "kuaishou": "Kuaishou 快手",
}
PLATFORM_COLORS = {
    "weibo": "#e6162d", "baidu": "#2932e1", "zhihu": "#0066ff", "toutiao": "#f04142",
    "douyin": "#111111", "bilibili": "#fb7299", "kuaishou": "#ff6a00",
}
# Bilingual names for outlets / trackers whose source name has no Chinese.
OUTLET_ZH = {
    "Weibo trending history (GitHub, justjavac)": "Weibo 微博 trending history 热搜历史 (GitHub, justjavac)",
    "Weibo trending history (GitHub, bhwa233)": "Weibo 微博 trending history 热搜历史 (GitHub, bhwa233)",
    "China Digital Times English": "China Digital Times 中国数字时代 (English)",
    "China Media Project": "China Media Project 中国传媒研究计划",
    "BBC News Chinese": "BBC News Chinese BBC中文",
    "YouTube: DW Chinese": "YouTube: DW Chinese 德国之声中文",
    "YouTube: BBC News 中文": "YouTube: BBC News 中文",
}
CJK = re.compile(r"[\u3400-\u9fff]")

# Visible copy (Product Scope, 2026-10-19). The word "Deleted" must not appear in visible text.
HEADING_EN, HEADING_ZH = "Dropped off today", "今日下榜"
SUBTITLE_EN = "Topics that left a hot list abruptly and didn't return. Some may be normal rotation."
SUBTITLE_ZH = "今日突然从热榜消失且未再出现的话题。部分可能属于正常轮换。"
LABEL_EVIDENCE = ("Likely censored", "疑似被删")
LABEL_NO_EVIDENCE = ("Dropped off", "已下榜")
# One line shown above the cards when zero cards are "Likely censored" (Product Scope, 2026-10-19).
# Hidden when one or more cards are Likely censored; an empty string renders nothing.
NO_EVIDENCE_LINE = 'No topic met our evidence bar for "likely censored" today. The topics below dropped off abruptly, which is a signal, not proof. 今日没有话题达到"疑似被删"的证据标准。以下话题突然下榜，仅为信号，并非证据。'
TIME_LINE = "Dropped off at: {time} 下榜时间：{time}"
HARD_EVIDENCE_TEXT = {
    "url_dead": "the topic link returns 404/410 链接已失效",
    "censor_notice": "the platform shows a removal notice 平台显示屏蔽提示",
    "cdt_match": "a censorship tracker has a dated entry 审查追踪记录有对应条目",
    "deleted (not found)": "the platform reports it removed 平台显示已移除",
}


def has_evidence(f):
    """A flag has evidence only when it carries a non-empty hard_evidence list (404/410, a removal notice, or a
    tracker entry). tier == "high" on its own does not count."""
    he = f.get("hard_evidence")
    return bool(isinstance(he, (list, tuple)) and len(he) > 0)


def card_label(evidence):
    return LABEL_EVIDENCE if evidence else LABEL_NO_EVIDENCE


def hard_evidence_text(code):
    t = HARD_EVIDENCE_TEXT.get(code)
    if t:
        return t
    return "other hard evidence 其他确凿证据" if re.search(r"delet", str(code), re.I) else str(code)
# Drop anything that looks like personal data (phone, ID card, email, @handle).
PII = re.compile(r"(\b1[3-9]\d{9}\b|\b\d{17}[\dXx]\b|[\w.+-]+@[\w-]+\.[\w.]+|@\w{3,})")


def bilingual(name):
    if not name:
        return ""
    if name in PLATFORMS:
        return PLATFORMS[name]
    if name in OUTLET_ZH:
        return OUTLET_ZH[name]
    if not CJK.search(name):
        print(f"warning: no Chinese name for outlet {name!r}", file=sys.stderr)
    return name


def parse_z(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def et(dt, fmt="%b %-d, %-I:%M %p ET"):
    return dt.astimezone(ET).strftime(fmt) if dt else "?"


def mins(m):
    if m is None:
        return "?"
    h, r = divmod(int(m), 60)
    return f"{h} h {r} min" if h else f"{r} min"


def evidence_lines(f):
    out = []
    he = f.get("hard_evidence")
    if isinstance(he, (list, tuple)) and he:
        out.append("Hard evidence 确凿证据: " + "; ".join(hard_evidence_text(c) for c in he))
    trail = f.get("rank_trail") or []
    out.append(f"Dropped off while hot 热度高时突然消失: peak #{f.get('peak_rank')}"
               + (f", last ranks {' → '.join('#'+str(r) for r in trail[-6:])}" if trail else ""))
    for e in f.get("evidence") or []:
        c, s, ts = e.get("check"), e.get("signal"), parse_z(e.get("ts")) if "T" in str(e.get("ts")) else None
        if c and c.startswith("url_recheck"):
            when = c.split("_")[-1].replace("m", " min").replace("h", " h")
            if s == "live":
                out.append(f"Re-check after {when} 复查: still gone from the list; search link still loads ({e.get('result')}) at {et(ts)}")
            elif s == "inconclusive":
                out.append(f"Re-check after {when} 复查: still gone from the list; link check inconclusive at {et(ts)}")
    seen = set()
    for h in f.get("cdt_hits") or []:
        src = bilingual(h.get("source"))
        key = (src, h.get("url"))
        if key in seen:
            continue
        seen.add(key)
        out.append(("Matching entry on a censorship tracker / archive 审查追踪记录", src, h.get("url"), h.get("published")))
    for s in f.get("survived_on") or []:
        w = s.get("where")
        if w in PLATFORMS:
            out.append(("Still on another hot list 仍在其他热榜", PLATFORMS[w], s.get("url"), None))
        elif not any(isinstance(o, tuple) and o[2] == s.get("url") for o in out):
            out.append(("Still covered elsewhere 其他来源仍有报道", bilingual(w), s.get("url"), None))
    return out


def load_en(path):
    if not path:
        return {}, {}
    try:
        items = json.load(open(path)).get("items", [])
    except Exception:
        return {}, {}
    by_id = {i.get("id"): i.get("headline_en") for i in items if i.get("headline_en")}
    by_t = {i.get("headline_original"): i.get("headline_en") for i in items if i.get("headline_en")}
    return by_id, by_t


# ---- Stricter cut: keep abrupt removals, drop ordinary churn (audit of 2026-10-19) ----
MIN_GONE_MIN = 60        # still gone an hour after it left
MAX_DROP_RANK = 10       # was in the top 10 when it left
SLIDE_RANKS = 3          # left within 3 ranks of its best recent rank (not sliding down)
MIN_ON_MIN = 30          # was on the list at least 30 min (not a flash entry)
# Median minutes a top-10 topic stays on each list (history, 3 days to 2026-10-19). "Left early" = under half.
MEDIAN_TOP10_MIN = {"baidu": 333, "toutiao": 271, "bilibili": 204, "zhihu": 642, "weibo": 195}
# Bilibili rotates its hot search about hourly: 40 of 209 top-10 topics lived 45-75 min.
ROTATION_BAND_MIN = {"bilibili": (45, 75)}
RETITLE_WINDOW_MIN = 20  # a near-identical headline appeared on the same list within 20 min
TOPIC_WINDOW_MIN = 60    # history check window after the drop
TOPIC_MAX_RANK = 30
STOP_BIGRAMS = {"什么", "为什", "怎么", "如何", "发生", "已经", "还要", "还得", "一个", "中国", "今年", "全年", "有望",
                "回应", "宣布", "官方", "网友", "最新", "多少", "是否", "可以", "不是", "没有", "这样", "我们", "你们"}
CJK2 = re.compile(r"^[\u3400-\u9fff]{2}$")


def bigrams(t):
    t = "".join(ch for ch in (t or "") if not ch.isspace())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def topic_terms(t):
    return {b for b in bigrams(t) if CJK2.match(b)} - STOP_BIGRAMS


def is_retitle(a, b):
    """Same headline, edited: one contains the other, or 60% of the shorter one's bigrams are shared."""
    if not a or not b or a == b:
        return False
    if a in b or b in a:
        return True
    x, y = bigrams(a), bigrams(b)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= 0.6


def same_event(a, b):
    """Two kept items that are one story: 2+ shared topic bigrams, or 1 shared and gone within 30 min of each other."""
    shared = topic_terms(a["title"]) & topic_terms(b["title"])
    near = abs((a["_gone"] - b["_gone"]).total_seconds()) <= 30 * 60
    return len(shared) >= 2 or (len(shared) >= 1 and near)


def _minutes(a, b):
    return (a - b).total_seconds() / 60 if a and b else None


def open_history(path):
    """Open history.sqlite read-only. Returns None (and the cut runs without history checks) on any error."""
    if not path:
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.execute("select 1 from snapshots limit 1")
        return conn
    except sqlite3.Error as exc:
        print(f"warning: history not usable ({exc}); skipping retitle/topic checks", file=sys.stderr)
        return None


def history_titles(conn, lst, start, minutes):
    t0 = int(start.timestamp())
    q = ("select h.title from hot_items h join snapshots s on s.id = h.snapshot_id "
         "where s.list = ? and s.ok = 1 and s.ts >= ? and s.ts <= ? and h.rank <= ?")
    return {t for (t,) in conn.execute(q, (lst, t0, t0 + minutes * 60, TOPIC_MAX_RANK))}


CUT_ORDER = ["came back once before", "gone under 60 min", "not in the top 10 when it left",
             "slid down before leaving", "on the list a normal length of time", "inside the list's normal rotation",
             "still on another hot list", "left with other flagged topics (batch drop)", "retitled",
             "topic still on the list", "same story as a kept item"]


def why_cut(f, gone, gen, flags, history=None):
    """Return the reason a flag is ordinary churn, or None to keep it."""
    trail = [r for r in (f.get("rank_trail") or []) if isinstance(r, int)]
    on = (f.get("time_on_list") or {}).get("minutes")
    lst, title = f.get("list"), f.get("title") or ""
    if any(e.get("signal") == "returned" for e in f.get("evidence") or []):
        return "came back once before"
    if (_minutes(gen, gone) or 0) < MIN_GONE_MIN:
        return "gone under 60 min"
    if not trail or trail[-1] > MAX_DROP_RANK:
        return "not in the top 10 when it left"
    if trail[-1] > min(trail) + SLIDE_RANKS:
        return "slid down before leaving"
    if on is None or on < MIN_ON_MIN or on >= MEDIAN_TOP10_MIN.get(lst, 0) / 2:
        return "on the list a normal length of time"
    lo, hi = ROTATION_BAND_MIN.get(lst, (1, 0))
    if lo <= on <= hi:
        return "inside the list's normal rotation"
    if any((s.get("where") in PLATFORMS) for s in f.get("survived_on") or []):
        return "still on another hot list"
    miss = (f.get("censored_at") or {}).get("first_missing")
    batch = [g for g in flags if g is not f and g.get("list") == lst and miss
             and (g.get("censored_at") or {}).get("first_missing") == miss]
    # Topics that left in the same snapshot: a list refresh, unless they are all one story and none came back.
    terms = topic_terms(title)
    if batch and not all(g.get("status") != "returned" and terms & topic_terms(g.get("title")) for g in batch):
        return "left with other flagged topics (batch drop)"
    for g in flags:
        if g is f or g.get("list") != lst:
            continue
        if not is_retitle(title, g.get("title")):
            continue
        g_in, g_out = parse_z(g.get("first_seen_at")), parse_z(g.get("last_seen_at"))
        appeared = _minutes(g_in, gone)
        if (appeared is not None and abs(appeared) <= RETITLE_WINDOW_MIN) or (g_in and g_out and g_in <= gone <= g_out):
            return "retitled"  # the edited headline appeared, or was already on the list, when this one left
    if history is not None:
        try:
            later = history_titles(history, lst, gone, TOPIC_WINDOW_MIN) - {title}
        except sqlite3.Error as exc:
            print(f"warning: history query failed ({exc})", file=sys.stderr)
            later = set()
        if any(is_retitle(title, t) for t in later):
            return "retitled"
        if any(len(terms & topic_terms(t)) >= 2 for t in later):
            return "topic still on the list"
    return None


def select(data, hours, by_id, by_t, history=None, strict=True, funnel=None):
    gen = parse_z(data.get("meta", {}).get("generated_at")) or datetime.now(timezone.utc)
    cutoff = gen - timedelta(hours=hours)
    flags = data.get("flags", [])
    rows = []
    for f in flags:
        if f.get("status") not in ("likely_censored", "censored"):
            continue  # "returned" items came back, so they are not shown
        gone = parse_z((f.get("censored_at") or {}).get("first_missing")) or parse_z(f.get("last_seen_at"))
        if not gone or gone < cutoff:
            continue
        title = f.get("title") or ""
        if PII.search(title):
            continue
        if funnel is not None:
            funnel["flagged"] = funnel.get("flagged", 0) + 1
        if strict:
            reason = why_cut(f, gone, gen, flags, history)
            if reason:
                if funnel is not None:
                    funnel[reason] = funnel.get(reason, 0) + 1
                continue
        en = f.get("title_en") or by_id.get(f.get("item_id")) or by_t.get(title) or ""
        ev = has_evidence(f)
        rows.append({
            "platform": f.get("list"),
            "platform_name": PLATFORMS.get(f.get("list"), f.get("list")),
            "title_zh": title,
            "title_en": en,
            "label": card_label(ev)[0],
            "label_zh": card_label(ev)[1],
            "evidence_strength": "stronger" if ev else "standard",
            "peak_rank": f.get("peak_rank"),
            "first_seen_et": et(parse_z(f.get("first_seen_at"))),
            "last_seen_et": et(parse_z(f.get("last_seen_at"))),
            "first_missing_et": et(gone),
            "minutes_on_list": (f.get("time_on_list") or {}).get("minutes"),
            "url": f.get("url"),
            "official_line": f.get("official_line"),
            "official_line_zh": f.get("official_line_zh"),
            "evidence": evidence_lines(f),
            "_gone": gone,
        })
    rows.sort(key=lambda r: (r["peak_rank"] or 99, -r["_gone"].timestamp()))
    if strict:
        kept = []
        for r in rows:
            r["title"] = r["title_zh"]
            match = next((k for k in kept if same_event(r, k)), None)
            if match is not None:
                # Merged into the kept card: the card has evidence if any member does.
                if r["evidence_strength"] == "stronger" and match["evidence_strength"] != "stronger":
                    match["evidence_strength"] = "stronger"
                    match["label"], match["label_zh"] = LABEL_EVIDENCE
                if funnel is not None:
                    funnel["same story as a kept item"] = funnel.get("same story as a kept item", 0) + 1
            else:
                kept.append(r)
        for r in rows:
            r.pop("title", None)
        rows = kept
    if funnel is not None:
        funnel["kept"] = len(rows)
        order = ["flagged"] + CUT_ORDER + ["kept"]
        ordered = {k: funnel.get(k, 0) for k in order}
        funnel.clear()
        funnel.update(ordered)
    return gen, rows


CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e7e5e0;--accent:#b4232a;--chip:#fbeaea}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",sans-serif}
a{color:#1a5fb4}header{background:#16161a;color:#fff;padding:40px 20px 32px}
.wrap{max-width:980px;margin:0 auto;padding:0 20px}header .wrap{padding:0}
h1{margin:0 0 6px;font-size:34px;letter-spacing:-.5px}h1 span{color:#ff6b6b}
.sub{color:#c9c9cf;margin:0}.stats{display:flex;gap:12px;flex-wrap:wrap;margin-top:22px}
.stat{background:#24242a;border-radius:12px;padding:10px 16px}.stat b{display:block;font-size:24px}.stat small{color:#a9a9b0}
.note{background:#fff8e6;border:1px solid #f0dfb0;border-radius:12px;padding:14px 16px;margin:24px 0;font-size:14.5px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 18px}.filters button{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 14px;font:inherit;font-size:14px;cursor:pointer}
.filters button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.grid{display:grid;gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}
.plat{color:#fff;border-radius:6px;padding:2px 8px;font-weight:600}.lab{background:var(--chip);color:var(--accent);border-radius:6px;padding:2px 8px;font-weight:600}
.no-evidence{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:24px 0 0;font-size:14.5px}
.lab.off{background:#eeeef0;color:#3a3a3f}.rank{margin-left:auto;font-weight:700;font-size:15px}
.zh{font-size:20px;font-weight:650;margin:10px 0 2px}.en{color:var(--muted);margin:0 0 10px}.en.pending{font-style:italic;font-size:14px}
.times{font-size:14px;color:#3a3a3f;margin-bottom:8px}details{font-size:14px}summary{cursor:pointer;color:#1a5fb4}
details ul{margin:8px 0 0;padding-left:20px}details li{margin:3px 0}
.links{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:28px 0}
.links a{display:block;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;text-decoration:none;color:var(--ink)}
.links a b{display:block;color:#1a5fb4}.empty{background:#fff;border:1px dashed var(--line);border-radius:14px;padding:30px;text-align:center;color:var(--muted)}
footer{color:var(--muted);font-size:13px;padding:24px 0 48px}
"""

JS = """
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{
 document.querySelectorAll('.filters button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
 const p=b.dataset.p;document.querySelectorAll('.card').forEach(c=>c.style.display=(p==='all'||c.dataset.p===p)?'':'none');});
"""


def render(gen, rows, hours):
    e = html.escape
    counts = {}
    for r in rows:
        counts[r["platform"]] = counts.get(r["platform"], 0) + 1
    cards = []
    for r in rows:
        ev = []
        for x in r["evidence"]:
            if isinstance(x, tuple):
                what, src, url, pub = x
                link = f'<a href="{e(url)}" rel="nofollow noopener" target="_blank">{e(src)}</a>' if url else e(src)
                ev.append(f"<li>{e(what)}: {link}" + (f" ({e(pub)})" if pub else "") + "</li>")
            else:
                ev.append(f"<li>{e(x)}</li>")
        ol = r.get("official_line")
        if isinstance(ol, dict) and ol.get("url"):
            raw = str(ol.get("published") or "")
            pub = et(parse_z(raw)) if raw.endswith("Z") or "+" in raw[10:] else (f"{raw} source time" if raw else "")
            ev.append(f'<li>Related coverage still online 相关报道: <a href="{e(ol["url"])}" rel="nofollow noopener" target="_blank">{e(bilingual(ol.get("source")))}: {e(ol.get("title") or "")}</a>' + (f" ({e(pub)})" if pub else "") + "</li>")
        elif isinstance(ol, str) and ol:
            ev.append(f"<li>Official response 官方回应: {e(ol)} / {e(r.get('official_line_zh') or '')}</li>")
        if r.get("url"):
            ev.append(f'<li><a href="{e(r["url"])}" rel="nofollow noopener" target="_blank">Search this topic on {e(r["platform_name"])}</a></li>')
        en = (f'<p class="en">{e(r["title_en"])}</p>' if r["title_en"]
              else '<p class="en pending">English translation pending · 英文翻译待补</p>')
        color = PLATFORM_COLORS.get(r["platform"], "#555")
        evid = r["evidence_strength"] == "stronger"
        lab_en, lab_zh = card_label(evid)
        ev.insert(0, f"<li>On the list 上榜 {e(r['first_seen_et'])} → last seen 最后出现 {e(r['last_seen_et'])} · "
                     f"{e(mins(r['minutes_on_list']))} on list 在榜时长</li>")
        cards.append(f"""<article class="card" data-p="{e(r['platform'] or '')}" data-evidence="{'yes' if evid else 'no'}">
<div class="top"><span class="plat" style="background:{color}">{e(r['platform_name'])}</span><span class="lab{'' if evid else ' off'}">{e(lab_en)} {e(lab_zh)}</span><span class="rank">peak #{e(str(r['peak_rank']))}</span></div>
<p class="zh">{e(r['title_zh'])}</p>{en}
<div class="times">{e(TIME_LINE.format(time=r['first_missing_et']))}</div>
<details><summary>Evidence 证据 ({len(ev)})</summary><ul>{''.join(ev)}</ul></details></article>""")
    order = [p for p in PLATFORMS if p in counts]
    btns = ['<button class="on" data-p="all">All 全部 (%d)</button>' % len(rows)] + [
        f'<button data-p="{p}">{e(PLATFORMS[p])} ({counts[p]})</button>' for p in order]
    stats = "".join(f'<div class="stat"><b>{counts[p]}</b><small>{e(PLATFORMS[p])}</small></div>' for p in order)
    n_ev = sum(1 for r in rows if r["evidence_strength"] == "stronger")
    label_stats = (f'<div class="stat"><b>{n_ev}</b><small>{e(" ".join(LABEL_EVIDENCE))}</small></div>'
                   f'<div class="stat"><b>{len(rows) - n_ev}</b><small>{e(" ".join(LABEL_NO_EVIDENCE))}</small></div>')
    no_ev_line = (f'<p class="no-evidence" id="no-evidence">{e(NO_EVIDENCE_LINE, quote=False)}</p>\n'
                  if n_ev == 0 and NO_EVIDENCE_LINE else "")
    body = "\n".join(cards) if cards else '<div class="empty">No hot-list topics dropped off in this window. 本时段暂无下榜话题。</div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(HEADING_EN)} · {e(HEADING_ZH)} | China hot-list watch</title>
<meta name="description" content="Topics that left Chinese hot lists (Weibo 微博, Baidu 百度, Zhihu 知乎, Toutiao 今日头条, Bilibili 哔哩哔哩) abruptly and didn't return. Some may be normal rotation. Labeled likely censored when there is hard evidence, otherwise dropped off. Updated hourly.">
<style>{CSS}</style></head><body>
<header><div class="wrap"><h1>{e(HEADING_EN)} <span>{e(HEADING_ZH)}</span></h1>
<p class="sub" id="sub-en">{e(SUBTITLE_EN, quote=False)}</p>
<p class="sub" id="sub-zh" lang="zh">{e(SUBTITLE_ZH)}</p>
<p class="sub win">The {hours} hours to {e(et(gen, '%a %b %-d, %Y, %-I:%M %p ET'))}.</p>
<div class="stats">{label_stats}{stats}</div></div></header>
<main class="wrap">
{no_ev_line}<div class="note"><b>How to read this 说明:</b> each topic left a hot list from the top 10 without sliding down first, well before topics on that list usually drop off, and was still gone an hour later. Retitled headlines, topics still on the list or on another hot list, and batch drops are left out. That is a signal, not proof: lists also churn for ordinary reasons. A topic with hard evidence (the link returns 404/410, the platform shows a removal notice, or a censorship tracker has a dated entry) is labeled <b>Likely censored 疑似被删</b>; every other topic is labeled <b>Dropped off 已下榜</b>. Open "Evidence" for the timeline, link re-checks and any matching tracker entry. Hot-list headlines and public links only; no user data. Times are US Eastern (ET).</div>
<div class="filters">{''.join(btns)}</div>
<section class="grid">{body}</section>
<div class="links">
<a href="{ACTOR}"><b>Full feed on Apify →</b>155 sources, 7 hot lists, English translations, deletion watch. $8 per 1,000 rows.</a>
<a href="{HF}"><b>Free sample on Hugging Face →</b>Load it with <code>datasets</code>.</a>
<a href="{X402}"><b>Pay-per-call API (x402) →</b>$0.01 USDC per call on Base; free <code>/sample</code>.</a>
<a href="deleted-today.json"><b>This page as JSON →</b>Same items, machine-readable.</a>
</div></main>
<footer class="wrap">Built by Ownly from public, logged-out sources. Chinese headlines are as published; English is machine-translated. Source: <a href="{REPO}">{REPO.split('github.com/')[1]}</a>.</footer>
<script>{JS}</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("censored")
    ap.add_argument("out_dir")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--feed-en")
    ap.add_argument("--history", help="history.sqlite, opened read-only, for the retitle / topic checks")
    ap.add_argument("--all-flags", action="store_true", help="skip the stricter cut and show every flag")
    a = ap.parse_args()
    data = json.load(open(a.censored))
    by_id, by_t = load_en(a.feed_en)
    hist = open_history(a.history)
    funnel = {}
    gen, rows = select(data, a.hours, by_id, by_t, history=hist, strict=not a.all_flags, funnel=funnel)
    if hist is not None:
        hist.close()
    import os
    os.makedirs(a.out_dir, exist_ok=True)
    open(os.path.join(a.out_dir, "index.html"), "w").write(render(gen, rows, a.hours))
    out = []
    for r in rows:
        r = dict(r); r.pop("_gone")
        if isinstance(r.get("official_line"), dict):
            r["official_line"] = {k: r["official_line"].get(k) for k in ("source", "title", "url", "published")}
        r["evidence"] = [x if isinstance(x, str) else {"type": x[0], "source": x[1], "url": x[2], "published": x[3]} for x in r["evidence"]]
        out.append(r)
    json.dump({"generated_at_et": et(gen, "%Y-%m-%d %H:%M ET"), "window_hours": a.hours,
               "label": "dropped off (likely censored when there is hard evidence)",
               "note": "Left a hot list from the top 10 without sliding, early for that list, still gone 1 h later. A signal, not proof. "
                       "Items with hard evidence are labeled Likely censored; the rest Dropped off.",
               "count": len(out), "cut": funnel, "items": out}, open(os.path.join(a.out_dir, "deleted-today.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(a.out_dir, ".nojekyll"), "w").close()
    print(f"built {len(rows)} items from {funnel.get('flagged', 0)} flags, window ends {et(gen)}")


if __name__ == "__main__":
    main()
