"""
SEC EDGAR full-text search API (efts.sec.gov) uzerinden 'gercek' OSINT katmani.

Bu, cogu rakip takimin sadece haber API'si kullanmasindan farklilasan kisim:
Form 4 (icerden ogrenen alim/satimi) ve 8-K (onemli olay bildirimi) gibi
resmi/kamusal beyanlari da sinyale dahil ediyoruz.

API key gerektirmez, ama SEC "fair access" politikasi geregi gercek bir
User-Agent (isim + iletisim) istiyor. Rate limit: ~10 req/sn.
"""
import time
from datetime import datetime, timedelta
from typing import List, Dict

import requests

from config import SEC_EDGAR_USER_AGENT

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
HEADERS = {"User-Agent": SEC_EDGAR_USER_AGENT}


def _search(query: str, forms: str, days_back: int, limit: int) -> List[Dict]:
    end = datetime.utcnow().date()
    start = end - timedelta(days=days_back)

    params = {
        "q": query,
        "forms": forms,
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
    }

    # SEC'in full-text search endpoint'i ara sira gecici 500 donuyor. Bu OSINT
    # katmani opsiyonel bir sinyal kaynagi - erisilemezse tum pipeline'i
    # dusurmek yerine bos liste donup analiz haber + fiyat ile devam etmeli
    # (reasoning.py zaten 'veri yok' durumunu ayrica ele aliyor).
    data = None
    for attempt in range(3):
        try:
            resp = requests.get(EFTS_URL, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception:
            if attempt == 2:
                return []
            time.sleep(1.5)

    hits = data.get("hits", {}).get("hits", [])[:limit]
    results = []
    for h in hits:
        src = h.get("_source", {})
        accession = src.get("adsh", "").replace("-", "")
        cik_list = src.get("ciks", [])
        cik = cik_list[0].lstrip("0") if cik_list else ""
        # Insan tarafindan okunabilir filing linki (index sayfasi)
        filing_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            if cik
            else "https://www.sec.gov/edgar/search/"
        )
        results.append(
            {
                "form": src.get("form"),
                "company": (src.get("display_names") or [""])[0],
                "filed_at": src.get("file_date"),
                "accession_no": src.get("adsh"),
                "url": filing_url,
            }
        )
    return results


def fetch_insider_filings(company_name: str, days_back: int = 14, limit: int = 5) -> List[Dict]:
    """Form 4 (insider trading) beyanlarini sirket adina gore arar."""
    return _search(f'"{company_name}"', forms="4", days_back=days_back, limit=limit)


def fetch_material_events(company_name: str, days_back: int = 14, limit: int = 5) -> List[Dict]:
    """8-K (onemli olay) beyanlarini sirket adina gore arar."""
    return _search(f'"{company_name}"', forms="8-K", days_back=days_back, limit=limit)


if __name__ == "__main__":
    # Hizli manuel test: python -m osint.sec_edgar
    for f in fetch_material_events("Apple Inc", days_back=30):
        print(f)
