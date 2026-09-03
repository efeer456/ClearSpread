# Transparent, Human-Approved OSINT Options Agent

**Alpaca AI Trading Agents Hackathon (lablab.ai) — Options Alpha Agents track**

## Tagline

An options trading agent that never trades alone — three independent analysts argue, a critic reconciles them, and a human clicks the only button that can touch the market. Every step is a fully-sourced, hash-chained receipt.

## Where we actually differ

"Transparent, human-approved, defined-risk" is table stakes in this hackathon — most serious entries claim some version of it. We looked at what that claim usually *doesn't* include and built those parts instead:

1. **Real multi-agent disagreement, not one model asked to sound thorough.** Three separate Gemini calls — a News analyst, an SEC Filings analyst, a Price/Momentum analyst — each see *only* their own slice of the data and never each other's output. A fourth Critic agent is handed all three opinions and is required to name any disagreement explicitly (e.g. bullish headlines vs. insiders selling) as a risk flag, not average it away. In live testing this isn't hypothetical: on one real AAPL run the News analyst came back bearish (litigation headlines), Filings came back neutral (routine insider selling), and Price came back bullish (a quiet 5-day drift) — the Critic caught the conflict, named it in `risk_flags`, and synthesized a conservative bearish call at 62/100 confidence instead of just averaging three numbers together.
2. **A hash-chained ledger, not just an "audit log" in name.** Every decision, human action, and execution is appended to a SQLite `ledger` table where each row's SHA-256 hash covers the previous row's hash plus its own payload. The app has a one-click "Verify Ledger Integrity" button that recomputes the whole chain live and reports exactly where it breaks if anything was ever edited out-of-band. This is a real, checkable tamper-evidence property, not a label on an ordinary table.
3. **Defined-risk only, and proven live twice, through two different execution paths.** The strategy engine proposes debit call/put spreads exclusively — max loss known up front, no naked option selling. We didn't just claim this works: we submitted two real live MLEG orders on a fresh, hackathon-dedicated paper account, first through `alpaca-py`, then — after migrating for the MCP/CLI requirement — a second real order through Alpaca's official CLI, both confirmed on the exchange with real order IDs (below).
4. **Approval is a hard gate, not a formality.** `trading/executor.py` — the only code path that can touch the live order book — is never called except from the UI's Approve button. A configurable `MAX_NOTIONAL_PER_TRADE` guard blocks oversized orders even post-approval, and a guard-blocked approval is logged into the same hash chain as an executed one — nothing quietly disappears.

## Architecture

```
osint/alpaca_news.py     -> Alpaca NewsClient, per-ticker headlines
osint/sec_edgar.py       -> SEC EDGAR full-text search (Form 4 / 8-K)
alpaca_cli.py            -> subprocess wrapper around Alpaca's official CLI (alpacahq/cli)
agent/market_context.py  -> recent price/volume via Alpaca CLI (`data bars`)
agent/reasoning.py       -> 3 independent Analyst agents (News/Filings/Price, run concurrently,
                             each forced structured function-calling) + 1 Critic agent that
                             synthesizes them into the final Decision Card
agent/options_strategy.py-> sentiment -> defined-risk debit spread via Alpaca CLI (`data option chain`)
trading/executor.py      -> ONLY called post-approval: Alpaca CLI (`order submit --order-class mleg`)
storage/audit_log.py     -> SQLite: decision + human action + execution, PLUS a SHA-256
                             hash-chained `ledger` table (tamper-evident, verifiable on demand)
app.py                   -> Streamlit UI (3-analyst panel, Approve/Reject, Audit Trail + ledger verify)
```

**Alpaca CLI, not just the raw SDK.** Every market-data and order-execution call in the
trading path goes through Alpaca's official CLI (`github.com/alpacahq/cli`) via subprocess —
not the `alpaca-py` Python SDK directly. `alpaca-py` is used only in the OSINT layer
(`osint/alpaca_news.py`) to pull headlines; the actual agent decision-to-execution path is
CLI-driven end to end (account lookup, option chain snapshots, price bars, and multi-leg
order submission).

## Proven live, not just imported

Every module was run against real credentials, not just syntax-checked:

- Fresh Alpaca paper trading account opened specifically for this hackathon: **account ID `94110f66-070a-46c8-b5aa-f19532d029b6`** (`PA3JDEHU8POM`), starting balance $100,000, options trading **level 3 approved** (verified live via `alpaca account get`).
- Two real defined-risk orders submitted end-to-end on that account, through two different execution paths:
  - `4d043b23-778c-45fe-ad4f-cbbdaf28400b` — AAPL Call Debit Spread (long 327.5C / short 337.5C, exp. 2026-09-18, $373 max loss / $627 max gain), submitted via the `alpaca-py` SDK, confirmed `NEW`.
  - `bad9115c-7ad4-4078-b262-bcca74ff761c` — same structure, submitted after migrating to the Alpaca CLI (`order submit --order-class mleg`), confirmed `pending_new`. This is the path the current codebase uses exclusively.
- A real multi-agent Decision Card run on AAPL where the three analysts genuinely disagreed: News came back bearish on litigation headlines (78/100 confidence), Filings came back neutral on routine insider selling (75/100), Price came back bullish on a quiet 5-day drift (70/100). The Critic named the conflict explicitly in `risk_flags` and synthesized a bearish call at 62/100 — not a hypothetical, an actual run.
- The hash-chained ledger verified live via `verify_ledger()` after real writes — chain intact, head hash matched a fresh recomputation from row 1.
- The full chain (source → 3 analyst opinions → Critic synthesis → human approval → live order) recorded in the audit trail and verified queryable end-to-end.
- Bugs that only live testing caught and that are now fixed: an `alpaca-py` field rename (`NewsSet`), a SIP-feed entitlement 403 (fixed by forcing `DataFeed.IEX`), a logic bug where spread legs could be picked across different expirations (now hard-constrained to a single target expiry), and transient Gemini 503 "high demand" errors (now handled with automatic retry inside `agent/reasoning.py` itself, not just in test scripts).

## Demo script (for judges / video)

1. Start on the **Audit Trail** tab — empty, to show there's no hidden state.
2. Pick a symbol, click **"Collect OSINT and Analyze"** — three independent analyst
   opinions appear (News / Filings / Price), then the synthesized Decision Card. If they
   disagree, point at the risk flag where the Critic names it explicitly.
3. Show the proposed debit spread: legs, max loss, max gain, breakeven — all computed
   before any approval is possible.
4. Click **Approve** — the order goes out on the paper account through the Alpaca CLI;
   **Reject** would instead log the rejection with zero market impact.
5. Switch to **Audit Trail**, click **"Verify Ledger Integrity"** — the hash chain is
   recomputed live and confirmed intact.
6. Closing line: *"Three agents argue, one reconciles them, and only a human can pull
   the trigger — and every step is auditable, and provably untampered, after the fact."*

## Known limitations (2-day hackathon scope)

- Strategy set is debit call/put spreads only; credit spreads/iron condors are a natural next step.
- SEC EDGAR full-text search matches by company name (that's how the public API works), not a proper CIK filter — correct in practice for the tickers tested, but a known simplification.
- The 3-analyst + critic pipeline is 4 sequential/parallel Gemini calls per signal (~15-20s observed live) rather than 1; acceptable for this use case (a human is about to spend minutes reviewing the card anyway) but a real latency cost of the multi-agent design.

## Tech stack

Python, Streamlit, Alpaca's official CLI (`github.com/alpacahq/cli`, for all market data + paper trading execution), `alpaca-py` (OSINT news only), Google Gemini (`google-genai`, forced structured function-calling across 4 concurrent/sequential agent calls per signal), SEC EDGAR full-text search API, SQLite with a SHA-256 hash-chained ledger.
