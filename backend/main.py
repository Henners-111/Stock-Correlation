# backend/main.py
from fastapi import FastAPI
import yfinance as yf
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import pandas as pd
import math
import os


app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

	
# Allow CORS origins to be configured via env var (comma-separated)
_env_origins = os.getenv("ALLOW_ORIGINS")
if _env_origins:
	allow_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
else:
	# Sensible defaults for local dev and the provided production domain
	allow_origins = [
		"https://stock-correlation.onrender.com"
		"https://stock.nethercot.uk",
		"http://localhost",
		"http://127.0.0.1",
		"http://localhost:8000",
		"http://127.0.0.1:8000",
		"http://localhost:8080",
		"http://127.0.0.1:8080",
	]

app.add_middleware(
	CORSMiddleware,
	allow_origins=allow_origins,
	allow_methods=["*"],
	allow_headers=["*"],
)


class OHLCV(BaseModel):
	date: str
	open: float
	high: float
	low: float
	close: float
	volume: Optional[float] = None


class HistoryResponse(BaseModel):
	ticker: str
	data: List[OHLCV]


@app.get("/")
def root():
	return {
		"name": "Stock Correlation API",
		"status": "ok",
		"endpoints": [
			"/history?ticker=AAPL&start=2024-01-01&end=2024-03-01",
		],
	}


@app.get("/history")
def get_history(ticker: str, start: str, end: str):
	try:
		# Normalize incoming dates to YYYY-MM-DD accepting various formats
		def normalize_date(s: str) -> str:
			if not s:
				return s
			# If already ISO date, return as-is to avoid pandas warnings
			if isinstance(s, str) and len(s) == 10 and s[4] == '-' and s[7] == '-' and s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit():
				return s
			# Try dayfirst, then monthfirst
			for dayfirst in (True, False):
				try:
					dt = pd.to_datetime(s, dayfirst=dayfirst, errors="raise")
					return dt.strftime("%Y-%m-%d")
				except Exception:
					continue
			# Fallback: return original; yfinance may still handle
			return s

		start = normalize_date(start)
		end = normalize_date(end)

		# Be explicit with yfinance args to avoid API defaults changing
		df = yf.download(
			ticker,
			start=start,
			end=end,
			progress=False,
			auto_adjust=False,
			group_by="column",
			threads=True,
		)
		if df is None or df.empty:
			return {"ticker": ticker, "data": []}

		# Flatten index to column and normalize names robustly
		df = df.reset_index()
		# If MultiIndex columns, take the first level (field name), ignore ticker level
		if isinstance(df.columns, pd.MultiIndex):
			df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
		# Detect datetime-like column and rename to 'date' before lowercasing
		dt_col_name = None
		for col in df.columns:
			series = df[col]
			if pd.api.types.is_datetime64_any_dtype(series) or isinstance(series.iloc[0], (pd.Timestamp, datetime)):
				dt_col_name = col
				break
		if dt_col_name is not None and str(dt_col_name).lower() != "date":
			df = df.rename(columns={dt_col_name: "date"})
		# Now normalize names
		df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
		# Standardize common Yahoo names
		rename_map = {
			"adj_close": "adjclose",
			"adjclose": "adj_close",
		}
		df = df.rename(columns=rename_map)

		# Select available columns safely
		needed_cols = ["date", "open", "high", "low", "close"]
		optional_cols = ["volume"]
		for col in needed_cols:
			if col not in df.columns:
				# If any core OHLC column is missing, return empty set instead of 500
				return {"ticker": ticker, "data": []}

		# Drop rows with missing OHLC
		df = df.dropna(subset=["open", "high", "low", "close", "date"])  # type: ignore

		def to_date_str(x):
			if hasattr(x, "strftime"):
				return x.strftime("%Y-%m-%d")
			return str(x)

		def safe_float(x):
			try:
				f = float(x)
			except Exception:
				return None
			if math.isnan(f) or math.isinf(f):
				return None
			return f

		records: List[dict] = []
		for _, row in df.iterrows():
			o = safe_float(row["open"])  # type: ignore[index]
			h = safe_float(row["high"])  # type: ignore[index]
			l = safe_float(row["low"])   # type: ignore[index]
			c = safe_float(row["close"]) # type: ignore[index]
			v = safe_float(row["volume"]) if "volume" in df.columns else None  # type: ignore[index]
			date_str = to_date_str(row["date"])  # type: ignore[index]
			if o is None or h is None or l is None or c is None or not date_str:
				continue
			records.append({
				"date": date_str,
				"open": o,
				"high": h,
				"low": l,
				"close": c,
				"volume": v,
			})

		return {"ticker": ticker, "data": records}
	except Exception as e:
		# Do not leak internal error as 500; return structured message
		return {"ticker": ticker, "data": [], "error": str(e)}


if __name__ == "__main__":
	import uvicorn
	host = os.getenv("HOST", "0.0.0.0")
	port = int(os.getenv("PORT", "8000"))
	uvicorn.run(app, host=host, port=port)