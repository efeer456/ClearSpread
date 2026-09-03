"""
Bu modul YALNIZCA insan onayindan sonra cagrilir (app.py'deki Approve butonu).
Karar kartinin kendisi asla dogrudan buraya gelmez - once UI'da kullanici
'Approve' demis olmali. Bu, projenin 'insan-onayli' vaadinin kod seviyesindeki
karsiligi.

Emir, dogrudan alpaca-py SDK yerine resmi Alpaca CLI uzerinden gonderilir -
bkz. alpaca_cli.py.
"""
from typing import Dict

from alpaca_cli import submit_mleg_order
from config import MAX_NOTIONAL_PER_TRADE


def submit_debit_spread(strategy: Dict, quantity: int = 1) -> Dict:
    """
    `agent.options_strategy.propose_debit_spread` ciktisini alip PAPER hesapta
    bir MLEG (multi-leg) limit emri olarak gonderir.

    Guvenlik kontrolu: toplam notional (quantity * max_loss_per_contract),
    config.MAX_NOTIONAL_PER_TRADE degerini asarsa emir GONDERILMEZ.
    """
    estimated_risk = strategy["max_loss_per_contract"] * quantity
    if estimated_risk > MAX_NOTIONAL_PER_TRADE:
        return {
            "submitted": False,
            "reason": (
                f"Guvenlik limiti asildi: tahmini risk ${estimated_risk:.2f} > "
                f"izin verilen ${MAX_NOTIONAL_PER_TRADE:.2f}. Miktari azaltin."
            ),
        }

    legs = []
    for leg in strategy["legs"]:
        intent = "buy_to_open" if leg["action"] == "buy" else "sell_to_open"
        legs.append({
            "symbol": leg["symbol"],
            "side": leg["action"],
            "ratio_qty": "1",
            "position_intent": intent,
        })

    order = submit_mleg_order(
        legs=legs,
        qty=quantity,
        limit_price=strategy["estimated_debit_per_contract"],
    )

    return {
        "submitted": True,
        "order_id": order["id"],
        "status": order["status"],
        "legs": [leg["symbol"] for leg in strategy["legs"]],
        "limit_price": strategy["estimated_debit_per_contract"],
        "quantity": quantity,
    }
