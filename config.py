"""
Merkezi konfigurasyon. Tum modul .env dosyasindan degerleri buradan okur.
"""
import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SEC_EDGAR_USER_AGENT = os.getenv(
    "SEC_EDGAR_USER_AGENT", "AlpacaOsintAgent contact@example.com"
)
WATCHLIST = [t.strip().upper() for t in os.getenv("WATCHLIST", "AAPL,TSLA,NVDA").split(",")]

# Karar kartlarinin ve emirlerin tutuldugu SQLite dosyasi
DB_PATH = os.path.join(os.path.dirname(__file__), "audit_trail.db")

# Gemini ile analiz icin kullanilacak model (gerekirse .env'de GEMINI_MODEL ile ezilebilir)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# Riski sinirlamak icin: bir emirde harcanacak maksimum notional (paper hesapta bile)
MAX_NOTIONAL_PER_TRADE = 500.0

# Resmi Alpaca CLI (https://github.com/alpacahq/cli) binary yolu.
# Hackathon kurali geregi trading/data cagrilari SDK yerine bu CLI uzerinden yapiliyor.
ALPACA_CLI_PATH = os.getenv("ALPACA_CLI_PATH", "alpaca")
