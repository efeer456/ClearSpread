"""
Alpaca'nin NewsClient'i uzerinden belirli ticker'lar icin son haberleri ceker.
Bu, karar kartinin ilk "kaynak" katmanidir.

Not: alpaca-py'nin NewsClient'i genellikle key gerektirmeden de calisir,
ancak rate-limit'ten kacinmak icin kendi Alpaca anahtarlarinizi vermeniz onerilir.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict

from alpaca.data.historical.news import NewsClient
from alpaca.data.requests import NewsRequest

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY

_client = NewsClient(ALPACA_API_KEY, ALPACA_SECRET_KEY) if ALPACA_API_KEY else NewsClient()


def fetch_recent_news(symbol: str, lookback_hours: int = 24, limit: int = 10) -> List[Dict]:
    """
    Verilen sembol icin son `lookback_hours` saat icindeki haberleri dondurur.

    Donen her item: {"id", "headline", "summary", "url", "created_at", "source"}
    """
    start = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    request = NewsRequest(symbols=symbol, start=start, limit=limit, sort="desc")

    news_set = _client.get_news(request)
    items = []
    for n in news_set.data["news"]:
        items.append(
            {
                "id": str(n.id),
                "headline": n.headline,
                "summary": getattr(n, "summary", "") or "",
                "url": n.url,
                "created_at": n.created_at.isoformat() if n.created_at else None,
                "source": n.source,
                "symbols": n.symbols,
            }
        )
    return items


if __name__ == "__main__":
    # Hizli manuel test: python -m osint.alpaca_news
    for item in fetch_recent_news("AAPL", lookback_hours=72, limit=5):
        print(item["created_at"], "-", item["headline"])
