# backend/main.py
from fastapi import FastAPI, HTTPException, Query
import yfinance as yf
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import pandas as pd
import math
import os
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import html
import re
import time


app = FastAPI()

# Logger
logger = logging.getLogger(__name__)
if not logger.handlers:
	logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

	
# Allow CORS origins to be configured via env var (comma-separated)
_env_origins = os.getenv("ALLOW_ORIGINS")
if _env_origins:
	allow_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
	# If wildcard present in env, collapse to "*"
	if any(o == "*" for o in allow_origins):
		allow_origins = ["*"]
else:
	# Default to permissive CORS to avoid cross-origin failures from static hosts
	allow_origins = ["*"]

app.add_middleware(
	CORSMiddleware,
	allow_origins=allow_origins,
	allow_methods=["*"],
	allow_headers=["*"],
    allow_credentials=False,
    max_age=86400,
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


class Suggestion(BaseModel):
	symbol: str
	name: str
	exchange: Optional[str] = None
	last: Optional[float] = None
	change_percent: Optional[float] = None
	alias_of: Optional[str] = None


SUGGESTION_CACHE_TTL = int(os.getenv("SUGGESTION_CACHE_TTL", "300"))
_suggestion_cache: dict[tuple[str, int], tuple[float, List[dict]]] = {}
_suggestion_session = requests.Session()
_suggestion_session.headers.update({
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
	"Accept-Language": "en-US,en;q=0.8",
	"Connection": "keep-alive",
	"Referer": "https://stooq.com/",
})
_suggestion_session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.4, status_forcelist=[429, 500, 502, 503, 504])))

_yahoo_suggestion_session = requests.Session()
_yahoo_suggestion_session.headers.update({
	"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
	"Accept": "application/json",
	"Accept-Language": "en-US,en;q=0.9",
	"Connection": "keep-alive",
	"Referer": "https://finance.yahoo.com/",
})
_yahoo_suggestion_session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.4, status_forcelist=[429, 500, 502, 503, 504])))

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
_TAG_RE = re.compile(r"<.*?>", re.S)
_EXCLUDE_EXCH: tuple[str, ...] = ()
_YAHOO_ALLOWED_TYPES = {
	"EQUITY",
	"ETF",
	"INDEX",
	"MUTUALFUND",
	"FUND",
	"FUTURE",
	"CRYPTOCURRENCY",
	"CURRENCY",
	"BOND",
}
_SUGGESTION_SYMBOL_REMAPS = {
	"BTC-USD": "BTC.V",
	"BTCUSD": "BTC.V",
	"BTC=F": "BTC.V",
	"XAUUSD=X": "XAUUSD",
	"GC=F": "XAUUSD",
	"US10Y": "INRTUS.M",
	"^TNX": "INRTUS.M",
}



def _strip_html(text: str) -> str:
	if not text:
		return ""
	clean = _TAG_RE.sub("", text)
	clean = html.unescape(clean)
	return clean.replace("\xa0", " ").strip()


def _parse_float(text: str) -> Optional[float]:
	clean = _strip_html(text)
	if not clean:
		return None
	clean = clean.replace(" ", "").replace(",", "")
	try:
		return float(clean)
	except (ValueError, TypeError):
		return None


def _parse_change_percent(text: str) -> Optional[float]:
	clean = _strip_html(text)
	if not clean:
		return None
	value = clean.replace(" ", "").replace(",", "")
	mult = 1.0
	if value.startswith("-"):
		mult = -1.0
	value = value.lstrip("+-")
	if value.endswith("%"):
		value = value[:-1]
	try:
		return float(value) * mult
	except (ValueError, TypeError):
		return None


def _remap_suggestion_symbol(symbol: str, quote: Optional[dict]) -> tuple[str, Optional[str]]:
	original = symbol or ""
	upper = original.upper()
	if upper in _SUGGESTION_SYMBOL_REMAPS:
		return _SUGGESTION_SYMBOL_REMAPS[upper], original
	info = quote or {}
	quote_type = (info.get("quoteType") or "").upper()
	if quote_type == "CRYPTOCURRENCY":
		if "-" in upper:
			base = upper.split("-")[0]
			if base and base.isalpha():
				return f"{base}.V", original
		if upper.endswith("=F"):
			base = upper[:-2]
			if base and base.isalpha():
				return f"{base}.V", original
	if quote_type == "CURRENCY" and upper.endswith("=X"):
		if upper == "XAUUSD=X":
			return "XAUUSD", original
	if quote_type == "INDEX" and upper.startswith("^"):
		if upper == "^TNX":
			return "INRTUS.M", original
	return original, None


def _compute_popularity_score(quote: dict, order: int) -> float:
	try:
		score_val = float(quote.get("score") or 0.0)
	except (TypeError, ValueError):
		score_val = 0.0
	qtype = (quote.get("quoteType") or "").upper()
	type_bonus = {
		"EQUITY": 500.0,
		"ETF": 350.0,
		"INDEX": 300.0,
		"CRYPTOCURRENCY": 280.0,
		"FUTURE": 260.0,
		"CURRENCY": 240.0,
		"MUTUALFUND": 200.0,
		"FUND": 180.0,
		"BOND": 150.0,
	}
	score_val += type_bonus.get(qtype, 120.0)
	score_val -= order * 0.01
	return score_val


def _fetch_stooq_html(query: str) -> str:
	if not query:
		return ""
	params = {"q": query}
	last_text = ""
	for _ in range(2):
		resp = _suggestion_session.get("https://stooq.com/db/l/", params=params, timeout=6)
		if resp.status_code >= 500:
			time.sleep(0.2)
			continue
		if resp.status_code >= 400:
			raise HTTPException(status_code=502, detail=f"Stooq responded with {resp.status_code}")
		text = resp.text or ""
		if text.strip():
			return text
		last_text = text
	return last_text


def _parse_stooq_rows(raw_html: str) -> List[dict]:
	if not raw_html:
		return []
	results: List[dict] = []
	for row_html in _ROW_RE.findall(raw_html):
		cells = _CELL_RE.findall(row_html)
		if len(cells) < 3:
			continue
		symbol_match = re.search(r">([^<]+)<", cells[0], re.S)
		symbol = _strip_html(symbol_match.group(1) if symbol_match else cells[0])
		name = _strip_html(cells[1])
		exchange = _strip_html(cells[2]) if len(cells) > 2 else ""
		if not symbol or not name:
			continue
		if exchange and any(token in exchange.lower() for token in _EXCLUDE_EXCH):
			continue
		entry = {
			"symbol": symbol.upper(),
			"name": name,
			"exchange": exchange or None,
			"last": _parse_float(cells[3]) if len(cells) > 3 else None,
			"change_percent": _parse_change_percent(cells[4]) if len(cells) > 4 else None,
		}
		results.append(entry)
	return results


def _fetch_yahoo_suggestions(query: str, limit: int) -> List[dict]:
	if not query:
		return []
	params = {
		"q": query,
		"quotesCount": max(limit * 2, 10),
		"newsCount": 0,
		"listsCount": 0,
		"enableFuzzyQuery": "false",
		"lang": "en-US",
		"region": "US",
		"quotesQueryId": "tss_match_phrase_query",
		"multiQuoteQueryId": "multi_quote_single_token",
	}
	resp = _yahoo_suggestion_session.get("https://query2.finance.yahoo.com/v1/finance/search", params=params, timeout=6)
	if resp.status_code >= 500:
		raise HTTPException(status_code=502, detail="Yahoo suggest unavailable")
	if resp.status_code >= 400:
		raise HTTPException(status_code=resp.status_code, detail="Yahoo suggest error")
	payload = resp.json() if resp.content else {}
	quotes = payload.get("quotes") or []
	seen: set[str] = set()
	results: List[dict] = []
	for order, quote in enumerate(quotes):
		raw_symbol = (quote.get("symbol") or "").strip()
		if not raw_symbol:
			continue
		preferred_symbol, alias_symbol = _remap_suggestion_symbol(raw_symbol, quote)
		symbol = preferred_symbol.upper()
		if not symbol or symbol in seen:
			continue
		qtype = (quote.get("quoteType") or "").upper()
		if qtype and _YAHOO_ALLOWED_TYPES and qtype not in _YAHOO_ALLOWED_TYPES:
			continue
		name = quote.get("shortname") or quote.get("longname") or quote.get("name") or symbol
		exchange = quote.get("exchDisp") or quote.get("fullExchangeName")
		last = quote.get("regularMarketPrice")
		change_pct = quote.get("regularMarketChangePercent")
		try:
			last_val = float(last)
		except (TypeError, ValueError):
			last_val = None
		try:
			chg_val = float(change_pct)
		except (TypeError, ValueError):
			chg_val = None
		item = {
			"symbol": symbol,
			"name": name,
			"exchange": exchange,
			"last": last_val,
			"change_percent": chg_val,
		}
		if alias_symbol and alias_symbol.upper() != symbol:
			item["alias_of"] = alias_symbol.upper()
		item["_score"] = _compute_popularity_score(quote, order)
		results.append(item)
		seen.add(symbol)
		if len(results) >= limit:
			break
	return results


def _fetch_stooq_suggestions(query: str, limit: int) -> List[dict]:
	base = query.strip()
	upper = base.upper()
	terms: List[str] = []
	for candidate in (base, upper):
		if candidate and candidate not in terms:
			terms.append(candidate)
	if upper and '.' not in upper and len(upper) <= 5:
		fallback = f"{upper}.US"
		if fallback not in terms:
			terms.append(fallback)
	seen = set()
	output: List[dict] = []
	for term in terms:
		if not term:
			continue
		try:
			html_text = _fetch_stooq_html(term)
		except HTTPException:
			raise
		except Exception as exc:
			logger.warning("Suggest fetch failed for %s: %s", term, exc)
			continue
		for item in _parse_stooq_rows(html_text):
			symbol = item.get("symbol")
			if not symbol or symbol in seen:
				continue
			seen.add(symbol)
			output.append(item)
			if len(output) >= limit:
				return output
	return output


def fetch_suggestions(query: str, limit: int) -> List[dict]:
	merged: dict[str, dict] = {}
	try:
		yahoo_results = _fetch_yahoo_suggestions(query, limit)
	except HTTPException:
		raise
	except Exception as exc:
		logger.warning("Yahoo suggestion fetch failed for %s: %s", query, exc)
	else:
		for item in yahoo_results:
			sym = (item.get("symbol") or "").upper()
			if not sym:
				continue
			item["symbol"] = sym
			merged[sym] = item
	try:
		stooq_results = _fetch_stooq_suggestions(query, limit)
	except HTTPException:
		raise
	except Exception as exc:
		logger.warning("Stooq suggestion fetch failed for %s: %s", query, exc)
	else:
		for item in stooq_results:
			sym = (item.get("symbol") or "").upper()
			if not sym or sym in merged:
				continue
			entry = dict(item)
			entry["symbol"] = sym
			entry["_score"] = -1.0
			merged[sym] = entry
	ordered = sorted(merged.values(), key=lambda x: x.get("_score", 0.0), reverse=True)
	out: List[dict] = []
	for item in ordered:
		item.pop("_score", None)
		out.append(item)
		if len(out) >= limit:
			break
	return out


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
		# Normalize some common aliases (US rates, gold) to provider symbols
		def normalize_ticker(sym: str) -> str:
			if not sym:
				return sym
			key = sym.strip().lower()
			aliases = {
				# Common typo for Stooq US interest rate index
				"intrus.m": "INRTUS.M",
				"us10y": "^TNX",  # 10Y Treasury yield index (approx x10)
				"10y": "^TNX",
				"^tnx": "^TNX",
				"us30y": "^TYX",  # 30Y Treasury yield index (approx x10)
				"30y": "^TYX",
				"^tyx": "^TYX",
				"gold": "XAUUSD=X",  # Gold spot in USD
				"xau": "XAUUSD=X",
				"xauusd": "XAUUSD=X",
				"xauusd=x": "XAUUSD=X",
				"gc=f": "GC=F",  # Gold futures continuous
			}
			return aliases.get(key, sym)

		orig_ticker = ticker
		ticker = normalize_ticker(ticker)

		def build_symbol_variants(user_sym: str, normalized_sym: str) -> list[str]:
			key_user = (user_sym or "").strip().lower()
			key_norm = (normalized_sym or "").strip().lower()
			variants = []
			# Always try the normalized symbol first
			if normalized_sym:
				variants.append(normalized_sym)
			# Gold variants
			if key_user in {"gold", "xau", "xauusd"} or key_norm in {"xauusd=x", "gc=f", "xauusd"}:
				# Yahoo spot & futures, ETF, and Stooq spot symbol
				for v in ["XAUUSD=X", "GC=F", "GLD", "XAUUSD"]:
					if v not in variants:
						variants.append(v)
			# US rates variants (use ETFs as fallbacks when indices blocked)
			if key_user in {"us10y", "10y"} or key_norm == "^tnx":
				# Yahoo index, ETF proxy, and Stooq interest rate index
				for v in ["^TNX", "IEF", "INRTUS.M"]:
					if v not in variants:
						variants.append(v)
			if key_user in {"us30y", "30y"} or key_norm == "^tyx":
				for v in ["^TYX", "TLT"]:
					if v not in variants:
						variants.append(v)
			# Ensure original user symbol is also tried if distinct
			if user_sym and user_sym not in variants:
				variants.append(user_sym)
			return variants

		symbol_variants = build_symbol_variants(orig_ticker, ticker)
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

		# Helpers
		def normalize_ohlcv_df(df: pd.DataFrame) -> pd.DataFrame:
			if df is None or df.empty:
				return pd.DataFrame()
			df = df.reset_index()
			if isinstance(df.columns, pd.MultiIndex):
				df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
			# Find datetime column and name it 'date'
			dt_col_name = None
			if len(df.columns) > 0:
				for col in df.columns:
					series = df[col]
					# Guard against empty series access
					is_dt = pd.api.types.is_datetime64_any_dtype(series)
					if not is_dt and len(series) > 0:
						is_dt = isinstance(series.iloc[0], (pd.Timestamp, datetime))
					if is_dt:
						dt_col_name = col
						break
			if dt_col_name is not None and str(dt_col_name).lower() != "date":
				df = df.rename(columns={dt_col_name: "date"})
			# Lowercase normalize
			df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
			# Standardize common variants
			rename_map = {
				"adj_close": "adjclose",
				"adjclose": "adj_close",
			}
			df = df.rename(columns=rename_map)
			return df

		def filter_date_range(df: pd.DataFrame, start_s: str, end_s: str) -> pd.DataFrame:
			if df.empty:
				return df
			try:
				s = pd.to_datetime(start_s)
				e = pd.to_datetime(end_s)
				if "date" in df.columns:
					# Prefer explicit YYYY-MM-DD parsing when the strings match ISO format to avoid warnings
					def _parse_dates(col: pd.Series) -> pd.Series:
						obj = col.astype("string").replace({pd.NA: None, "NaT": None, "nat": None, "nan": None})
						sample = obj.dropna().head(12)
				
						def try_format(fmt: str) -> Optional[pd.Series]:
							try:
								parsed = pd.to_datetime(obj, format=fmt, errors="coerce")
								if sample.empty or parsed.loc[sample.index].notna().all():
									return parsed
							except Exception:
								return None
							return None

						# Try common formats explicitly to avoid pandas format inference warnings.
						for fmt, pattern in [
							("%Y-%m-%d", r"^\d{4}-\d{2}-\d{2}$"),
							("%Y-%m-%d %H:%M:%S", r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"),
							("%Y/%m/%d", r"^\d{4}/\d{2}/\d{2}$"),
							("%m/%d/%Y", r"^\d{2}/\d{2}/\d{4}$"),
							("%d/%m/%Y", r"^\d{2}/\d{2}/\d{4}$"),
						]:
							if sample.empty:
								parsed = try_format(fmt)
								if parsed is not None:
									return parsed
							else:
								if sample.str.fullmatch(pattern).all():
									parsed = try_format(fmt)
									if parsed is not None:
										return parsed

						# Fallback: parse item-by-item to avoid global inference warnings.
						def parse_scalar(val: Optional[str]):
							if val is None:
								return pd.NaT
							text = val.strip()
							if not text or text.lower() in {"nat", "nan"}:
								return pd.NaT
							for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
								try:
									return datetime.strptime(text, fmt)
								except ValueError:
									continue
							try:
								return pd.Timestamp(text)
							except Exception:
								return pd.NaT

						parsed_list = [parse_scalar(v) for v in obj]
						return pd.Series(parsed_list, index=col.index, dtype="datetime64[ns]")
					df["date"] = _parse_dates(df["date"])  # type: ignore
					df = df[(df["date"] >= s) & (df["date"] <= e)]
				return df
			except Exception:
				return df

		def fetch_yahoo(symbol: str, s: str, e: str) -> pd.DataFrame:
			try:
				logger.info(f"/history: fetching from Yahoo for {symbol} {s}→{e}")
				# Use a session with retries and a browser UA to avoid simple bot blocks
				session = requests.Session()
				session.headers.update({
					"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
					"Accept": "*/*",
					"Accept-Encoding": "gzip, deflate, br",
					"Connection": "keep-alive",
				})
				retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
				session.mount("https://", HTTPAdapter(max_retries=retry))
				df = yf.download(
					symbol,
					start=s,
					end=e,
					progress=False,
					auto_adjust=False,
					group_by="column",
					threads=False,
					session=session,
				)
				df = normalize_ohlcv_df(df)
				return df
			except Exception as ex:
				logger.warning(f"Yahoo fetch failed for {symbol}: {ex}")
				return pd.DataFrame()

		def fetch_stooq(symbol: str, s: str, e: str) -> pd.DataFrame:
			# Try multiple symbol variants for Stooq (common: '.us' for US tickers)
			candidates = []
			base = symbol.lower()
			candidates.append(base)
			if not base.endswith('.us'):
				candidates.append(base + '.us')
			for cand in candidates:
				try:
					url = f"https://stooq.com/q/d/l/?s={cand}&i=d"
					logger.info(f"/history: fetching from Stooq for {symbol} via {url}")
					resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
					if resp.status_code != 200:
						logger.warning(f"Stooq HTTP {resp.status_code} for {symbol} ({cand})")
						continue
					text = resp.text.strip()
					if not text or text.lower().startswith("no data"):
						continue
					# Read CSV from text
					from io import StringIO
					df = pd.read_csv(StringIO(text), header=None)
					# Stooq daily CSV is usually: Date,Open,High,Low,Close,Volume
					if df.shape[1] >= 5:
						cols = ["date", "open", "high", "low", "close"] + (["volume"] if df.shape[1] >= 6 else [])
						df.columns = cols + [f"extra{i}" for i in range(df.shape[1]-len(cols))]
						# Drop any extra columns beyond volume
						df = df[cols]
					else:
						# Try default parser if shape unexpected
						df = pd.read_csv(StringIO(text))
					# Normalize columns and date range
					df.columns = [str(c).strip().lower() for c in df.columns]
					if "date" not in df.columns and "data" in df.columns:
						df = df.rename(columns={"data": "date"})
					df = normalize_ohlcv_df(df)
					df = filter_date_range(df, s, e)
					if df is not None and not df.empty:
						return df
				except Exception as ex:
					logger.warning(f"Stooq fetch failed for {symbol} ({cand}): {ex}")
					continue
			return pd.DataFrame()

		# Decide provider order (prefer Stooq by default to avoid Yahoo blocks on some hosts)
		providers_env = os.getenv("PROVIDERS", "stooq,yahoo")
		providers = [p.strip().lower() for p in providers_env.split(",") if p.strip()]
		# If the normalized ticker requires Yahoo (e.g., '^' indices or FX '=')
		# then prefer Yahoo first for this request regardless of default order
		if ticker and (ticker.startswith('^') or '=' in ticker):
			providers = ["yahoo"] + [p for p in providers if p != "yahoo"]
		if not providers:
			providers = ["yahoo", "stooq"]

		df = pd.DataFrame()
		used_symbol: Optional[str] = None
		errors: List[str] = []
		for p in providers:
			found_for_provider = False
			for sym in symbol_variants:
				if p == "yahoo":
					df = fetch_yahoo(sym, start, end)
				elif p == "stooq":
					df = fetch_stooq(sym, start, end)
				else:
					logger.warning(f"Unknown provider '{p}' ignored")
					continue
				if df is not None and not df.empty:
					used_provider = p
					used_symbol = sym
					found_for_provider = True
					break
			if found_for_provider:
				break
			else:
				errors.append(f"{p}: no data")
		else:
			used_provider = None  # type: ignore[assignment]

		# If still empty, return graceful error
		if df is None or df.empty:
			return {"ticker": ticker, "data": [], "error": "; ".join(errors) or "no data"}

		# Select available columns safely
		needed_cols = ["date", "open", "high", "low", "close"]
		for col in needed_cols:
			if col not in df.columns:
				logger.warning(f"Missing column '{col}' after provider normalization; returning empty result")
				return {"ticker": ticker, "data": [], "provider": used_provider}

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
			o = safe_float(row.get("open"))
			h = safe_float(row.get("high"))
			l = safe_float(row.get("low"))
			c = safe_float(row.get("close"))
			v = safe_float(row.get("volume")) if "volume" in df.columns else None
			date_val = row.get("date")
			date_str = to_date_str(date_val) if date_val is not None else ""
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

		result = {"ticker": orig_ticker, "data": records, "provider": used_provider}
		if used_symbol and used_symbol != orig_ticker:
			result["provider_symbol"] = used_symbol
		return result
	except Exception as e:
		# Do not leak internal error as 500; return structured message
		logger.exception(f"/history failed for {ticker}: {e}")
		return {"ticker": orig_ticker if 'orig_ticker' in locals() else ticker, "data": [], "error": str(e)}


@app.get("/suggest")
def suggest(q: str = Query(..., min_length=1, max_length=24), limit: int = Query(12, ge=1, le=40)):
	key = (q.lower(), limit)
	now = time.time()
	cached = _suggestion_cache.get(key)
	if cached and now - cached[0] < SUGGESTION_CACHE_TTL:
		return {"query": q, "data": cached[1], "cached": True}
	try:
		items = fetch_suggestions(q, limit)
	except HTTPException:
		raise
	except Exception as exc:
		logger.warning("Suggestion lookup failed for %s: %s", q, exc)
		raise HTTPException(status_code=502, detail="Suggestion lookup failed")
	validated = [Suggestion(**item).dict() for item in items]
	_suggestion_cache[key] = (now, validated)
	return {"query": q, "data": validated}


if __name__ == "__main__":
	import uvicorn
	host = os.getenv("HOST", "0.0.0.0")
	port = int(os.getenv("PORT", "8000"))
	uvicorn.run(app, host=host, port=port)