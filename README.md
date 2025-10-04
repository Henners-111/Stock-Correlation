# Stock Correlation & Stress App

Frontend (static HTML + JS) + FastAPI backend. Fetches Yahoo Finance history, computes correlation/beta/alpha/rolling r, and simulates conditional shocks.

## Quick start (local)
- Requirements: Python 3.10+ (no Node needed)

Local run
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

## Deploy via GitHub Pages + home backend
1. **Frontend (static)**
	- Push the repository to GitHub.
	- In repo settings → Pages, choose “Deploy from branch”, select `main` and `/ (root)`.
	- (Optional) Add `CNAME` with `stock.nethercot.uk` and point Cloudflare DNS A record `stock` to your home IP. Ensure “Force HTTPS” is on once the cert is issued.

2. **Backend (FastAPI) on your home server**
	- Install Python 3.10+ on the host (Proxmox VM, bare metal, etc.).
	- Clone the repo and install deps:
```bash
git clone https://github.com/<your-username>/stock-corr-demo.git
cd stock-corr-demo
python3 -m venv .venv
source .venv/bin/activate  # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```
- Run the API (example using uvicorn directly):
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```
- For a permanent service, create a systemd unit or Supervisor entry that launches the above command on boot.

3. **Expose through Nginx Proxy Manager (NPM) + Cloudflare**
	- In NPM, create a Proxy Host `api.stock.nethercot.uk` → http://<home-server-ip>:8000. Enable Websockets. Issue a Let’s Encrypt cert, Force SSL, HTTP/2, HSTS.
	- In Cloudflare, add an A record `api` pointing to your home IP (orange cloud ON). If LE fails, temporarily gray-cloud OFF, issue cert, then re-enable.
	- The frontend (GitHub Pages) already calls `https://api.stock.nethercot.uk` in production, so once DNS + certs propagate the app will work end-to-end.

4. **CORS**
	- Ensure the backend `ALLOW_ORIGINS` env includes `https://stock.nethercot.uk` (and any other host you serve the frontend from). For local testing, you can leave defaults.

See `SELF_HOSTING.md` for a fuller walkthrough of the NPM + Cloudflare flow.

## Configuration (env)
- `ALLOW_ORIGINS`: comma-separated CORS origins (e.g., `https://stock.nethercot.uk,https://api.stock.nethercot.uk`).
- `HOST`/`PORT`: backend bind host/port (default 0.0.0.0:8000).
- `PROVIDERS`: comma-separated data providers in order of preference. Default `yahoo,stooq`. If Yahoo Finance blocks your server or rate-limits, set `stooq,yahoo`.
- `LOG_LEVEL`: Python logging level (e.g., `INFO`, `DEBUG`).

## API
- GET `/` → health JSON.
- GET `/history?ticker=AAPL&start=2024-01-01&end=2024-03-01`
	- Returns array of OHLCV with ISO date strings; cleans NaN/inf rows.
	- Will try providers in order (`PROVIDERS`). Response may include `provider` (e.g., `"yahoo"` or `"stooq"`). On failure, returns `{ ticker, data: [], error }`.
- GET `/suggest?q=AAPL&limit=12`
	- Returns up to `limit` ticker suggestions using Yahoo Finance search with a Stooq fallback.
	- Covers equities, ETFs, commodities, FX/interest-rate indices, and cryptocurrencies so tickers like `GC=F`, `^TNX`, or `BTC-USD` appear alongside stocks.
	- Response items include `symbol`, `name`, optional `exchange`, `last`, and `change_percent` (percent change). When the Yahoo symbol differs from the preferred Stooq-style ticker (e.g., `BTC-USD` → `BTC.V`, `GC=F` → `XAUUSD`, `^TNX` → `INRTUS.M`), the payload also sets `alias_of` to the original symbol so the UI can show provenance.
	- Suggestions are ordered by Yahoo's popularity score (with light type-based nudges) so the most traded symbols surface first.

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
index.html, main.js # Frontend UI and logic (Plotly, fetch)
SELF_HOSTING.md     # Detailed NPM + Cloudflare guide
```
