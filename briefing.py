#!/usr/bin/env python3
"""Fetch recent AI news/research and generate a markdown briefing.

Sources (all free, no API key required):
  - Hacker News (Algolia search API), filtered to AI-related stories
  - arXiv (cs.AI / cs.LG), most recent papers
  - RSS feeds from TechCrunch AI and MIT Technology Review

If ANTHROPIC_API_KEY is set, the raw items are summarized into a narrative
digest via the Claude API. Otherwise a plain formatted digest of headlines
and links is produced.

Usage:
    python3 briefing.py [--output-dir briefings] [--hours 24]
"""
import argparse
import datetime
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET

import requests

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ARXIV_API_URL = "http://export.arxiv.org/api/query"
RSS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "MIT Technology Review": "https://www.technologyreview.com/feed/",
}
AI_KEYWORDS = (
    "ai", "artificial intelligence", "llm", "large language model", "gpt",
    "claude", "anthropic", "openai", "gemini", "chatgpt", "machine learning",
    "neural network", "deep learning", "genai", "generative ai",
)


def fetch_hacker_news(hours: int, limit: int = 15) -> list[dict]:
    since = int((datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(hours=hours)).timestamp())
    params = {
        "query": "AI",
        "tags": "story",
        "numericFilters": f"created_at_i>{since}",
        "hitsPerPage": limit,
    }
    resp = requests.get(HN_SEARCH_URL, params=params, timeout=20)
    resp.raise_for_status()
    items = []
    for hit in resp.json().get("hits", []):
        title = hit.get("title") or ""
        if not any(k in title.lower() for k in AI_KEYWORDS):
            continue
        items.append({
            "source": "Hacker News",
            "title": title,
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
            "points": hit.get("points", 0),
            "extra": f"{hit.get('points', 0)} points, {hit.get('num_comments', 0)} comments",
        })
    return items


def fetch_arxiv(hours: int, limit: int = 10) -> list[dict]:
    params = (
        "search_query=cat:cs.AI+OR+cat:cs.LG"
        "&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={limit}"
    )
    resp = requests.get(f"{ARXIV_API_URL}?{params}", timeout=20)
    resp.raise_for_status()
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.content)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    items = []
    for entry in root.findall("atom:entry", ns):
        published = entry.findtext("atom:published", default="", namespaces=ns)
        try:
            pub_dt = datetime.datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=datetime.timezone.utc)
        except ValueError:
            pub_dt = None
        if pub_dt and pub_dt < cutoff:
            continue
        title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
        link = entry.findtext("atom:id", default="", namespaces=ns)
        authors = [a.findtext("atom:name", default="", namespaces=ns)
                   for a in entry.findall("atom:author", ns)]
        items.append({
            "source": "arXiv",
            "title": title,
            "url": link,
            "extra": ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
        })
    return items


def fetch_rss(name: str, url: str, hours: int, limit: int = 10) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    items = []
    channel_items = root.findall("./channel/item") or root.findall(
        "{http://www.w3.org/2005/Atom}entry")
    for item in channel_items[: limit * 3]:
        title_el = item.find("title")
        link_el = item.find("link")
        pubdate_el = item.find("pubDate")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else (
            link_el.get("href", "") if link_el is not None else "")
        pub_dt = None
        if pubdate_el is not None and pubdate_el.text:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
                try:
                    pub_dt = datetime.datetime.strptime(pubdate_el.text.strip(), fmt)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                    break
                except ValueError:
                    continue
        if pub_dt and pub_dt < cutoff:
            continue
        if not title or not link:
            continue
        items.append({"source": name, "title": title, "url": link, "extra": ""})
        if len(items) >= limit:
            break
    return items


def collect_items(hours: int) -> dict[str, list[dict]]:
    collected = {}
    fetchers = [
        ("Hacker News", lambda: fetch_hacker_news(hours)),
        ("arXiv", lambda: fetch_arxiv(hours)),
    ]
    for name, url in RSS_FEEDS.items():
        fetchers.append((name, lambda n=name, u=url: fetch_rss(n, u, hours)))

    for name, fetch in fetchers:
        try:
            collected[name] = fetch()
        except Exception as exc:  # network hiccups shouldn't kill the whole briefing
            print(f"warning: failed to fetch {name}: {exc}", file=sys.stderr)
            collected[name] = []
    return collected


def render_plain_digest(date_str: str, items_by_source: dict[str, list[dict]]) -> str:
    lines = [f"# AI Briefing — {date_str}", ""]
    total = sum(len(v) for v in items_by_source.values())
    if total == 0:
        lines.append("No new items found in the selected time window.")
        return "\n".join(lines)

    for source, items in items_by_source.items():
        if not items:
            continue
        lines.append(f"## {source}")
        lines.append("")
        for item in items:
            extra = f" _{item['extra']}_" if item.get("extra") else ""
            lines.append(f"- [{item['title']}]({item['url']}){extra}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_summarized_digest(date_str: str, items_by_source: dict[str, list[dict]]) -> str:
    import anthropic

    client = anthropic.Anthropic()
    raw_lines = []
    for source, items in items_by_source.items():
        for item in items:
            raw_lines.append(f"[{source}] {item['title']} ({item['url']})")
    raw_text = "\n".join(raw_lines)

    if not raw_lines:
        return render_plain_digest(date_str, items_by_source)

    prompt = (
        "You are writing a concise daily AI news briefing for a technical reader. "
        "Below is a raw list of AI-related headlines and links gathered from Hacker News, "
        "arXiv, and tech news RSS feeds. Group related items, drop pure duplicates, and "
        "write a markdown briefing with a few thematic sections (e.g. 'Model releases', "
        "'Research', 'Industry & policy'). For each item, include a one-sentence summary "
        "and a markdown link. Keep it tight — this is a daily skim, not an essay.\n\n"
        f"Raw items:\n{raw_text}"
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    body = "".join(block.text for block in response.content if hasattr(block, "text"))
    return f"# AI Briefing — {date_str}\n\n{body.strip()}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="briefings",
                         help="Directory to write the dated markdown briefing into")
    parser.add_argument("--hours", type=int, default=24,
                         help="How many hours back to look for new items")
    args = parser.parse_args()

    date_str = datetime.date.today().isoformat()
    print(f"Fetching AI news from the last {args.hours}h...")
    items_by_source = collect_items(args.hours)

    for source, items in items_by_source.items():
        print(f"  {source}: {len(items)} item(s)")

    if os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY found — summarizing with Claude...")
        digest = render_summarized_digest(date_str, items_by_source)
    else:
        print("No ANTHROPIC_API_KEY set — writing plain headline digest.")
        digest = render_plain_digest(date_str, items_by_source)

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, f"{date_str}.md")
    with open(out_path, "w") as f:
        f.write(digest)

    print(f"Wrote briefing to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
