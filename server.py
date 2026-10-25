"""Tadawul MCP connector: Saudi Exchange market data, portfolio and watchlist tools.

Market data comes from Yahoo Finance via `yfinance` (Saudi tickers are 4 digits + ".SR",
e.g. 2222.SR = Saudi Aramco). Data is unofficial and may be delayed.
Portfolio/watchlist are stored in a local SQLite file (single user, no auth).
"""
import os
import sqlite3
import datetime as dt
from contextlib import closing

import yfinance as yf
from mcp.server.fastmcp import FastMCP

DB_PATH = os.environ.get("TADAWUL_DB", "tadawul.db")
DATABASE_URL = os.environ.get("DATABASE_URL")  # Postgres if set, else local SQLite
MCP_SECRET = os.environ.get("MCP_SECRET")      # makes the endpoint /mcp/<secret>

if DATABASE_URL:
    import psycopg
    from psycopg.rows import dict_row

mcp = FastMCP(
    "Tadawul",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
    streamable_http_path=f"/mcp/{MCP_SECRET}" if MCP_SECRET else "/mcp",
)

# Small built-in directory for fast name -> ticker matching (extend freely).
COMPANIES = {
    "2222.SR": "Saudi Arabian Oil Co (Aramco)",
    "1120.SR": "Al Rajhi Bank",
    "1180.SR": "Saudi National Bank (SNB)",
    "2010.SR": "SABIC",
    "7010.SR": "stc (Saudi Telecom)",
    "1211.SR": "Maaden",
    "2082.SR": "ACWA Power",
    "5110.SR": "Saudi Electricity Co",
    "4013.SR": "Dr. Sulaiman Al Habib Medical",
    "1150.SR": "Alinma Bank",
    "1010.SR": "Riyad Bank",
    "2280.SR": "Almarai",
    "4030.SR": "Bahri",
    "4190.SR": "Jarir Marketing",
    "2350.SR": "Saudi Kayan",
    "1140.SR": "Bank Albilad",
    "1060.SR": "Saudi Awwal Bank (SAB)",
    "7203.SR": "Elm Company",
}


def q(sql: str, params: tuple = (), fetch: bool = False):
    """Run one statement on Postgres (DATABASE_URL) or SQLite. Use ? placeholders."""
    if DATABASE_URL:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            cur = c.execute(sql.replace("?", "%s"), params)
            return cur.fetchall() if fetch else None
    with closing(sqlite3.connect(DB_PATH)) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        c.commit()
        return rows


def init_schema():
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    q(f"""CREATE TABLE IF NOT EXISTS trades(
        id {pk}, portfolio TEXT NOT NULL, ticker TEXT NOT NULL,
        side TEXT NOT NULL, quantity DOUBLE PRECISION NOT NULL,
        price DOUBLE PRECISION NOT NULL, fees DOUBLE PRECISION NOT NULL DEFAULT 0,
        trade_date TEXT NOT NULL)""")
    q("CREATE TABLE IF NOT EXISTS watchlist(ticker TEXT PRIMARY KEY, added TEXT NOT NULL)")


def sym(ticker: str) -> str:
    t = ticker.strip().upper()
    if t.endswith(".SR"):
        return t
    return f"{t}.SR" if t.isdigit() else t


def _quote(ticker: str) -> dict:
    t = sym(ticker)
    try:
        fi = yf.Ticker(t).fast_info
        last = fi["last_price"]
        prev = fi["previous_close"]
        return {
            "ticker": t,
            "name": COMPANIES.get(t),
            "price": round(last, 2) if last else None,
            "previous_close": round(prev, 2) if prev else None,
            "change_pct": round((last - prev) / prev * 100, 2) if last and prev else None,
            "year_high": fi["year_high"],
            "year_low": fi["year_low"],
            "market_cap": fi["market_cap"],
            "currency": "SAR",
        }
    except Exception as e:  # noqa: BLE001
        return {"ticker": t, "error": f"quote unavailable: {e}"}


@mcp.tool()
def get_overview() -> str:
    """Start here. Explains what this connector covers and which tool to use for what."""
    return (
        "Tadawul connector: Saudi Exchange (Tadawul) stocks, prices in SAR. Tickers are 4-digit "
        "codes (e.g. 2222 = Aramco, 1120 = Al Rajhi); '.SR' is added automatically. "
        "Use find_companies to resolve names. get_quote / get_price_history / get_fundamentals "
        "for market data. get_portfolio, add_holding, sell_holding for the user's portfolio. "
        "get_watchlist / update_watchlist for the watchlist. Data is unofficial and may be delayed."
    )


@mcp.tool()
def find_companies(query: str) -> list[dict]:
    """Match a company name, abbreviation or partial ticker to Tadawul tickers. Use before any ticker lookup."""
    q = query.strip().lower()
    hits = [
        {"ticker": t, "name": n}
        for t, n in COMPANIES.items()
        if q in n.lower() or q in t.lower()
    ]
    if not hits:
        try:
            for r in yf.Search(query, max_results=10).quotes:
                s = r.get("symbol", "")
                if s.endswith(".SR"):
                    hits.append({"ticker": s, "name": r.get("shortname") or r.get("longname")})
        except Exception:  # noqa: BLE001
            pass
    return hits[:10]


@mcp.tool()
def get_quote(tickers: list[str]) -> list[dict]:
    """Latest price, daily change %, 52-week range and market cap for one or more Tadawul tickers."""
    return [_quote(t) for t in tickers[:20]]


@mcp.tool()
def get_price_history(ticker: str, period: str = "6mo", interval: str = "1d") -> dict:
    """OHLCV history. period: 1mo, 3mo, 6mo, 1y, 5y, max. interval: 1d, 1wk, 1mo."""
    t = sym(ticker)
    df = yf.Ticker(t).history(period=period, interval=interval)
    if df.empty:
        return {"ticker": t, "error": "no data"}
    rows = [
        [d.strftime("%Y-%m-%d"), round(r.Open, 2), round(r.High, 2), round(r.Low, 2),
         round(r.Close, 2), int(r.Volume)]
        for d, r in df.iterrows()
    ]
    return {"ticker": t, "columns": ["date", "open", "high", "low", "close", "volume"], "rows": rows[-250:]}


@mcp.tool()
def get_fundamentals(ticker: str) -> dict:
    """Valuation and financial snapshot: P/E, P/B, EPS, dividend yield, ROE, margins, sector."""
    t = sym(ticker)
    info = yf.Ticker(t).info or {}
    keys = [
        "longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE",
        "priceToBook", "trailingEps", "dividendYield", "dividendRate", "returnOnEquity",
        "profitMargins", "totalRevenue", "debtToEquity", "beta",
    ]
    return {"ticker": t, **{k: info.get(k) for k in keys}}


@mcp.tool()
def add_holding(ticker: str, quantity: float, price: float, portfolio: str = "main",
                fees: float = 0, trade_date: str | None = None) -> dict:
    """Record a BUY the user made. Only call when the user explicitly asks to record a purchase."""
    t = sym(ticker)
    q("INSERT INTO trades(portfolio,ticker,side,quantity,price,fees,trade_date) VALUES(?,?,?,?,?,?,?)",
      (portfolio, t, "BUY", quantity, price, fees, trade_date or dt.date.today().isoformat()))
    return {"recorded": f"BUY {quantity} {t} @ {price} SAR", "portfolio": portfolio}


@mcp.tool()
def sell_holding(ticker: str, quantity: float, price: float, portfolio: str = "main",
                 fees: float = 0, trade_date: str | None = None) -> dict:
    """Record a SELL the user made. Only call when the user explicitly asks to record a sale."""
    t = sym(ticker)
    pos = _positions(portfolio).get(t)
    if not pos or pos["quantity"] < quantity:
        return {"error": f"cannot sell {quantity}: only {pos['quantity'] if pos else 0} held"}
    q("INSERT INTO trades(portfolio,ticker,side,quantity,price,fees,trade_date) VALUES(?,?,?,?,?,?,?)",
      (portfolio, t, "SELL", quantity, price, fees, trade_date or dt.date.today().isoformat()))
    return {"recorded": f"SELL {quantity} {t} @ {price} SAR", "portfolio": portfolio}


def _positions(portfolio: str) -> dict:
    """Average-cost positions and realized P&L from the trade log."""
    pos: dict[str, dict] = {}
    rows = q("SELECT * FROM trades WHERE portfolio=? ORDER BY id", (portfolio,), fetch=True)
    for r in rows:
        p = pos.setdefault(r["ticker"], {"quantity": 0.0, "cost": 0.0, "realized": 0.0})
        if r["side"] == "BUY":
            p["quantity"] += r["quantity"]
            p["cost"] += r["quantity"] * r["price"] + r["fees"]
        else:
            avg = p["cost"] / p["quantity"] if p["quantity"] else 0
            p["cost"] -= avg * r["quantity"]
            p["quantity"] -= r["quantity"]
            p["realized"] += (r["price"] * r["quantity"] - r["fees"]) - avg * r["quantity"]
    return {t: p for t, p in pos.items() if p["quantity"] > 1e-9 or abs(p["realized"]) > 1e-9}


@mcp.tool()
def get_portfolio(portfolio: str = "main") -> dict:
    """The user's holdings with live prices, market value, unrealized and realized P&L in SAR."""
    out, total_val, total_cost, total_real = [], 0.0, 0.0, 0.0
    for t, p in _positions(portfolio).items():
        total_real += p["realized"]
        if p["quantity"] <= 1e-9:
            continue
        price = _quote(t).get("price")
        val = price * p["quantity"] if price else None
        out.append({
            "ticker": t, "name": COMPANIES.get(t), "quantity": p["quantity"],
            "avg_cost": round(p["cost"] / p["quantity"], 2), "price": price,
            "market_value": round(val, 2) if val else None,
            "unrealized_pl": round(val - p["cost"], 2) if val else None,
            "unrealized_pl_pct": round((val / p["cost"] - 1) * 100, 2) if val and p["cost"] else None,
        })
        total_cost += p["cost"]
        total_val += val or 0
    return {
        "portfolio": portfolio, "currency": "SAR", "holdings": out,
        "total_cost": round(total_cost, 2), "total_value": round(total_val, 2),
        "unrealized_pl": round(total_val - total_cost, 2), "realized_pl": round(total_real, 2),
    }


@mcp.tool()
def get_watchlist() -> list[dict]:
    """The user's watchlist with live prices."""
    tickers = [r["ticker"] for r in q("SELECT ticker FROM watchlist ORDER BY added", fetch=True)]
    return [_quote(t) for t in tickers]


@mcp.tool()
def update_watchlist(ticker: str, action: str = "add") -> dict:
    """Add or remove a ticker from the watchlist. action: 'add' or 'remove'."""
    t = sym(ticker)
    if action == "remove":
        q("DELETE FROM watchlist WHERE ticker=?", (t,))
    else:
        q("INSERT INTO watchlist(ticker,added) VALUES(?,?) ON CONFLICT(ticker) DO NOTHING",
          (t, dt.datetime.utcnow().isoformat()))
    return {"ticker": t, "action": action, "ok": True}


init_schema()

if __name__ == "__main__":
    if not MCP_SECRET:
        print("WARNING: MCP_SECRET not set; endpoint is unprotected at /mcp")
    mcp.run(transport="streamable-http")
