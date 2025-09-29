# Stock Correlation & Stress App

Frontend (static HTML + JS) + FastAPI backend. Fetches Yahoo Finance history, computes correlation/beta/alpha/rolling r, and simulates conditional shocks.

## Quick start (local)
- Requirements: Python 3.10+ (no Node needed)

Option A — simple local run
```powershell
# 1) Create venv (optional)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Install backend deps
pip install -r backend\requirements.txt

# 3) Start backend API
python backend\main.py    # http://127.0.0.1:8000

# 4) Serve frontend (from project root) in another terminal
python -m http.server 8080  # http://127.0.0.1:8080
```
Open http://127.0.0.1:8080 and click Run. In dev, the frontend calls http://127.0.0.1:8000.

Option B — Docker Compose
```powershell
docker compose up -d
# Frontend: http://127.0.0.1:8080
# Backend : http://127.0.0.1:8000
```

## Deploy behind Nginx Proxy Manager + Cloudflare
- Create two Proxy Hosts in NPM:
	- stock.nethercot.uk → http://<vm-ip>:8080 (Let’s Encrypt, Force SSL)
	- api.stock.nethercot.uk → http://<vm-ip>:8000 (Let’s Encrypt, Force SSL)
- Cloudflare DNS: A records for stock and api to your public IP (proxy ON). If LE fails, temporarily turn proxy OFF to issue certs.
- Full, step-by-step guide: see `SELF_HOSTING.md`.

## Configuration (env)
- `ALLOW_ORIGINS`: comma-separated CORS origins (e.g., `https://stock.nethercot.uk,https://api.stock.nethercot.uk`).
- `HOST`/`PORT`: backend bind host/port (default 0.0.0.0:8000).

## API
- GET `/` → health JSON.
- GET `/history?ticker=AAPL&start=2024-01-01&end=2024-03-01`
	- Returns array of OHLCV with ISO date strings; cleans NaN/inf rows.

## How it works (stats model)
- Build daily log-returns for both series over the overlapping range.
- Compute means, variances, covariance, Pearson r, OLS beta/alpha.
- Conditional shock: for shock to A, model B | A as Normal with:
	- E[B|A] = μB + Cov(A,B)/Var(A) × shockA
	- Var[B|A] = Var(B) − Cov(A,B)^2 / Var(A)
- Show Expected B and Monte Carlo histogram/quantiles for B|A.

## Limitations
- Simplified Gaussian/linear model; no fat tails, copulas, regime shifts, or GARCH.
- Not a full stress testing platform.

## Troubleshooting
- “Not enough overlapping data”: check date range, markets/holidays, or widen the window.
- CORS errors in prod: ensure `ALLOW_ORIGINS` includes exactly your frontend origin(s).
- Mixed content: access both frontend and backend via HTTPS through NPM.

## Project structure
```
backend/            # FastAPI server
	main.py           # API endpoints
	requirements.txt  # Python deps
nginx/default.conf  # Static site nginx config (Docker)
docker-compose.yml  # Frontend (8080) + Backend (8000)
index.html, main.js # Frontend UI and logic (Plotly, fetch)
SELF_HOSTING.md     # Detailed NPM + Cloudflare guide
```
