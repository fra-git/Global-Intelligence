"""Market snapshot: delayed quotes for the economy desk and the PDF markets dashboard.

These are *prices*, not facts about policy; the prompt keeps them in a
separate block so the model never blends them with official announcements.
Sovereign spreads (BTP-Bund, OAT-Bund) are not reliably available from free
quote feeds, so the model verifies them from Tier-1 sources via web search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# category -> label -> Yahoo Finance symbol
GROUPS: dict[str, dict[str, str]] = {
    "Europe": {
        "Euro Stoxx 50": "^STOXX50E",
        "FTSE MIB (Italy)": "FTSEMIB.MI",
        "DAX (Germany)": "^GDAXI",
        "CAC 40 (France)": "^FCHI",
        "IBEX 35 (Spain)": "^IBEX",
        "FTSE 100 (UK)": "^FTSE",
    },
    "Americas": {
        "S&P 500": "^GSPC",
        "Nasdaq 100": "^NDX",
        "VIX (US volatility)": "^VIX",
        "Bovespa (Brazil)": "^BVSP",
    },
    "Asia": {
        "Nikkei 225 (Japan)": "^N225",
        "CSI 300 (China)": "000300.SS",
        "Hang Seng (Hong Kong)": "^HSI",
        "KOSPI (South Korea)": "^KS11",
        "Taiex (Taiwan)": "^TWII",
        "Nifty 50 (India)": "^NSEI",
    },
    "Rates": {
        "US 10Y yield (%)": "^TNX",
        "US 2Y yield (%)": "2YY=F",
    },
    "Currencies": {
        "EUR/USD": "EURUSD=X",
        "EUR/GBP": "EURGBP=X",
        "EUR/CHF": "EURCHF=X",
        "EUR/CNY": "EURCNY=X",
        "US Dollar Index (DXY)": "DX-Y.NYB",
        "USD/JPY": "JPY=X",
        "USD/CNH": "CNH=X",
        "USD/RUB": "RUB=X",
        "USD/INR": "INR=X",
        "USD/BRL": "BRL=X",
        "USD/TRY": "TRY=X",
        "Bitcoin ($)": "BTC-USD",
    },
    "Commodities": {
        "Brent ($/bbl)": "BZ=F",
        "WTI ($/bbl)": "CL=F",
        "Dutch TTF gas (EUR/MWh)": "TTF=F",
        "Gold ($/oz)": "GC=F",
        "Silver ($/oz)": "SI=F",
        "Copper ($/lb)": "HG=F",
        "Wheat (c/bu)": "ZW=F",
    },
}
INSTRUMENTS: dict[str, str] = {k: v for g in GROUPS.values() for k, v in g.items()}


@dataclass(frozen=True)
class Quote:
    label: str
    last: float
    change_pct: float | None
    week_pct: float | None = None


def snapshot() -> list[Quote]:
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed; skipping market snapshot")
        return []

    quotes: list[Quote] = []
    for label, symbol in INSTRUMENTS.items():
        try:
            hist = yf.Ticker(symbol).history(period="1mo", interval="1d")
            closes = hist["Close"].dropna()
            if closes.empty:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else None
            week = float(closes.iloc[-6]) if len(closes) > 5 else None
            chg = (last / prev - 1) * 100 if prev else None
            wk = (last / week - 1) * 100 if week else None
            quotes.append(Quote(label, last, chg, wk))
        except Exception as exc:
            log.warning("quote %s failed: %s", symbol, exc)
    return quotes


def render(quotes: list[Quote]) -> str:
    if not quotes:
        return "(unavailable — verify all levels via web search)"
    lines = []
    for q in quotes:
        moves = [f"{v:+.2f}% {k}" for k, v in (("d/d", q.change_pct), ("w/w", q.week_pct))
                 if v is not None]
        lines.append(f"- {q.label}: {q.last:,.2f}" + (f" ({', '.join(moves)})" if moves else ""))
    return "\n".join(lines)
