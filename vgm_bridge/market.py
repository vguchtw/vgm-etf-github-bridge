from __future__ import annotations

from datetime import date
from dateutil.relativedelta import relativedelta
import yfinance as yf


class MarketDataError(RuntimeError):
    pass


def period_end_price(symbol: str, period: str) -> float:
    start = date.fromisoformat(period + "-01")
    end = start + relativedelta(months=1)
    # Download enough data to obtain the last close inside the simulated month.
    frame = yf.download(
        symbol,
        start=start.isoformat(),
        end=end.isoformat(),
        progress=False,
        auto_adjust=True,
        actions=False,
    )
    if frame.empty:
        raise MarketDataError(f"No historical price found for {symbol} in {period}")
    close = frame["Close"].dropna()
    if close.empty:
        raise MarketDataError(f"No close price found for {symbol} in {period}")
    value = close.iloc[-1]
    if hasattr(value, "iloc"):
        value = value.iloc[0]
    return float(value)
