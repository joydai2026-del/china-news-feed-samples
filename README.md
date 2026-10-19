# China News Feed with Deletion Watch — free samples

Free discovery samples from **Ownly's China News Feed with Deletion Watch**, a bilingual (Chinese / English) China news feed plus a deletion watch on Chinese hot-search lists.

**Get the full feed on the Apify Store: https://apify.com/china.unofficial/china-news-feed**

## What is in a sample
Headlines, short excerpts, and links only (not full article text). English text is machine-translated.

Hot lists watched include Weibo 微博, Baidu 百度, Zhihu 知乎, Toutiao 今日头条, Bilibili 哔哩哔哩, Douyin 抖音, and Kuaishou 快手. News sources include state media such as Xinhua 新华社 and CGTN 中国国际电视台, plus overseas Chinese-language outlets such as Focus Taiwan 中央社 (CNA 中央通讯社).

## Files (2026-10-19/)
| File | Contents |
|---|---|
| `feed_en.sample.json` | 50 English feed rows (English-language outlets and translated rows) |
| `feed_zh.sample.json` | 50 Chinese feed rows (top hot-list rows plus news) |
| `topics.sample.json` | 20 topic clusters across state, overseas and platform sources |
| `README_meta.json` | Generation time and counts |

Generated from the live pipeline on 2026-10-19 by `tools/build_sample.py`.

**No deletion-watch flags in the static sample.** A topic leaving a hot list is a signal, not proof, and a frozen file can't show the follow-up re-checks. The earlier 2026-10-12 sample is gone, along with its flag file and topic labels. Those flags predated the current evidence rule, and some were plainly wrong (for example a tennis win, 创造历史！郑钦文中网夺冠). Current flags are on the live page below, each labeled **likely censored 疑似被删** with its evidence.

## Full product
Language choice (Chinese, English, or both) and the deletion watch are on the Apify listing:
https://apify.com/china.unofficial/china-news-feed

## Dropped off today / 今日下榜 (live page)
https://joydai2026-del.github.io/china-news-feed-samples/ lists hot-list topics that left a list abruptly in the last 24 hours and didn't return (some may be normal rotation). A topic with hard evidence is labeled **Likely censored 疑似被删**; the rest are labeled **Dropped off 已下榜**. Each card shows its evidence (timeline in ET, link re-checks, tracker matches). It's rebuilt daily from the live pipeline by `tools/publish_deleted_today.sh`, and the same data is at `docs/deleted-today.json`. It contains hot-list headlines and public links only, no user data.

## Related links

- Hugging Face dataset (same sample, loadable with `datasets`): https://huggingface.co/datasets/freedom-press/china-news-feed-sample
- MCP server for Claude Desktop, Cursor and other MCP clients: https://github.com/joydai2026-del/china-news-feed-mcp
- Apify actor (full feed, $8 per 1,000 rows): https://apify.com/china.unofficial/china-news-feed

## License
CC BY 4.0 for Ownly's compilation, labels, summaries and translations (see `LICENSE`). Headlines, excerpts and linked articles remain with their publishers.
