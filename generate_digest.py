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
POLYGON_KEY = os.environ.get("POLYGON_API_KEY")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "docs", "data.json")
PREFS_PATH = os.path.join(os.path.dirname(__file__), "preferences.txt")

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
- Keep each field concise: thesis 2-3 sentences max, catalyst 1 sentence, edge 1-2 sentences, bull/bear 1-2 sentences each. Do not write essays -- the phone UI shows these as short cards.
"""

def load_preferences():
    """Load user preferences from preferences.txt if it exists."""
    if os.path.exists(PREFS_PATH):
        try:
            with open(PREFS_PATH) as f:
                prefs = f.read().strip()
            if prefs:
                return f"\n=== INVESTOR PREFERENCES (always apply these) ===\n{prefs}\n=== END PREFERENCES ===\n"
        except Exception as e:
            print(f"  Warning: could not load preferences.txt: {e}", file=sys.stderr)
    return ""


def build_user_prompt():
    """Build the user prompt, injecting live Polygon data and preferences."""
    # Import here so the file still works even if polygon_data.py is missing
    market_data = ""
    earnings_data = ""
    try:
        sys.path.insert(0, os.path.dirname(__file__))

        # Load watchlist from preferences
        watchlist = []
        if os.path.exists(PREFS_PATH):
            with open(PREFS_PATH) as f:
                for line in f:
                    if line.lower().startswith("watchlist:"):
                        tickers = line.split(":", 1)[1].strip()
                        watchlist = [t.strip().upper() for t in tickers.split(",") if t.strip()]

        # Polygon: live prices
        import polygon_data
        market_data = polygon_data.build_market_context(watchlist=watchlist)
    except Exception as e:
        print(f"  Warning: Polygon data fetch failed: {e} — continuing without live data", file=sys.stderr)

    try:
        # Earnings calendar: confirmed dates
        import earnings_calendar
        earnings_data = earnings_calendar.build_earnings_context(watchlist=watchlist, days_ahead=14)
    except Exception as e:
        print(f"  Warning: Earnings calendar fetch failed: {e} — continuing without calendar", file=sys.stderr)

    prefs = load_preferences()

    kalshi_block = ""
    try:
        import kalshi_data
        kalshi_block = kalshi_data.build_kalshi_context()
    except Exception as e:
        print(f"  Warning: Kalshi fetch failed: {e} — continuing without prediction-market odds", file=sys.stderr)

    base = "Generate today's morning market digest. Screen broadly, then report only ideas that genuinely clear the high-conviction bar -- fewer than 5 is fine if that's what the day's news supports."

    parts = [base]
    if market_data:
        parts.append(market_data)
    if earnings_data:
        parts.append(earnings_data)
    if prefs:
        parts.append(prefs)
    if kalshi_block:
        parts.append(kalshi_block)
    if market_data:
        parts.append("IMPORTANT: Where verified Polygon prices appear above for a ticker you are considering, use those exact figures in your edge calculation -- do not substitute a price from web search.")
    if earnings_data:
        parts.append("IMPORTANT: Where a confirmed earnings date appears above for a ticker you are considering, use that exact date and timing in your catalyst field -- do not substitute a date from web search.")
    return "\n\n".join(parts)


def call_claude(user_prompt):
    if not API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    body = {
        "model": MODEL,
        "max_tokens": 6000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
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


def call_claude_followup(messages):
    """
    Second call, no tools: explicitly asks the model to restate ONLY the final
    JSON object from its own prior reasoning, with nothing else. This avoids
    fragile parsing of a response that mixes reasoning text and JSON.
    """
    followup_messages = messages + [
        {
            "role": "user",
            "content": (
                "Output ONLY the final JSON object from your analysis above, and nothing else. "
                "No reasoning, no code fences, no commentary before or after -- just the raw "
                "JSON object starting with { and ending with }."
            ),
        }
    ]

    body = {
        "model": MODEL,
        "max_tokens": 5000,
        "system": SYSTEM_PROMPT,
        "messages": followup_messages,
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

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"ERROR: Follow-up API call failed: {e.code} {e.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)


def extract_text(api_response):
    """Pull all text blocks out of the response, in order."""
    chunks = []
    for block in api_response.get("content", []):
        if block.get("type") == "text":
            chunks.append(block["text"])
    return "\n".join(chunks)


def extract_json(text):
    """
    Find and parse a JSON object in the model's text output. Handles the case
    where the model includes reasoning text and/or multiple JSON-looking
    blocks by trying, in order: a fenced ```json block, then each top-level
    {...} span found via brace matching, preferring the LAST valid one (since
    models often think out loud first, then restate a final clean version).
    """
    text = text.strip()

    candidates = []

    # 1. Any fenced ```json ... ``` or ``` ... ``` blocks.
    import re
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        candidates.append(match.group(1).strip())

    # 2. Brace-matched top-level {...} spans across the whole text, in case
    #    there's no fence (or in addition to it).
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start : i + 1])
                    start = None

    # Try candidates last-first, since a restated "final" JSON tends to come
    # after any exploratory reasoning blocks.
    last_error = None
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and "ideas" in parsed:
                return parsed
        except json.JSONDecodeError as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    raise ValueError("No valid JSON object with an 'ideas' key found in model output")



VERIFY_SYSTEM = """You are a fact-checker reviewing a morning market digest for a retail investor.
You will receive a JSON digest and your job is to check it for internal errors and return a corrected version.

CHECK EACH IDEA FOR:
1. MATH CONSISTENCY: If the edge field says "Mean analyst target $X vs current price $Y implies Z% upside",    verify that (X-Y)/Y * 100 ≈ Z. If the math is wrong, correct the percentage.
2. CONVICTION ALIGNMENT: If conviction is "high" but there is no specific dated catalyst (e.g. no    earnings date, no specific Fed decision date), downgrade to "medium" and note why.
3. VAGUE CATALYSTS: If catalyst says "upcoming earnings" or "expected earnings" without a specific date,    but the edge or thesis mentions a specific date, update the catalyst to use that specific date.
4. INTERNAL CONTRADICTIONS: If the thesis says one thing and the bear_case contradicts a fact in the thesis    (not just a risk -- an actual factual contradiction), correct it.
5. STALE PRICES: If the edge field uses a price that differs significantly from a price mentioned elsewhere    in the same idea, flag and standardize to the most recently cited figure.

DO NOT:
- Change the substance or investment thesis of any idea
- Add new ideas or remove ideas
- Change conviction from medium to high (only downgrade, never upgrade)
- Alter the disclaimer
- Make changes for style or wording preferences -- only fix factual errors and math

OUTPUT: Return the corrected JSON object only. If no corrections were needed, return the original JSON unchanged. No preamble, no explanation of what you changed, no code fences -- just the raw JSON.
"""

def call_claude_verify(digest, polygon_prices=None):
    """
    Third Claude call (no tools): fact-checks the digest for internal
    math errors, vague catalysts, and conviction mismatches.
    Returns a corrected digest dict, or the original if no issues found.
    """
    price_note = ""
    if polygon_prices:
        price_note = "\n\nVerified Polygon prices for reference:\n" + "\n".join(
            f"  {t}: ${p:.2f} prev close" for t, p in polygon_prices.items()
        )

    verify_prompt = (
        "Please fact-check the following morning market digest for internal math errors, "
        "vague catalysts, and conviction mismatches. Return the corrected JSON only."
        + price_note
        + "\n\nDIGEST TO CHECK:\n"
        + json.dumps(digest, indent=2)
    )

    body = {
        "model": MODEL,
        "max_tokens": 5000,
        "system": VERIFY_SYSTEM,
        "messages": [{"role": "user", "content": verify_prompt}],
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

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            response = json.loads(resp.read().decode("utf-8"))
        verified_text = extract_text(response)
        verified = extract_json(verified_text)
        # Preserve generated_at if it was on the original
        if "generated_at" in digest:
            verified["generated_at"] = digest["generated_at"]
        print("Verification pass complete.")
        return verified
    except Exception as e:
        print(f"  Warning: verification pass failed ({e}) — using original digest", file=sys.stderr)
        return digest




def main():
    print("Calling Claude API...")
    # Build prompt with live data injected
    user_prompt = build_user_prompt()
    response = call_claude(user_prompt)
    text = extract_text(response)

    try:
        digest = extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Could not cleanly parse JSON from the first response ({e}); asking the model to restate it...")
        followup_messages = [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": response.get("content", [])},
        ]
        followup_response = call_claude_followup(followup_messages)
        followup_text = extract_text(followup_response)
        try:
            digest = extract_json(followup_text)
        except (ValueError, json.JSONDecodeError) as e2:
            print(f"ERROR: Could not parse digest JSON even after follow-up: {e2}", file=sys.stderr)
            print("--- Raw first-response output ---", file=sys.stderr)
            print(text, file=sys.stderr)
            print("--- Raw follow-up output ---", file=sys.stderr)
            print(followup_text, file=sys.stderr)
            sys.exit(1)

    digest["generated_at"] = datetime.now(timezone.utc).isoformat()

    # --- Pass 2: Verification ---
    # Pull Polygon prices to give the verifier a ground truth for math checks.
    polygon_prices = {}
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import polygon_data
        watchlist = []
        if os.path.exists(PREFS_PATH):
            with open(PREFS_PATH) as f:
                for line in f:
                    if line.lower().startswith("watchlist:"):
                        tickers = line.split(":", 1)[1].strip()
                        watchlist = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        # Also add any tickers from the digest itself
        for idea in digest.get("ideas", []):
            t = idea.get("ticker", "").upper()
            if t and t not in watchlist:
                watchlist.append(t)
        for ticker in watchlist:
            prev = polygon_data.fetch_previous_close(ticker)
            if prev and isinstance(prev, dict) and prev.get("close"):
                polygon_prices[ticker] = prev["close"]
            elif prev and isinstance(prev, (int, float)):
                polygon_prices[ticker] = prev
    except Exception as e:
        print(f"  Warning: could not fetch prices for verification ({e})", file=sys.stderr)

    print("Running verification pass...")
    digest = call_claude_verify(digest, polygon_prices=polygon_prices if polygon_prices else None)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(digest, f, indent=2)

    print(f"Digest written to {OUTPUT_PATH}")
    print(json.dumps(digest, indent=2))


if __name__ == "__main__":
    main()
