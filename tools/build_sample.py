#!/usr/bin/env python3
"""Build the free discovery sample from live pipeline output.

Usage: build_sample.py <pipeline_output_dir> <out_dir>
The static sample carries news rows, hot-list rows and topic clusters only. Deletion-watch
flags are left out: a hot-list exit is a signal, not proof, and a frozen sample can't show
the re-checks that make a flag meaningful. Live flags, each labeled "likely censored" with
its evidence, are on https://joydai2026-del.github.io/china-news-feed-samples/ and in the
Apify actor. Topics with any deletion-watch status are skipped, and censorship fields are
not copied. Headlines, short excerpts and links only. No user data.
"""
import json, os, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PLATFORMS = {"weibo": "Weibo 微博", "baidu": "Baidu 百度", "zhihu": "Zhihu 知乎", "toutiao": "Toutiao 今日头条",
             "douyin": "Douyin 抖音", "bilibili": "Bilibili 哔哩哔哩", "kuaishou": "Kuaishou 快手"}
PII = re.compile(r"(\b1[3-9]\d{9}\b|\b\d{17}[\dXx]\b|[\w.+-]+@[\w-]+\.[\w.]+|@\w{3,})")
FLAT = re.compile(r"\[Censored\]|【已被审查】|\bCensored\b|已被审查|被审查")


def et(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%d %H:%M ET")


def main(src, out):
    os.makedirs(out, exist_ok=True)
    gen = json.load(open(os.path.join(src, "censored.json")))["meta"]["generated_at"]
    meta = {"generated_at_et": et(gen), "product": "Ownly China News Feed with Deletion Watch",
            "license": "CC BY 4.0 for Ownly's compilation, labels and summaries; headlines, excerpts and linked articles remain with their publishers.",
            "note": "Free discovery sample: headlines, short excerpts and links only. English is machine-translated. Deletion-watch flags are not included; see the live page.",
            "full_feed": "https://apify.com/china.unofficial/china-news-feed",
            "deleted_today": "https://joydai2026-del.github.io/china-news-feed-samples/"}
    fe = json.load(open(os.path.join(src, "feed_en.json")))["items"]
    en = [i for i in fe if i.get("kind") == "news" and i.get("headline_en")]
    en.sort(key=lambda i: i.get("fetched_at") or "", reverse=True)
    seen, en_rows = set(), []
    for i in en:  # at most 3 per outlet so the sample shows range
        if sum(1 for r in en_rows if r["source_id"] == i["source_id"]) >= 3 or i["id"] in seen:
            continue
        seen.add(i["id"])
        en_rows.append({k: i.get(k) for k in ("id", "topic_id", "source_id", "outlet", "source_type", "headline_en", "summary_en", "url", "fetched_at")})
        if len(en_rows) == 50:
            break
    json.dump({"meta": meta, "items": en_rows}, open(os.path.join(out, "feed_en.sample.json"), "w"), ensure_ascii=False, indent=1)

    fz = json.load(open(os.path.join(src, "feed_zh.json")))["items"]
    hot = sorted((i for i in fz if i.get("kind") == "hot" and not PII.search(i.get("title") or "")), key=lambda i: (i.get("rank") or 99))
    news = sorted((i for i in fz if i.get("kind") == "news"), key=lambda i: i.get("fetched_at") or "", reverse=True)
    zh_rows, per = [], {}
    for i in hot[:25] + news:
        if i.get("kind") == "news":
            per[i["source_id"]] = per.get(i["source_id"], 0) + 1
            if per[i["source_id"]] > 2:
                continue
        zh_rows.append({k: i.get(k) for k in ("id", "topic_id", "source_id", "outlet", "source_type", "title", "url", "rank", "heat", "fetched_at")})
        if len(zh_rows) == 50:
            break
    json.dump({"meta": meta, "items": zh_rows}, open(os.path.join(out, "feed_zh.sample.json"), "w"), ensure_ascii=False, indent=1)

    tp = json.load(open(os.path.join(src, "topics.json")))["topics"]
    topics = []
    for t in sorted(tp, key=lambda t: -(t.get("distinct_sources") or 0)):
        s = t.get("summary_en") or ""
        if t.get("censored") or t.get("censorship_flags") or t.get("censorship_status") or s.startswith("[") or FLAT.search(s) or "Pulled from" in s:
            continue
        # the summarizer leaves 'X headline it as: "".' when it has no headline text
        s = s.replace(' headline it as: "".', " cover it.")
        topics.append({"topic_id": t["topic_id"], "label_zh": t.get("label_zh"), "summary_en": s,
                       "n_items": t.get("n_items"), "distinct_sources": t.get("distinct_sources"),
                       "source_types": t.get("source_types")})
        if len(topics) == 20:
            break
    json.dump({"meta": meta, "topics": topics}, open(os.path.join(out, "topics.sample.json"), "w"), ensure_ascii=False, indent=1)

    counts = {"feed_en": len(en_rows), "feed_zh": len(zh_rows), "topics": len(topics)}
    json.dump({**meta, "counts": counts}, open(os.path.join(out, "README_meta.json"), "w"), ensure_ascii=False, indent=1)
    for name in os.listdir(out):
        if FLAT.search(open(os.path.join(out, name)).read()):
            sys.exit(f"flat Censored label left in {name}")
    print(counts)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
