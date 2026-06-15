"""Pure technical-indicator functions over a price series/DataFrame.

Hand-rolled with pandas/numpy to avoid TA-Lib's C dependency (a known EC2
install pain point). Every function is deterministic and unit-tested.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing == EMA with alpha = 1/n.
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss is 0 (only gains), RSI is 100.
    out = out.where(avg_loss != 0.0, 100.0)
    # But keep NaN during the warm-up window.
    out[avg_gain.isna()] = np.nan
    return out


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD line, signal line, and histogram."""
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def momentum(series: pd.Series, n: int = 10) -> pd.Series:
    """Rate of change over n periods, as a fraction (0.05 == +5%)."""
    return series.pct_change(periods=n)


def volume_ratio(volume: pd.Series, n: int = 20) -> pd.Series:
    """Latest volume relative to the trailing n-period average."""
    avg = volume.rolling(window=n, min_periods=n).mean()
    return volume / avg.replace(0.0, np.nan)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average True Range. Expects columns: high, low, close."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def golden_cross(fast_ma: pd.Series, slow_ma: pd.Series) -> bool:
    """True if fast MA crossed above slow MA on the latest bar."""
    if len(fast_ma) < 2 or len(slow_ma) < 2:
        return False
    f0, f1 = fast_ma.iloc[-2], fast_ma.iloc[-1]
    s0, s1 = slow_ma.iloc[-2], slow_ma.iloc[-1]
    if any(pd.isna(x) for x in (f0, f1, s0, s1)):
        return False
    return bool(f0 <= s0 and f1 > s1)
