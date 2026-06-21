#!/usr/bin/env python3
"""
Morning Market Digest Generator
Calls the Anthropic API (with web search enabled) to produce a daily
macro + market digest, and writes it to docs/data.json for the phone
front-end to read.
"""

import json
import os
import sys
from datetime import datetime, timezone
import urllib.request
import urllib.error

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "data.json")

SYSTEM_PROMPT = """You are a markets research assistant producing a morning digest for a single retail investor who wants only the highest-conviction ideas, not a padded list.

You have a web_search tool. Use it to find TODAY's actual news: overnight macro developments, \
major index futures moves, key economic data releases, Fed/central bank news, and notable \
sector or company-specific news. Run multiple searches covering: macro/economic news, \
Fed/rates, major indices, and 2-3 sector-specific searches (tech, energy, healthcare, etc. \
depending on what's moving). Cast a wide net -- you need enough raw candidates to be selective.

SCREENING PROCESS (do this before writing anything):
1. From your research, build a working list of 10-15 candidate tickers/ideas touched by today's \
   news -- more than you'll report.
2. For each candidate, check it against the "high conviction" bar below.
3. Keep only the candidates that clear the bar. Discard the rest, even if that means a short list.
4. Rank what's left and report the top ones, in order of strength.

HIGH CONVICTION BAR -- an idea only qualifies as "high" if it has BOTH:
(a) A specific, dated, or near-term catalyst (an earnings date, a Fed decision, a guidance \
    update, an M&A event, a data release) -- not just "good vibes" or a general theme, and
(b) A quantifiable edge you can point to (an analyst price-target gap, a clear valuation \
    dislocation, a concrete margin/earnings number, an unusual options-flow or volume signal) \
    -- not just a narrative.
If an idea has a real catalyst or theme but lacks a quantifiable edge (or vice versa), label it \
"medium" -- it's still worth watching, just not your top conviction. Use "medium" honestly, not \
as a default hedge -- if something genuinely clears bar (a) and (b), call it "high".

CRITICAL: It is completely acceptable, and often correct, to report FEWER than 5 ideas on a \
quiet news day. Do not invent or pad weak ideas just to hit a count of 5. A short, high-quality \
list is more useful than 5 mediocre ones. Report between 1 and 5 ideas -- whatever number \
actually clears the bar above. If, after genuinely screening, nothing clears even the "medium" \
bar, it is fine to return fewer than 3 ideas total and say so plainly in macro_summary.

After research and screening, produce a JSON object (and ONLY a JSON object, no other text, no \
markdown fences) with this exact structure:

{
  "date": "YYYY-MM-DD",
  "macro_summary": "2-4 sentence overview of the overnight/today macro picture. If today's news \
flow is thin and few or no ideas cleared the high-conviction bar, say so explicitly here.",
  "key_events": ["short bullet", "short bullet", ...],
  "ideas": [
    {
      "ticker": "SYMBOL",
      "type": "stock | etf | fund | option",
      "name": "Full name",
      "thesis": "2-3 sentence explanation of why this is interesting today, grounded in \
specific news/data you found",
      "catalyst": "The specific dated/near-term event or trigger -- this is what justifies the \
conviction level, be concrete (e.g. 'Q2 earnings July 10' not 'upcoming earnings')",
      "edge": "The specific quantifiable gap or signal (e.g. 'Mean analyst target $105 vs ~$84 \
current, ~25% implied upside' or 'Trading at 0.6x peer average EV/EBITDA')",
      "bull_case": "1-2 sentences",
      "bear_case": "1-2 sentences",
      "conviction": "high | medium",
      "category": "macro-driven | sector-driven | earnings-driven | technical | hedge"
    }
  ],
  "disclaimer": "This is automated research synthesis, not financial advice. Not a licensed advisor. Verify independently before acting."
}

Rules:
- 1 to 5 items in "ideas" -- only what genuinely clears the bar. Never pad to reach 5.
- Every idea must be traceable to something concrete you found in search results today \
  (a specific data point, news event, earnings report, guidance change, etc.), not generic \
  evergreen reasoning.
- Be evenhanded: always include a real bear_case, not a throwaway one. A real bear case does \
  not disqualify something from being "high" conviction -- conviction is about the strength of \
  the setup, not the absence of risk.
- Do not present these as recommendations to buy/sell. Frame as "ideas worth researching further."
- Output valid JSON only. No preamble, no code fences, no trailing commentary.
"""

USER_PROMPT = "Generate today's morning market digest. Screen broadly, then report only ideas that genuinely clear the high-conviction bar -- fewer than 5 is fine if that's what the day's news supports."


def call_claude():
    if not API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    body = {
        "model": MODEL,
        "max_tokens": 4000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": USER_PROMPT}],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    # Web search can take a few turns; allow a generous timeout.
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: API call failed: {e.code} {e.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)


def extract_text(api_response):
    """Pull all text blocks out of the response, in order."""
    chunks = []
    for block in api_response.get("content", []):
        if block.get("type") == "text":
            chunks.append(block["text"])
    return "\n".join(chunks)


def extract_json(text):
    """Find and parse the JSON object in the model's text output."""
    text = text.strip()
    # Strip code fences if the model added them despite instructions.
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    # Find the outermost JSON object as a fallback.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model output")
    candidate = text[start : end + 1]
    return json.loads(candidate)


def main():
    print("Calling Claude API...")
    response = call_claude()
    text = extract_text(response)

    try:
        digest = extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"ERROR: Could not parse digest JSON: {e}", file=sys.stderr)
        print("--- Raw model output ---", file=sys.stderr)
        print(text, file=sys.stderr)
        sys.exit(1)

    digest["generated_at"] = datetime.now(timezone.utc).isoformat()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(digest, f, indent=2)

    print(f"Digest written to {OUTPUT_PATH}")
    print(json.dumps(digest, indent=2))


if __name__ == "__main__":
    main()
