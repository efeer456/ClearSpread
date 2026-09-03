"""
'Bu haber fiyata zaten yansimis mi?' kontrolu icin son fiyat/hacim hareketini ceker.
Gemini'in guven skorunu kalibre etmesine yardimci olur.

Veri, Alpaca CLI (alpaca data bars) uzerinden cekilir - bkz. alpaca_cli.py.
"""
from datetime import date, timedelta
from typing import Dict

from alpaca_cli import get_stock_bars


def get_recent_price_context(symbol: str, lookback_days: int = 5) -> Dict:
    """
    Son `lookback_days` gunluk gunluk barlardan basit bir ozet cikarir:
    son kapanis, lookback basindan bu yana % degisim, ortalamaya gore hacim orani.
    """
    end = date.today()
    start = end - timedelta(days=lookback_days + 3)  # hafta sonlari icin pay birak

    bars = get_stock_bars(
        symbol, start.isoformat(), end.isoformat(),
        timeframe="1Day", feed="iex",  # ucretsiz paper hesaplar SIP feed'ine erisemiyor
    )

    if not bars:
        return {"symbol": symbol, "available": False}

    bars = bars[-lookback_days:]
    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]

    pct_change = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] else 0.0
    avg_volume = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else volumes[-1]
    volume_ratio = volumes[-1] / avg_volume if avg_volume else 1.0

    return {
        "symbol": symbol,
        "available": True,
        "last_close": round(closes[-1], 2),
        "pct_change_period": round(pct_change, 2),
        "last_volume": volumes[-1],
        "volume_vs_avg_ratio": round(volume_ratio, 2),
        "lookback_days": lookback_days,
    }


if __name__ == "__main__":
    # Hizli manuel test: python -m agent.market_context
    print(get_recent_price_context("AAPL"))
