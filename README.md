# Tadawul MCP connector

Saudi Exchange (Tadawul) tools for Claude: quotes, history, fundamentals, portfolio, watchlist.

## Environment variables
- MCP_SECRET   random string; endpoint becomes /mcp/<MCP_SECRET> (keeps strangers out)
- DATABASE_URL Postgres connection string (portfolio persists). If unset, uses local SQLite.

## Run locally
    pip install -r requirements.txt
    MCP_SECRET=test python server.py     # http://localhost:8000/mcp/test

## Deploy free on Render
1. Push this folder to a GitHub repo.
2. Create a free Postgres (Neon or Supabase) and copy its connection string.
3. Render > New > Blueprint > pick the repo (uses render.yaml). Paste DATABASE_URL when asked.
4. Open the service's Environment tab, copy MCP_SECRET.
5. Claude > Settings > Connectors > Add custom connector:
   https://YOUR-APP.onrender.com/mcp/<MCP_SECRET>

Data: Yahoo Finance via yfinance (unofficial, may be delayed or blocked from cloud IPs).
