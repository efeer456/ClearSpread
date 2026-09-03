"""
Karar kartindaki sentiment'e gore, Alpaca'nin option chain verisinden
TANIMLI RISKLI (defined-risk) bir strateji onerisi kurar: debit call/put spread.

Tasarim tercihi: "naked" (aciga) opsiyon satisi / sinirsiz riskli stratejiler
BILINCLI OLARAK desteklenmiyor. Bu proje 'guvenlik-once, seffaf, insan onayli'
temasi uzerine kurulu - o yuzden her zaman max kayip onceden bilinen bir yapi.

Option chain verisi Alpaca CLI (alpaca data option chain) uzerinden cekilir -
bkz. alpaca_cli.py.
"""
from datetime import date, timedelta
from typing import Dict, Optional

from alpaca_cli import get_option_chain


def _mid_price(snapshot: Optional[Dict]) -> Optional[float]:
    q = (snapshot or {}).get("latestQuote")
    if q and q.get("bp") and q.get("ap"):
        return round((q["bp"] + q["ap"]) / 2, 2)
    return None


def propose_debit_spread(symbol: str, sentiment: str, spot_price: float,
                          min_dte: int = 14, max_dte: int = 45,
                          width_pct: float = 0.05) -> Optional[Dict]:
    """
    sentiment == 'bullish'  -> long call debit spread (uzun/kisa call)
    sentiment == 'bearish'  -> long put debit spread  (uzun/kisa put)
    sentiment == 'neutral'  -> None (bu basit strateji seti icin islem onerilmiyor)

    Donen dict: strategy_name, legs (buy/sell + strike + expiration + symbol),
    estimated_debit, max_loss, max_gain, breakeven.
    """
    if sentiment not in ("bullish", "bearish"):
        return None

    contract_type = "call" if sentiment == "bullish" else "put"

    today = date.today()
    exp_gte = today + timedelta(days=min_dte)
    exp_lte = today + timedelta(days=max_dte)

    strike_low = spot_price * (1 - width_pct * 2)
    strike_high = spot_price * (1 + width_pct * 2)

    chain = get_option_chain(
        underlying_symbol=symbol,
        contract_type=contract_type,
        expiration_date_gte=exp_gte.isoformat(),
        expiration_date_lte=exp_lte.isoformat(),
        strike_price_gte=strike_low,
        strike_price_lte=strike_high,
    )

    if not chain:
        return None

    # Chain, istenen min_dte-max_dte araligindaki TUM vadeleri birlikte dondurur.
    # Bacaklari sadece strike'a gore eslestirirsek farkli vadelerden secilip
    # "diagonal spread"e donusebilir - once tek bir vadeye daralt.
    all_contracts = []
    for occ_symbol, snapshot in chain.items():
        strike = _extract_strike_from_symbol(occ_symbol)
        expiry = _extract_expiry_from_symbol(symbol, occ_symbol)
        if strike is None or expiry is None:
            continue
        all_contracts.append((strike, expiry, occ_symbol, snapshot))

    if len(all_contracts) < 2:
        return None

    # En yakin (en erken) vadeyi hedefle, sadece o vadedeki kontratlarla devam et.
    target_expiry = min(e for _, e, _, _ in all_contracts)
    contracts = [(strike, occ_symbol, snapshot)
                 for strike, expiry, occ_symbol, snapshot in all_contracts
                 if expiry == target_expiry]

    if len(contracts) < 2:
        return None

    contracts.sort(key=lambda c: c[0])

    if sentiment == "bullish":
        long_leg = min(contracts, key=lambda c: abs(c[0] - spot_price))
        target_short_strike = long_leg[0] * (1 + width_pct)
        short_leg = min(
            (c for c in contracts if c[0] > long_leg[0]),
            key=lambda c: abs(c[0] - target_short_strike),
            default=None,
        )
    else:  # bearish -> put debit spread: uzun bacak ATM, kisa bacak daha asagida
        long_leg = min(contracts, key=lambda c: abs(c[0] - spot_price))
        target_short_strike = long_leg[0] * (1 - width_pct)
        short_leg = min(
            (c for c in contracts if c[0] < long_leg[0]),
            key=lambda c: abs(c[0] - target_short_strike),
            default=None,
        )

    if short_leg is None:
        return None

    long_price = _mid_price(long_leg[2])
    short_price = _mid_price(short_leg[2])
    if long_price is None or short_price is None:
        return None

    net_debit = round(long_price - short_price, 2)
    width = abs(short_leg[0] - long_leg[0])
    max_loss = round(net_debit * 100, 2)          # 1 kontrat = 100 hisse
    max_gain = round((width - net_debit) * 100, 2)
    breakeven = round(
        long_leg[0] + net_debit if sentiment == "bullish" else long_leg[0] - net_debit, 2
    )

    return {
        "strategy_name": f"{'Call' if sentiment == 'bullish' else 'Put'} Debit Spread",
        "legs": [
            {"action": "buy", "type": contract_type, "strike": long_leg[0], "symbol": long_leg[1]},
            {"action": "sell", "type": contract_type, "strike": short_leg[0], "symbol": short_leg[1]},
        ],
        "estimated_debit_per_contract": net_debit,
        "max_loss_per_contract": max_loss,
        "max_gain_per_contract": max_gain,
        "breakeven": breakeven,
        "quantity_suggested": 1,  # guvenlik icin varsayilan 1 kontrat, UI'da degistirilebilir
    }


def _extract_strike_from_symbol(occ_symbol: str) -> Optional[float]:
    """OCC formatli sembolden (orn. AAPL260116C00150000) strike fiyatini cikarir."""
    try:
        digits = occ_symbol[-8:]
        return int(digits) / 1000.0
    except (ValueError, IndexError):
        return None


def _extract_expiry_from_symbol(underlying_symbol: str, occ_symbol: str) -> Optional[str]:
    """OCC formatli sembolden (orn. AAPL260116C00150000) YYMMDD vade kodunu cikarir."""
    try:
        prefix_len = len(underlying_symbol)
        return occ_symbol[prefix_len:prefix_len + 6]
    except IndexError:
        return None
