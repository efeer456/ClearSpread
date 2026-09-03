"""
Seffaf, Insan-Onayli OSINT Trading Agent
=========================================
Alpaca AI Trading Agents Hackathon (Options Alpha Agents track) icin.

Akis:
  1) OSINT topla (Alpaca News + SEC EDGAR)
  2) Gemini ile yapisal, denetlenebilir bir 'Karar Karti' uret
  3) Sinyale gore tanimli-riskli bir opsiyon stratejisi oner (debit spread)
  4) Insan onayi olmadan HICBIR emir gonderilmez
  5) Her adim SQLite denetim izine (audit trail) kaydedilir

Calistirmak icin:  streamlit run app.py
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
    record_execution, get_full_audit_trail,
)

st.set_page_config(page_title="Seffaf OSINT Trading Agent", layout="wide")
init_db()

if "pending" not in st.session_state:
    st.session_state.pending = None  # {"card_id", "card", "strategy"}

st.title("Seffaf & Insan-Onayli OSINT Opsiyon Ajani")
st.caption(
    "Her karar; kaynagina, akil yurutmesine ve guven skoruna kadar izlenebilir. "
    "Hicbir emir, siz onaylamadan gonderilmez."
)

tab_signal, tab_audit = st.tabs(["Yeni Sinyal", "Denetim Izi"])

# --------------------------------------------------------------------------
# TAB 1: Yeni sinyal uret
# --------------------------------------------------------------------------
with tab_signal:
    col_input, _ = st.columns([1, 2])
    with col_input:
        symbol = st.selectbox("Sembol", options=WATCHLIST, index=0)
        custom = st.text_input("...veya baska bir sembol gir", "")
        if custom.strip():
            symbol = custom.strip().upper()

        if st.button("OSINT Topla ve Analiz Et", type="primary"):
            with st.spinner(f"{symbol} icin OSINT toplaniyor ve Gemini analiz ediyor..."):
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
        st.subheader(f"Karar Karti #{card_id} — {card['symbol']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Sentiment", card["sentiment"].upper())
        c2.metric("Guven Skoru", f"{card['confidence_score']}/100")
        c3.metric("Fiyata Yansimis mi?", "Evet" if card["already_priced_in"] else "Hayir")

        st.markdown(f"**Ozet:** {card['event_summary']}")

        with st.expander("Akil Yurutme Adimlari (denetim icin)"):
            for i, step in enumerate(card["reasoning_steps"], 1):
                st.markdown(f"{i}. {step}")

        if card["risk_flags"]:
            st.warning("Risk Bayraklari: " + "; ".join(card["risk_flags"]))

        with st.expander("Kaynaklar (OSINT)"):
            sources = card.get("sources", {})
            for n in sources.get("news", []):
                st.markdown(f"- [{n['headline']}]({n['url']}) — {n.get('source', '')}")
            for f in sources.get("filings", []):
                st.markdown(f"- {f['form']} ({f.get('filed_at', '')}) — [{f['company']}]({f['url']})")
            st.json(sources.get("price_context", {}))

        st.divider()

        if strategy:
            st.markdown(f"### Onerilen Strateji: {strategy['strategy_name']}")
            for leg in strategy["legs"]:
                st.markdown(f"- **{leg['action'].upper()}** {leg['type']} @ strike {leg['strike']} ({leg['symbol']})")
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Kontrat basi max kayip", f"${strategy['max_loss_per_contract']:.2f}")
            sc2.metric("Kontrat basi max kazanc", f"${strategy['max_gain_per_contract']:.2f}")
            sc3.metric("Basabas noktasi", f"${strategy['breakeven']:.2f}")

            qty = st.number_input(
                "Kontrat adedi", min_value=1, max_value=20, value=strategy["quantity_suggested"]
            )
            est_risk = strategy["max_loss_per_contract"] * qty
            st.caption(f"Tahmini toplam risk: ${est_risk:.2f} (limit: ${MAX_NOTIONAL_PER_TRADE:.2f})")

            b1, b2 = st.columns(2)
            if b1.button("✅ Onayla ve Paper Hesapta Gonder", type="primary"):
                result = submit_debit_spread(strategy, quantity=qty)
                if result["submitted"]:
                    record_human_action(card_id, "approve", f"qty={qty}")
                    record_execution(card_id, result, qty)
                    st.success(f"Emir gonderildi. Order ID: {result['order_id']} (status: {result['status']})")
                else:
                    record_human_action(card_id, "approve_blocked", f"qty={qty} - {result['reason']}")
                    st.error(result["reason"])
                st.session_state.pending = None

            note = b2.text_input("Red gerekcesi (opsiyonel)", key="reject_note")
            if b2.button("❌ Reddet"):
                record_human_action(card_id, "reject", note)
                st.info("Karar reddedildi ve denetim izine kaydedildi. Hicbir emir gonderilmedi.")
                st.session_state.pending = None
        else:
            st.info(
                "Sentiment 'neutral' oldugu ya da fiyat verisi eksik oldugu icin "
                "bu basit strateji seti bir islem onermiyor. Yine de karar denetim izine kaydedildi."
            )
            if st.button("Onayla (islem yok, sadece kayit)"):
                record_human_action(card_id, "acknowledge", "")
                st.session_state.pending = None

# --------------------------------------------------------------------------
# TAB 2: Denetim izi
# --------------------------------------------------------------------------
with tab_audit:
    st.subheader("Tam Denetim Izi")
    st.caption("Kaynak -> Analiz -> Insan Karari -> Emir zincirinin degismez kaydi.")
    trail = get_full_audit_trail()
    if not trail:
        st.info("Henuz kayitli bir karar yok.")
    for entry in trail:
        c = entry["card"]
        with st.container(border=True):
            st.markdown(
                f"**#{c['id']} · {c['symbol']} · {c['sentiment'].upper()} · "
                f"guven {c['confidence_score']}/100** — _{c['created_at']}_"
            )
            st.markdown(c["event_summary"])
            if entry["actions"]:
                for a in entry["actions"]:
                    st.markdown(f"→ Insan aksiyonu: **{a['action']}** ({a['acted_at']}) {a.get('note') or ''}")
            else:
                st.markdown("→ Henuz insan aksiyonu yok (bekliyor).")
            for e in entry["executions"]:
                st.markdown(
                    f"→ Emir gonderildi: `{e['order_id']}` durum={e['status']} "
                    f"adet={e['quantity']} limit=${e['limit_price']}"
                )
