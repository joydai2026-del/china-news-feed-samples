#!/usr/bin/env python3
"""Build the "Deleted today / 今日被删" GitHub Pages page from the live censored.json.

Usage: build_deleted_today.py <censored.json> <out_dir> [--hours 24] [--feed-en feed_en.json]
Writes <out_dir>/index.html and <out_dir>/deleted-today.json.
Every item is labeled "Likely censored / 疑似被删". Hot-list headlines and public links only; no user data.
"""
import argparse, html, json, re, sys
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


def select(data, hours, by_id, by_t):
    gen = parse_z(data.get("meta", {}).get("generated_at")) or datetime.now(timezone.utc)
    cutoff = gen - timedelta(hours=hours)
    rows = []
    for f in data.get("flags", []):
        if f.get("status") not in ("likely_censored", "censored"):
            continue  # "returned" items came back, so they are not shown
        gone = parse_z((f.get("censored_at") or {}).get("first_missing")) or parse_z(f.get("last_seen_at"))
        if not gone or gone < cutoff:
            continue
        title = f.get("title") or ""
        if PII.search(title):
            continue
        en = f.get("title_en") or by_id.get(f.get("item_id")) or by_t.get(title) or ""
        rows.append({
            "platform": f.get("list"),
            "platform_name": PLATFORMS.get(f.get("list"), f.get("list")),
            "title_zh": title,
            "title_en": en,
            "label": "Likely censored",
            "label_zh": "疑似被删",
            "evidence_strength": "stronger" if f.get("tier") == "high" else "standard",
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
.str{color:var(--muted)}.rank{margin-left:auto;font-weight:700;font-size:15px}
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
        strength = "Stronger evidence 证据较强 (provisional)" if r["evidence_strength"] == "stronger" else "Standard evidence 一般证据"
        cards.append(f"""<article class="card" data-p="{e(r['platform'] or '')}">
<div class="top"><span class="plat" style="background:{color}">{e(r['platform_name'])}</span><span class="lab">Likely censored · 疑似被删</span><span class="str">{strength}</span><span class="rank">peak #{e(str(r['peak_rank']))}</span></div>
<p class="zh">{e(r['title_zh'])}</p>{en}
<div class="times">On the list 上榜 {e(r['first_seen_et'])} → last seen 最后出现 {e(r['last_seen_et'])} · gone by 消失于 {e(r['first_missing_et'])} · {e(mins(r['minutes_on_list']))} on list</div>
<details><summary>Evidence 证据 ({len(ev)})</summary><ul>{''.join(ev)}</ul></details></article>""")
    order = [p for p in PLATFORMS if p in counts]
    btns = ['<button class="on" data-p="all">All 全部 (%d)</button>' % len(rows)] + [
        f'<button data-p="{p}">{e(PLATFORMS[p])} ({counts[p]})</button>' for p in order]
    stats = "".join(f'<div class="stat"><b>{counts[p]}</b><small>{e(PLATFORMS[p])}</small></div>' for p in order)
    body = "\n".join(cards) if cards else '<div class="empty">No hot-list topics vanished in this window. 本时段暂无疑似被删话题。</div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deleted today · 今日被删 | China hot-list deletion watch</title>
<meta name="description" content="Topics that vanished from Chinese hot lists (Weibo 微博, Baidu 百度, Zhihu 知乎, Toutiao 今日头条, Bilibili 哔哩哔哩) while still trending, labeled likely censored, with evidence. Updated daily.">
<style>{CSS}</style></head><body>
<header><div class="wrap"><h1>Deleted today <span>今日被删</span></h1>
<p class="sub">Topics that vanished from Chinese hot lists while still trending, in the {hours} hours to {e(et(gen, '%a %b %-d, %Y, %-I:%M %p ET'))}. 热榜上仍在热议却突然消失的话题。</p>
<div class="stats"><div class="stat"><b>{len(rows)}</b><small>Likely censored 疑似被删</small></div>{stats}</div></div></header>
<main class="wrap">
<div class="note"><b>How to read this 说明:</b> each topic left a hot list abruptly while ranked high and was still gone at our 10-minute re-check. That is a signal, not proof: lists also churn for ordinary reasons. Every item is labeled <b>likely censored 疑似被删</b>. Open "Evidence" for the timeline, link re-checks and any matching tracker entry. Hot-list headlines and public links only; no user data. Times are US Eastern (ET).</div>
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
    a = ap.parse_args()
    data = json.load(open(a.censored))
    by_id, by_t = load_en(a.feed_en)
    gen, rows = select(data, a.hours, by_id, by_t)
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
    json.dump({"generated_at_et": et(gen, "%Y-%m-%d %H:%M ET"), "window_hours": a.hours, "label": "likely censored",
               "note": "Abrupt exit from a hot list while ranked high, still gone at T+10 min. A signal, not proof.",
               "count": len(out), "items": out}, open(os.path.join(a.out_dir, "deleted-today.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(a.out_dir, ".nojekyll"), "w").close()
    print(f"built {len(rows)} items, window ends {et(gen)}")


if __name__ == "__main__":
    main()
