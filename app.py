"""
Transparent, Human-Approved OSINT Trading Agent
=================================================
For the Alpaca AI Trading Agents Hackathon (Options Alpha Agents track).

Flow:
  1) Gather OSINT (Alpaca News + SEC EDGAR)
  2) Generate a structured, auditable 'Decision Card' with Gemini
  3) Propose a defined-risk options strategy based on the signal (debit spread)
  4) NO order is ever submitted without human approval
  5) Every step is logged to the SQLite audit trail

To run:  streamlit run app.py
"""
import streamlit as st

from config import WATCHLIST, MAX_NOTIONAL_PER_TRADE
from osint.alpaca_news import fetch_recent_news
from osint.sec_edgar import fetch_material_events, fetch_insider_filings
from agent.market_context import get_recent_price_context
from agent.reasoning import build_decision_card
from agent.options_strategy import propose_debit_spread
from trading.executor import submit_debit_spread
from storage.audit_log import (
    init_db, save_decision_card, record_human_action,
    record_execution, get_full_audit_trail, verify_ledger,
)

st.set_page_config(page_title="Transparent OSINT Trading Agent", layout="wide")
init_db()

if "pending" not in st.session_state:
    st.session_state.pending = None  # {"card_id", "card", "strategy"}

st.title("Transparent & Human-Approved OSINT Options Agent")
st.caption(
    "Every decision is traceable down to its sources, its reasoning, and its confidence score. "
    "No order is ever submitted without your approval."
)

tab_signal, tab_audit = st.tabs(["New Signal", "Audit Trail"])

# --------------------------------------------------------------------------
# TAB 1: Generate a new signal
# --------------------------------------------------------------------------
with tab_signal:
    col_input, _ = st.columns([1, 2])
    with col_input:
        symbol = st.selectbox("Symbol", options=WATCHLIST, index=0)
        custom = st.text_input("...or enter a different symbol", "")
        if custom.strip():
            symbol = custom.strip().upper()

        if st.button("Collect OSINT and Analyze", type="primary"):
            with st.spinner(f"Collecting OSINT for {symbol} and running Gemini analysis..."):
                news_items = fetch_recent_news(symbol, lookback_hours=48, limit=8)
                filings = fetch_material_events(symbol, days_back=21) + \
                    fetch_insider_filings(symbol, days_back=21)
                price_ctx = get_recent_price_context(symbol)

                card = build_decision_card(symbol, news_items, filings, price_ctx)

                strategy = None
                if price_ctx.get("available") and card["sentiment"] in ("bullish", "bearish"):
                    strategy = propose_debit_spread(
                        symbol, card["sentiment"], price_ctx["last_close"]
                    )

                card_id = save_decision_card(card, strategy)
                st.session_state.pending = {"card_id": card_id, "card": card, "strategy": strategy}

    if st.session_state.pending:
        card = st.session_state.pending["card"]
        strategy = st.session_state.pending["strategy"]
        card_id = st.session_state.pending["card_id"]

        st.divider()
        sentiment_color = {"bullish": "green", "bearish": "red", "neutral": "gray"}[card["sentiment"]]
        st.subheader(f"Decision Card #{card_id} — {card['symbol']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Sentiment", card["sentiment"].upper())
        c2.metric("Confidence Score", f"{card['confidence_score']}/100")
        c3.metric("Already Priced In?", "Yes" if card["already_priced_in"] else "No")

        st.markdown(f"**Summary:** {card['event_summary']}")

        with st.expander("Reasoning Steps (for audit)"):
            for i, step in enumerate(card["reasoning_steps"], 1):
                st.markdown(f"{i}. {step}")

        opinions = card.get("analyst_opinions")
        if opinions:
            with st.expander("Analyst Perspectives (3 independent agents, before synthesis)", expanded=True):
                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    st.markdown("**📰 News Analyst**")
                    o = opinions["news"]
                    st.markdown(f"{o['sentiment'].upper()} · conf {o['confidence']}/100")
                    st.caption(o["reasoning"])
                with ac2:
                    st.markdown("**📄 Filings Analyst**")
                    o = opinions["filings"]
                    st.markdown(f"{o['sentiment'].upper()} · conf {o['confidence']}/100")
                    st.caption(f"Insider activity: {o['insider_direction']}. {o['reasoning']}")
                with ac3:
                    st.markdown("**📈 Price Analyst**")
                    o = opinions["price"]
                    st.markdown(f"{o['momentum_bias'].upper()} · conf {o['confidence']}/100")
                    st.caption(o["reasoning"])
                sentiments = {opinions["news"]["sentiment"], opinions["filings"]["sentiment"],
                              opinions["price"]["momentum_bias"]}
                if len(sentiments) > 1:
                    st.warning("⚠️ The three analysts did not fully agree — see the Critic's synthesis below for how this was resolved.")
                else:
                    st.success("✅ All three analysts independently agreed.")

        if card["risk_flags"]:
            st.warning("Risk Flags: " + "; ".join(card["risk_flags"]))

        with st.expander("Sources (OSINT)"):
            sources = card.get("sources", {})
            for n in sources.get("news", []):
                st.markdown(f"- [{n['headline']}]({n['url']}) — {n.get('source', '')}")
            for f in sources.get("filings", []):
                st.markdown(f"- {f['form']} ({f.get('filed_at', '')}) — [{f['company']}]({f['url']})")
            st.json(sources.get("price_context", {}))

        st.divider()

        if strategy:
            st.markdown(f"### Proposed Strategy: {strategy['strategy_name']}")
            for leg in strategy["legs"]:
                st.markdown(f"- **{leg['action'].upper()}** {leg['type']} @ strike {leg['strike']} ({leg['symbol']})")
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Max loss per contract", f"${strategy['max_loss_per_contract']:.2f}")
            sc2.metric("Max gain per contract", f"${strategy['max_gain_per_contract']:.2f}")
            sc3.metric("Breakeven", f"${strategy['breakeven']:.2f}")

            qty = st.number_input(
                "Contract quantity", min_value=1, max_value=20, value=strategy["quantity_suggested"]
            )
            est_risk = strategy["max_loss_per_contract"] * qty
            st.caption(f"Estimated total risk: ${est_risk:.2f} (limit: ${MAX_NOTIONAL_PER_TRADE:.2f})")

            b1, b2 = st.columns(2)
            if b1.button("✅ Approve and Submit to Paper Account", type="primary"):
                result = submit_debit_spread(strategy, quantity=qty)
                if result["submitted"]:
                    record_human_action(card_id, "approve", f"qty={qty}")
                    record_execution(card_id, result, qty)
                    st.success(f"Order submitted. Order ID: {result['order_id']} (status: {result['status']})")
                else:
                    record_human_action(card_id, "approve_blocked", f"qty={qty} - {result['reason']}")
                    st.error(result["reason"])
                st.session_state.pending = None

            note = b2.text_input("Rejection reason (optional)", key="reject_note")
            if b2.button("❌ Reject"):
                record_human_action(card_id, "reject", note)
                st.info("Decision rejected and logged to the audit trail. No order was submitted.")
                st.session_state.pending = None
        else:
            st.info(
                "This simple strategy set proposes no trade because sentiment is 'neutral' "
                "or price data is unavailable. The decision was still logged to the audit trail."
            )
            if st.button("Acknowledge (no trade, log only)"):
                record_human_action(card_id, "acknowledge", "")
                st.session_state.pending = None

# --------------------------------------------------------------------------
# TAB 2: Audit trail
# --------------------------------------------------------------------------
with tab_audit:
    st.subheader("Full Audit Trail")
    st.caption("Immutable record of the Source -> Analysis -> Human Decision -> Order chain.")

    if st.button("🔒 Verify Ledger Integrity"):
        result = verify_ledger()
        if result["valid"]:
            st.success(
                f"Ledger intact: {result['entries']} hash-chained entries verified, "
                f"chain head `{result['last_hash'][:16]}...`."
            )
        else:
            st.error(f"Ledger tampered! Chain breaks at entry #{result['broken_at_id']} ({result['entry_type']}).")

    trail = get_full_audit_trail()
    if not trail:
        st.info("No decisions logged yet.")
    for entry in trail:
        c = entry["card"]
        with st.container(border=True):
            st.markdown(
                f"**#{c['id']} · {c['symbol']} · {c['sentiment'].upper()} · "
                f"confidence {c['confidence_score']}/100** — _{c['created_at']}_"
            )
            st.markdown(c["event_summary"])
            if entry["actions"]:
                for a in entry["actions"]:
                    st.markdown(f"→ Human action: **{a['action']}** ({a['acted_at']}) {a.get('note') or ''}")
            else:
                st.markdown("→ No human action yet (pending).")
            for e in entry["executions"]:
                st.markdown(
                    f"→ Order submitted: `{e['order_id']}` status={e['status']} "
                    f"qty={e['quantity']} limit=${e['limit_price']}"
                )
