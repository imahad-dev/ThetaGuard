"""Options mathematics, Black-Scholes pricing, Greeks solver, and empirical volatility percentile calculators."""
import math
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.stats import norm

RISK_FREE_RATE = 0.045  # Standard 4.5% risk free rate approximation

# 52-week IV range baselines for SPY and QQQ
HISTORICAL_IV_RANGES = {
    "SPY": {"min_iv": 0.105, "max_iv": 0.285},
    "QQQ": {"min_iv": 0.145, "max_iv": 0.355},
}


def calculate_d1_d2(
    S: float, K: float, T: float, r: float, sigma: float
) -> Tuple[float, float]:
    """Calculates Black-Scholes d1 and d2 parameters."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0, 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def calculate_put_delta(
    S: float, K: float, T: float, r: float = RISK_FREE_RATE, sigma: float = 0.20
) -> float:
    """
    Calculates Put Delta: N(d1) - 1.
    Values range from -1.0 (deep ITM) to 0.0 (deep OTM).
    """
    if T <= 0.0001:
        return -1.0 if S < K else 0.0
    d1, _ = calculate_d1_d2(S, K, T, r, sigma)
    delta = norm.cdf(d1) - 1.0
    return float(delta)


def calculate_put_price(
    S: float, K: float, T: float, r: float = RISK_FREE_RATE, sigma: float = 0.20
) -> float:
    """Calculates Black-Scholes theoretical European Put price."""
    if T <= 0:
        return max(0.0, K - S)
    d1, d2 = calculate_d1_d2(S, K, T, r, sigma)
    put_price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return float(max(0.01, put_price))


def calculate_implied_volatility_from_put(
    S: float, K: float, T: float, r: float, market_price: float, tol: float = 1e-4, max_iter: int = 100
) -> float:
    """
    Inverts Black-Scholes put formula using bisection search to compute implied volatility from option price.
    """
    if market_price <= 0 or T <= 0:
        return 0.18

    # Lower and upper volatility bounds
    low_sigma, high_sigma = 0.01, 3.00
    for _ in range(max_iter):
        mid_sigma = (low_sigma + high_sigma) / 2.0
        price = calculate_put_price(S, K, T, r, mid_sigma)
        diff = price - market_price
        if abs(diff) < tol:
            return float(mid_sigma)
        if diff > 0:
            high_sigma = mid_sigma
        else:
            low_sigma = mid_sigma

    return float((low_sigma + high_sigma) / 2.0)


def calculate_historical_realized_volatility_series(
    close_prices: List[float], window: int = 20
) -> List[float]:
    """
    Calculates rolling window annualized close-to-close realized volatility across a price series.
    Returns a list of annualized volatilities.
    """
    if len(close_prices) < window + 1:
        return [0.18]

    prices = np.array(close_prices, dtype=np.float64)
    log_returns = np.diff(np.log(prices))

    vol_series = []
    for i in range(window, len(log_returns) + 1):
        window_returns = log_returns[i - window : i]
        vol = np.std(window_returns, ddof=1) * np.sqrt(252.0)
        vol_series.append(float(vol))

    return vol_series


def calculate_volatility_rank_and_percentile(
    current_vol: float, historical_vol_series: List[float]
) -> Tuple[float, float, float, float]:
    """
    Calculates 52-week Volatility Rank and Percentile from a historical volatility series.
    Returns (rank_0_100, percentile_0_100, min_vol, max_vol).
    """
    if not historical_vol_series:
        return 40.0, 40.0, 0.10, 0.30

    vols = np.array(historical_vol_series, dtype=np.float64)
    min_vol = float(np.min(vols))
    max_vol = float(np.max(vols))

    if max_vol <= min_vol:
        rank = 50.0
    else:
        rank = float(np.clip(((current_vol - min_vol) / (max_vol - min_vol)) * 100.0, 0.0, 100.0))

    # Empirical percentile rank: % of days where historical vol <= current_vol
    percentile = float(np.sum(vols <= current_vol) / len(vols) * 100.0)

    return rank, percentile, min_vol, max_vol


def calculate_iv_rank(
    current_iv: float, underlying: str = "SPY", custom_range: Optional[Dict[str, float]] = None
) -> float:
    """
    Calculates 52-week IV Rank (0 to 100):
    IV Rank = ((Current IV - 52w Low IV) / (52w High IV - 52w Low IV)) * 100
    """
    symbol = underlying.upper()
    iv_range = custom_range or HISTORICAL_IV_RANGES.get(
        symbol, {"min_iv": 0.12, "max_iv": 0.32}
    )
    min_iv = iv_range["min_iv"]
    max_iv = iv_range["max_iv"]

    if max_iv <= min_iv:
        return 50.0

    raw_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100.0
    return float(np.clip(raw_rank, 0.0, 100.0))


def time_to_expiry_years(exp_date: date, current_dt: Optional[datetime] = None) -> float:
    """Computes time to expiration in fraction of trading/calendar years (365 days base)."""
    now = current_dt or datetime.now(timezone.utc)
    exp_dt = datetime(exp_date.year, exp_date.month, exp_date.day, 16, 0, tzinfo=timezone.utc)
    diff = (exp_dt - now).total_seconds()
    if diff <= 0:
        return 0.0001
    return diff / (365.0 * 86400.0)


def calculate_realized_volatility(price_series: List[float], window: int = 20) -> float:
    """Calculates annualized close-to-close realized volatility."""
    if len(price_series) < 2:
        return 0.18
    prices = np.array(price_series, dtype=np.float64)
    log_returns = np.diff(np.log(prices))
    std = np.std(log_returns, ddof=1) if len(log_returns) > 1 else np.std(log_returns)
    return float(std * np.sqrt(252.0))


def generate_benchmark_price_history(symbol: str, count: int = 252) -> List[float]:
    """
    Generates realistic 252-day geometric Brownian motion price series for fallback/simulation.
    """
    np.random.seed(42 if symbol.upper() == "SPY" else 101)
    base_price = 560.0 if symbol.upper() == "SPY" else 480.0
    daily_vol = (0.16 if symbol.upper() == "SPY" else 0.22) / np.sqrt(252.0)
    drift = 0.08 / 252.0
    returns = np.random.normal(drift, daily_vol, count)
    prices = [base_price * float(np.exp(np.sum(returns[:i]))) for i in range(1, count + 1)]
    return prices
