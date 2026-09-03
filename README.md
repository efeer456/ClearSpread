# Transparent, Human-Approved OSINT Options Agent

For the **Alpaca AI Trading Agents Hackathon** (lablab.ai) — *Options Alpha Agents* track.

## Idea

Most teams build "pull a headline → let the agent interpret it → auto-trade" pipelines.
This project deliberately stands somewhere else: **auditability over speed**.

- Three **independent analyst agents** (News, SEC Filings, Price/Momentum) each judge
  the same symbol from only their own slice of the data — they never see each other's
  output. A **Critic agent** then synthesizes their opinions into one **Decision Card**,
  and is required to explicitly call out any disagreement between analysts (e.g. bullish
  news vs. insiders selling) as a risk flag, instead of silently averaging it away.
- The agent never submits an order on its own. No options strategy is ever executed
  until the user clicks **Approve**.
- Only **defined-risk** strategies are proposed (debit call/put spreads) — max loss is
  known up front; "naked" option selling is not supported.
- Every step (source → analysis → human decision → order) is logged to a
  **hash-chained, tamper-evident SQLite ledger** and rendered as a timeline in the
  "Audit Trail" tab, which includes a one-click integrity check.

## Architecture

```
osint/alpaca_news.py     -> ticker-scoped headlines via Alpaca's NewsClient
osint/sec_edgar.py       -> SEC EDGAR full-text search (Form 4 / 8-K)
alpaca_cli.py            -> subprocess wrapper around Alpaca's official CLI (github.com/alpacahq/cli)
agent/market_context.py  -> recent price/volume for "already priced in?" checks (Alpaca CLI: data bars)
agent/reasoning.py       -> 3 independent Analyst agents (News/Filings/Price) + 1 Critic
                             agent that synthesizes them into a structured Decision Card
                             (Gemini, forced function-calling, never free text)
agent/options_strategy.py-> sentiment -> defined-risk debit spread (Alpaca CLI: data option chain)
trading/executor.py      -> ONLY called post-approval: Alpaca CLI (order submit --order-class mleg)
storage/audit_log.py     -> SQLite: decision + human action + execution history, plus a
                             SHA-256 hash-chained `ledger` table for tamper-evidence
app.py                   -> Streamlit UI (Approve/Reject + Audit Trail tab + ledger verify)
```

Per the hackathon's rules (use of Alpaca's MCP server or CLI is mandatory), the entire
trading flow — market data and order submission included — goes through Alpaca's
official **CLI** via subprocess calls (`alpaca_cli.py`) instead of the raw `alpaca-py`
SDK. `alpaca-py` is only used in `osint/alpaca_news.py` to fetch headlines (the OSINT
layer, not the trading layer).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your own keys
streamlit run app.py
```

Keys you'll need:
- **Alpaca paper trading** API key/secret (dashboard → Paper Trading → API Keys).
  Your account needs options trading level approved for options orders to work.
- **Gemini API key** (aistudio.google.com/apikey)
- SEC EDGAR needs no key, just a real contact string (`SEC_EDGAR_USER_AGENT`) per
  their fair-access policy.

You'll also need the **Alpaca CLI** installed:
```bash
go install github.com/alpacahq/cli/cmd/alpaca@latest   # or: brew install alpacahq/tap/cli
```
If it's on your PATH, `ALPACA_CLI_PATH=alpaca` in `.env` is enough; otherwise give the
full path (prebuilt Windows binary: [GitHub Releases](https://github.com/alpacahq/cli/releases)).

## Known limitations (2-day hackathon scope)

- The strategy set is currently **debit call/put spreads only**. Iron condors, credit
  spreads, etc. could be added to `agent/options_strategy.py` given more time.
- SEC EDGAR search matches by company name rather than ticker symbol (that's how the
  full-text search API works); the ticker → company-name mapping is kept simple and
  could be strengthened with `company_tickers.json`.
- ~~Stretch goal: MCP/CLI integration~~ — done: all trading/data calls now go through
  the official Alpaca CLI instead of the `alpaca-py` SDK (`alpaca_cli.py`).

## Demo flow (for judges)

1. Start with the "Audit Trail" tab empty.
2. Pick a symbol, click "Collect OSINT and Analyze" → three analyst opinions appear
   (News/Filings/Price), each independently sourced — point out when they disagree
   and how the Critic's synthesis explicitly resolves it as a risk flag.
3. Review the proposed strategy, adjust the contract quantity.
4. Click Approve or Reject → show the result in the "Audit Trail" tab.
5. Click "Verify Ledger Integrity" → the hash chain is recomputed live and confirmed intact.
6. Closing line: *"This agent never touches the market without your approval — and
   every step it takes is auditable, and verifiably tamper-evident, after the fact."*
