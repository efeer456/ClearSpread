"""
Alpaca ile konusma katmani: dogrudan alpaca-py SDK yerine resmi Alpaca CLI
(https://github.com/alpacahq/cli) uzerinden subprocess cagrisi yapar.
Hackathon kurallari, projenin Alpaca'nin MCP server'ini veya CLI'sini
kullanmasini zorunlu kiliyor - burada CLI tercih edildi.

agent/market_context.py, agent/options_strategy.py ve trading/executor.py
tum Alpaca veri/emir cagrilarini buradan yapar.
"""
import json
import os
import subprocess
from typing import Dict, List, Optional

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_CLI_PATH


class AlpacaCliError(RuntimeError):
    pass


def _run(*args: str) -> Optional[Dict]:
    env = os.environ.copy()
    env["ALPACA_API_KEY"] = ALPACA_API_KEY
    env["ALPACA_SECRET_KEY"] = ALPACA_SECRET_KEY

    cli_path = ALPACA_CLI_PATH
    if os.sep in cli_path or "/" in cli_path:
        cli_path = os.path.abspath(cli_path)

    result = subprocess.run(
        [cli_path, *args, "--quiet"],
        env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AlpacaCliError(result.stderr.strip() or f"alpaca CLI exited with code {result.returncode}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def get_account() -> Dict:
    return _run("account", "get")


def get_stock_bars(symbol: str, start: str, end: str,
                    timeframe: str = "1Day", feed: str = "iex") -> List[Dict]:
    """start/end: 'YYYY-MM-DD'. Doner: [{'c','h','l','n','o','t','v','vw'}, ...] (eskiden yeniye)."""
    data = _run(
        "data", "bars",
        "--symbol", symbol, "--start", start, "--end", end,
        "--timeframe", timeframe, "--feed", feed,
    )
    return (data or {}).get("bars", [])


def get_option_chain(underlying_symbol: str, contract_type: str,
                      expiration_date_gte: str, expiration_date_lte: str,
                      strike_price_gte: float, strike_price_lte: float) -> Dict[str, Dict]:
    """Doner: {occ_symbol: {'latestQuote': {'bp','ap',...}, 'greeks': {...}, ...}}."""
    data = _run(
        "data", "option", "chain",
        "--underlying-symbol", underlying_symbol,
        "--type", contract_type,
        "--expiration-date-gte", expiration_date_gte,
        "--expiration-date-lte", expiration_date_lte,
        "--strike-price-gte", str(strike_price_gte),
        "--strike-price-lte", str(strike_price_lte),
    )
    return (data or {}).get("snapshots", {})


def submit_mleg_order(legs: List[Dict], qty: int, limit_price: float,
                       time_in_force: str = "day", dry_run: bool = False) -> Dict:
    """legs: [{'symbol','side','ratio_qty','position_intent'}, ...] (<=4 bacak)."""
    args = [
        "order", "submit",
        "--order-class", "mleg",
        "--qty", str(qty),
        "--type", "limit",
        "--limit-price", str(limit_price),
        "--time-in-force", time_in_force,
        "--legs", json.dumps(legs),
    ]
    if dry_run:
        args.append("--dry-run")
    return _run(*args)


def get_order(order_id: str) -> Dict:
    return _run("order", "get", "--order-id", order_id)
