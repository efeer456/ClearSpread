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
import json

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
def _loads(raw):
    """DB'deki JSON kolonlarini cozer; bos/bozuk kayitta None doner."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


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
            def _reviewer_badge(o):
                r = o.get("_reviewer", {})
                if r.get("status") == "approved" and r.get("revisions", 0) > 0:
                    return f"🔁 reviewer requested {r['revisions']} revision(s)"
                if r.get("status") == "skipped":
                    return "⏭️ no data, reviewer skipped"
                return "✅ passed reviewer on first try"

            with st.expander("Analyst Perspectives (3 independent agents, before synthesis)", expanded=True):
                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    st.markdown("**📰 News Analyst**")
                    o = opinions["news"]
                    st.markdown(f"{o['sentiment'].upper()} · conf {o['confidence']}/100")
                    st.caption(o["reasoning"])
                    st.caption(_reviewer_badge(o))
                with ac2:
                    st.markdown("**📄 Filings Analyst**")
                    o = opinions["filings"]
                    st.markdown(f"{o['sentiment'].upper()} · conf {o['confidence']}/100")
                    st.caption(f"Insider activity: {o['insider_direction']}. {o['reasoning']}")
                    st.caption(_reviewer_badge(o))
                with ac3:
                    st.markdown("**📈 Price Analyst**")
                    o = opinions["price"]
                    st.markdown(f"{o['momentum_bias'].upper()} · conf {o['confidence']}/100")
                    st.caption(o["reasoning"])
                    st.caption(_reviewer_badge(o))
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

            # Karar verildikten sonra kart ekranda KALIR (sadece butonlar kalkar).
            # Onceden pending sifirlandigi icin kart, risk flag'leri ve strateji
            # aninda yok oluyordu; kullanici neyi onayladigini goremiyordu.
            decided = st.session_state.pending.get("decided")
            if decided:
                {"success": st.success, "error": st.error, "info": st.info}[decided["kind"]](decided["text"])
            else:
                b1, b2 = st.columns(2)
                if b1.button("✅ Approve and Submit to Paper Account", type="primary"):
                    result = submit_debit_spread(strategy, quantity=qty)
                    if result["submitted"]:
                        record_human_action(card_id, "approve", f"qty={qty}")
                        record_execution(card_id, result, qty)
                        st.session_state.pending["decided"] = {
                            "kind": "success",
                            "text": (f"Order submitted. Order ID: {result['order_id']} "
                                     f"(status: {result['status']})"),
                        }
                    else:
                        record_human_action(card_id, "approve_blocked", f"qty={qty} - {result['reason']}")
                        st.session_state.pending["decided"] = {"kind": "error", "text": result["reason"]}
                    st.rerun()

                note = b2.text_input("Rejection reason (optional)", key="reject_note")
                if b2.button("❌ Reject"):
                    record_human_action(card_id, "reject", note)
                    st.session_state.pending["decided"] = {
                        "kind": "info",
                        "text": "Decision rejected and logged to the audit trail. No order was submitted.",
                    }
                    st.rerun()
        else:
            st.info(
                "This simple strategy set proposes no trade because sentiment is 'neutral' "
                "or price data is unavailable. The decision was still logged to the audit trail."
            )
            decided = st.session_state.pending.get("decided")
            if decided:
                st.info(decided["text"])
            elif st.button("Acknowledge (no trade, log only)"):
                record_human_action(card_id, "acknowledge", "")
                st.session_state.pending["decided"] = {
                    "kind": "info",
                    "text": "Acknowledged. Logged to the audit trail, no order submitted.",
                }
                st.rerun()

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

            # Karar kartinin TAMAMI burada gorunmeli - risk flag'leri, analist
            # gorusleri ve onerilen strateji DB'de zaten duruyor; ozet satirini
            # gostermek 'her adim denetlenebilir' vaadini karsilamiyor.
            risk_flags = _loads(c.get("risk_flags")) or []
            if risk_flags:
                st.warning("Risk Flags: " + "; ".join(risk_flags))

            opinions = _loads(c.get("analyst_opinions")) or {}
            if opinions:
                with st.expander("Analyst Perspectives (3 independent agents)"):
                    for label, key, bias_field in (
                        ("News Analyst", "news", "sentiment"),
                        ("Filings Analyst", "filings", "sentiment"),
                        ("Price Analyst", "price", "momentum_bias"),
                    ):
                        o = opinions.get(key) or {}
                        bias = (o.get(bias_field) or "n/a").upper()
                        st.markdown(f"**{label}** — {bias} · conf {o.get('confidence', 'n/a')}/100")
                        st.caption(o.get("reasoning", ""))

            steps = _loads(c.get("reasoning_steps")) or []
            if steps:
                with st.expander("Reasoning Steps"):
                    for i, step in enumerate(steps, 1):
                        st.markdown(f"{i}. {step}")

            strat = _loads(c.get("strategy"))
            if strat:
                with st.expander(f"Proposed Strategy: {strat['strategy_name']}"):
                    for leg in strat["legs"]:
                        st.markdown(
                            f"- **{leg['action'].upper()}** {leg['type']} @ strike "
                            f"{leg['strike']} ({leg['symbol']})"
                        )
                    st.markdown(
                        f"Max loss **${strat['max_loss_per_contract']:.2f}** · "
                        f"max gain **${strat['max_gain_per_contract']:.2f}** · "
                        f"breakeven **${strat['breakeven']:.2f}**"
                    )
            else:
                st.caption("No strategy proposed (neutral sentiment or no price data).")

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
