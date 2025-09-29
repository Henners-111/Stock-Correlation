# Stock Correlation & Stress App

A tiny frontend + FastAPI backend to fetch stock history from Yahoo Finance, compute correlations, and simulate shocks.

## Prereqs
- Python 3.10+
- Node not required (static HTML + JS only)

## Setup (Windows PowerShell)

```powershell
# Create and activate a virtual environment (optional but recommended)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -r backend\requirements.txt

# Run backend API
python backend\main.py
```

Backend will start at http://127.0.0.1:8000

## Use the app
- Open `index.html` directly in your browser.
- Fill tickers and dates, click Run.

## Notes
- CORS is enabled for all origins.
- Monte Carlo uses a 2D Gaussian with covariance from historical returns.
- If there is little overlapping data, the app will show an error in the status area.

## What it does
- Fits a bivariate normal to historical daily log-returns of the two tickers (means, variances, covariance).
- You enter a shock to A (%). The app computes B’s conditional distribution given that realized shock:
	- E[B|A] = μB + Cov(A,B)/Var(A) × shockA
	- Var[B|A] = Var(B) − Cov(A,B)^2 / Var(A)
- Reports Expected B (shock) from that conditional mean and runs a Monte Carlo on B|A to show p5/p50/p95 and a histogram.
- Computes correlation, beta, alpha, covariance, and rolling correlation from the same historical returns.

## What it is not
- Not a regulatory or firm-wide stress platform (no macro scenarios, factor models, liquidity/contagion, non-linear exposures, or PnL attribution).
- Assumes Gaussian returns and linear relationships; no fat tails, copulas, regime shifts, or GARCH volatility.

## Ideas for stronger stress modeling
- Historical scenario replay (e.g., 2008, COVID) and worst-k day blocks.
- t-distribution or copula-based dependence to capture tail co-movements.
- GARCH/EGARCH volatility scaling and regime detection.
- Factor-based shocks (e.g., market, rates, credit) mapped to tickers/portfolio weights.
- Non-linear payoff support and portfolio aggregation.
