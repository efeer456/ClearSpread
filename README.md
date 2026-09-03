# Transparent, Human-Approved OSINT Options Agent

For the **Alpaca AI Trading Agents Hackathon** (lablab.ai) — *Options Alpha Agents* track.

## Idea

Most teams build "pull a headline → let the agent interpret it → auto-trade" pipelines.
This project deliberately stands somewhere else: **auditability over speed**.

- Every decision is produced as a **"Decision Card"** that clearly shows which OSINT
  sources it's based on (Alpaca News + SEC EDGAR Form 4/8-K filings), what reasoning
  steps were followed, and what confidence score it got.
- The agent never submits an order on its own. No options strategy is ever executed
  until the user clicks **Approve**.
- Only **defined-risk** strategies are proposed (debit call/put spreads) — max loss is
  known up front; "naked" option selling is not supported.
- Every step (source → analysis → human decision → order) is logged immutably to
  SQLite and rendered as a timeline in the "Audit Trail" tab.

## Architecture

```
osint/alpaca_news.py     -> ticker-scoped headlines via Alpaca's NewsClient
osint/sec_edgar.py       -> SEC EDGAR full-text search (Form 4 / 8-K)
alpaca_cli.py            -> subprocess wrapper around Alpaca's official CLI (github.com/alpacahq/cli)
agent/market_context.py  -> recent price/volume for "already priced in?" checks (Alpaca CLI: data bars)
agent/reasoning.py       -> Gemini, forced function-call -> structured Decision Card
agent/options_strategy.py-> sentiment -> defined-risk debit spread (Alpaca CLI: data option chain)
trading/executor.py      -> ONLY called post-approval: Alpaca CLI (order submit --order-class mleg)
storage/audit_log.py     -> SQLite: decision + human action + execution history
app.py                   -> Streamlit UI (Approve/Reject + Audit Trail tab)
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
2. Pick a symbol, click "Collect OSINT and Analyze" → a Decision Card appears on
   screen with its sources, reasoning steps, and confidence score.
3. Review the proposed strategy, adjust the contract quantity.
4. Click Approve or Reject → show the result in the "Audit Trail" tab.
5. Closing line: *"This agent never touches the market without your approval — and
   every step it takes is auditable after the fact."*
