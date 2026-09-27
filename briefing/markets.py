"""Market snapshot: delayed quotes as numeric anchors for the Market Ledger.

These are *prices*, not facts about policy; the prompt keeps them in a
separate block so the model never blends them with official announcements.
Sovereign spreads (BTP-Bund, OAT-Bund) are not reliably available from free
quote feeds, so the model verifies them from Tier-1 sources via web search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# label -> Yahoo Finance symbol
INSTRUMENTS: dict[str, str] = {
    "EUR/USD": "EURUSD=X",
    "EUR/CNY": "EURCNY=X",
    "Brent (front, $/bbl)": "BZ=F",
    "Dutch TTF (front, EUR/MWh)": "TTF=F",
    "Gold ($/oz)": "GC=F",
    "US 10Y yield (%)": "^TNX",
    "VIX": "^VIX",
    "Euro Stoxx 50": "^STOXX50E",
    "DAX": "^GDAXI",
    "CAC 40": "^FCHI",
    "FTSE MIB": "FTSEMIB.MI",
    "S&P 500": "^GSPC",
    # Global axis anchors
    "US Dollar Index (DXY)": "DX-Y.NYB",
    "USD/CNH": "CNH=X",
    "CSI 300": "000300.SS",
    "Hang Seng": "^HSI",
    "USD/RUB": "RUB=X",
    "USD/INR": "INR=X",
    "Nifty 50": "^NSEI",
    "USD/BRL": "BRL=X",
    "Bovespa": "^BVSP",
    "WTI (front, $/bbl)": "CL=F",
}


@dataclass(frozen=True)
class Quote:
    label: str
    last: float
    change_pct: float | None


def snapshot() -> list[Quote]:
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed; skipping market snapshot")
        return []

    quotes: list[Quote] = []
    for label, symbol in INSTRUMENTS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            closes = hist["Close"].dropna()
            if closes.empty:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else None
            chg = (last / prev - 1) * 100 if prev else None
            quotes.append(Quote(label, last, chg))
        except Exception as exc:
            log.warning("quote %s failed: %s", symbol, exc)
    return quotes


def render(quotes: list[Quote]) -> str:
    if not quotes:
        return "(unavailable — verify all levels via web search)"
    lines = []
    for q in quotes:
        chg = f" ({q.change_pct:+.2f}% d/d)" if q.change_pct is not None else ""
        lines.append(f"- {q.label}: {q.last:,.2f}{chg}")
    return "\n".join(lines)
