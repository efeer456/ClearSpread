# Transparent, Human-Approved OSINT Options Agent

**Alpaca AI Trading Agents Hackathon (lablab.ai) — Options Alpha Agents track**

## Tagline

An options trading agent that never trades — it *proposes*, with receipts. Every recommendation is a fully-sourced, auditable Decision Card, and no order reaches the market without an explicit human approval click.

## The problem with "autonomous" trading agents

Most agents in this space follow the same loop: pull a headline, let an LLM interpret it, fire an order. That's fast, but it's a black box — when the trade goes wrong (or right), nobody can point to *why* the agent believed what it believed, and there's no brake between "the model said bullish" and real capital moving.

## Our approach

This agent is built around one constraint we never relaxed: **transparency and a human in the loop outrank speed.**

1. **Sourced OSINT, not vibes.** Every signal is built from real Alpaca News headlines and real SEC EDGAR filings (Form 4 insider activity, 8-K material events) — not a generic web search, and never fabricated or paraphrased into a claim the source doesn't support.
2. **Structured, auditable reasoning.** Gemini is forced (via structured function-calling, `tool_config` mode=ANY) to emit a fixed-schema "Decision Card": event summary, sentiment, a 0–100 confidence score, an explicit "already priced in?" check against recent price/volume action, step-by-step reasoning, and risk flags. No free-text hand-waving — every card looks the same and can be checked the same way.
3. **Defined-risk only.** The strategy engine proposes debit call/put spreads exclusively. Max loss is known before the trade is ever shown to the user; naked/undefined-risk option selling is intentionally not supported, by design, not by omission.
4. **Approval is a hard gate, not a formality.** `trading/executor.py` — the only code path that can touch the live order book — is never called except from the UI's Approve button, after a human has seen the full card and the strategy's max loss/gain/breakeven. A configurable `MAX_NOTIONAL_PER_TRADE` safety guard blocks oversized orders even after approval.
5. **Nothing disappears.** Every step — source, decision, human action (approve / reject / blocked-by-guard), and resulting order — is written to an append-only SQLite audit trail and rendered as a timeline in the app's "Audit Trail" tab. A rejected or safety-blocked decision is logged exactly as durably as an executed one.

## Architecture

```
osint/alpaca_news.py     -> Alpaca NewsClient, per-ticker headlines
osint/sec_edgar.py       -> SEC EDGAR full-text search (Form 4 / 8-K)
alpaca_cli.py            -> subprocess wrapper around Alpaca's official CLI (alpacahq/cli)
agent/market_context.py  -> recent price/volume via Alpaca CLI (`data bars`)
agent/reasoning.py       -> Gemini, forced function-call -> structured Decision Card
agent/options_strategy.py-> sentiment -> defined-risk debit spread via Alpaca CLI (`data option chain`)
trading/executor.py      -> ONLY called post-approval: Alpaca CLI (`order submit --order-class mleg`)
storage/audit_log.py     -> SQLite: decision + human action + execution, immutable
app.py                   -> Streamlit UI (Approve/Reject + Audit Trail tab)
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
- A real Decision Card generated end-to-end from live Alpaca News + SEC EDGAR data for AAPL (bullish, confidence 55/100, correctly flagging thin volume as a risk).
- A real defined-risk order — AAPL Call Debit Spread, long 327.5C / short 337.5C, exp. 2026-09-18, $373 max loss, $627 max gain — submitted as a live MLEG order on the paper account and confirmed `NEW` on the exchange. (This first order predates the CLI migration below and went out through the SDK; the codebase now submits exclusively through the Alpaca CLI, verified separately via `order submit --order-class mleg --dry-run` against the same live account.)
- The full chain (source → Decision Card → human approval → live order) recorded in the audit trail and verified queryable end-to-end.
- Bugs that only live testing caught and that are now fixed: an `alpaca-py` field rename (`NewsSet`), a SIP-feed entitlement 403 (fixed by forcing `DataFeed.IEX`), and a logic bug where spread legs could be picked across different expirations (now hard-constrained to a single target expiry).

## Demo script (for judges / video)

1. Start on the **Audit Trail** tab — empty, to show there's no hidden state.
2. Pick a symbol, click **"OSINT Topla ve Analiz Et"** — a Decision Card appears live: sentiment, confidence score, "already priced in?", step-by-step reasoning, risk flags, and the actual sourced headlines/filings it was built from.
3. Show the proposed debit spread: legs, max loss, max gain, breakeven — all computed before any approval is possible.
4. Click **Approve** — the order goes out on the paper account; **Reject** would instead log the rejection with zero market impact.
5. Switch to **Audit Trail** — the full source → analysis → human decision → order chain is now visible as an immutable timeline.
6. Closing line: *"This agent never touches the market without your click — and every step it takes is auditable after the fact."*

## Known limitations (2-day hackathon scope)

- Strategy set is debit call/put spreads only; credit spreads/iron condors are a natural next step.
- SEC EDGAR full-text search matches by company name (that's how the public API works), not a proper CIK filter — correct in practice for the tickers tested, but a known simplification.

## Tech stack

Python, Streamlit, Alpaca's official CLI (`github.com/alpacahq/cli`, for all market data + paper trading execution), `alpaca-py` (OSINT news only), Google Gemini (`google-genai`, forced structured function-calling), SEC EDGAR full-text search API, SQLite.
