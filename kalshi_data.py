"""
kalshi_data.py — pull Fed / CPI odds from Kalshi's public API for the morning digest.

No API key needed: Kalshi's market-data endpoints are public reads.
Mirrors polygon_data.py: expose build_kalshi_context() which returns a text block
(or "" on failure) that generate_digest.py injects into the Claude prompt.

Standalone test:
    cd ~/morning-digest && python3 kalshi_data.py
"""

import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
TIMEOUT = 15

# Series to pull. Order = display order in the digest.
#   KXFEDDECISION : hike / hold / cut at the next FOMC meeting
#   KXFED         : fed funds target range after the meeting (rate buckets)
#   KXCPI         : monthly headline CPI print (m/m buckets)
SERIES = [
    ("KXFEDDECISION", "Next FOMC decision"),
    ("KXFED",         "Fed funds range after meeting"),
    ("KXCPI",         "Next CPI print"),
    ("KXPCECORE",     "Core PCE"),
]

MAX_MARKETS_PER_EVENT = 6   # keep the prompt tight; buckets below this are noise
MIN_EVENT_VOLUME = 1000     # open-interest contracts; below this the price is not a real signal


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _get(path, params=None):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "morning-digest/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_open_events(series_ticker):
    """Return open events (with nested markets) for a series, soonest-closing first."""
    data = _get("/events", {
        "series_ticker": series_ticker,
        "status": "open",
        "with_nested_markets": "true",
        "limit": 50,
    })
    events = data.get("events", []) or []

    def close_key(ev):
        # Use the earliest close_time among the event's markets
        times = [m.get("close_time") for m in ev.get("markets", []) if m.get("close_time")]
        return min(times) if times else "9999"

    return sorted(events, key=close_key)


# ---------------------------------------------------------------------------
# Price helpers — Kalshi has been migrating from integer cents to dollar strings,
# so handle both shapes.
# ---------------------------------------------------------------------------

def _cents(market, key):
    """Return a price in cents (0-100) from either `key` (cents) or `key_dollars`."""
    v = market.get(key)
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    v = market.get(f"{key}_dollars")
    if v is not None:
        try:
            return float(v) * 100.0
        except (TypeError, ValueError):
            pass
    return None


def implied_probability(market):
    """Best estimate of YES probability in [0, 1]. Mid of bid/ask, else last trade."""
    bid = _cents(market, "yes_bid")
    ask = _cents(market, "yes_ask")
    if bid is not None and ask is not None and ask >= bid and ask > 0:
        return (bid + ask) / 200.0
    last = _cents(market, "last_price")
    if last is not None:
        return last / 100.0
    return None


def _volume(market):
    """Contracts. Kalshi moved to *_fp string fields; try every shape, fall back to open interest."""
    for key in ("volume_fp", "volume", "open_interest_fp", "open_interest"):
        v = market.get(key)
        if v is not None:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                continue
    return 0


def _label(market):
    # Prefer the short YES bucket label; fall back through the other shapes Kalshi uses.
    for key in ("yes_sub_title", "subtitle", "title"):
        v = market.get(key)
        if v:
            return v
    no_lbl = market.get("no_sub_title")
    if no_lbl:
        return f"NOT [{no_lbl}]"
    if market.get("floor_strike") is not None:
        return f"strike {market['floor_strike']}"
    return market.get("ticker", "?")


def _fmt_close(iso):
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%b %d")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def summarize_event(event, label):
    """Render one event as a short text block. Returns None if too thin to trust."""
    markets = event.get("markets", []) or []
    rows = []
    for m in markets:
        p = implied_probability(m)
        if p is None:
            continue
        rows.append((p, _label(m), _volume(m), m.get("close_time")))
    if not rows:
        return None

    total_vol = sum(r[2] for r in rows)
    if total_vol < MIN_EVENT_VOLUME:
        return None

    rows.sort(key=lambda r: r[0], reverse=True)
    close = _fmt_close(rows[0][3])
    title = event.get("title", "").strip()

    lines = [f"{label}: {title}" + (f" (closes {close})" if close else "")]
    for p, name, vol, _ in rows[:MAX_MARKETS_PER_EVENT]:
        if p < 0.02:
            continue  # tail buckets add nothing
        lines.append(f"  {p*100:5.1f}%  {name}  [vol {vol:,}]")
    lines.append(f"  total volume: {total_vol:,} contracts")
    return "\n".join(lines)


def build_kalshi_context():
    """
    Build the prompt block. Returns "" if nothing usable so the digest still runs.
    Never raises — the caller already wraps in try/except, but be defensive anyway.
    """
    blocks = []
    for series, label in SERIES:
        try:
            events = fetch_open_events(series)
        except Exception as e:
            print(f"  Warning: Kalshi fetch failed for {series}: {e}", file=sys.stderr)
            continue
        for ev in events:
            block = summarize_event(ev, label)
            if block:
                blocks.append(block)
                break  # only the soonest-expiring liquid event per series

    if not blocks:
        return ""

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"=== KALSHI PREDICTION MARKET ODDS (fetched {stamp}) ==="
    footer = ("=== END KALSHI ===\n"
              "Note: Kalshi macro markets (Fed, CPI) are well calibrated near resolution; "
              "treat these as a fast summary of rate expectations, roughly equivalent to "
              "fed funds futures. Cite them as 'Kalshi implies X%' — do not present them "
              "as independent evidence beyond what futures already show.")
    return "\n".join([header, *blocks, footer])


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    out = build_kalshi_context()
    if out:
        print(out)
    else:
        print("No Kalshi data returned (network, series names, or all events too thin).")
        sys.exit(1)
