# AI Briefing

A small script that pulls recent AI news and research and writes a dated markdown briefing.

## Sources (all free, no API key required)

- **Hacker News** (via the Algolia search API), filtered to AI-related stories
- **arXiv** (`cs.AI` / `cs.LG`), most recently submitted papers
- **RSS**: TechCrunch AI, MIT Technology Review

## Usage

```bash
pip install -r requirements.txt
python3 briefing.py
```

This writes `briefings/YYYY-MM-DD.md`.

Options:

```bash
python3 briefing.py --hours 48 --output-dir briefings
```

- `--hours` — how far back to look for new items (default: 24)
- `--output-dir` — where to write the dated markdown file (default: `briefings`)

## Optional: LLM-summarized digest

By default the script produces a plain digest of headlines grouped by source. If you
set `ANTHROPIC_API_KEY`, it instead sends the raw items to Claude and writes a
narrative digest grouped by theme (model releases, research, industry & policy, etc.)
with one-line summaries.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 briefing.py
```

## Running it daily

Schedule it with cron, e.g. every morning at 7am:

```
0 7 * * * cd /path/to/AI-briefing && ANTHROPIC_API_KEY=sk-ant-... python3 briefing.py
```
