# CoinW Pattern Scanner

A runnable CoinW-only, read-only perpetual futures structural scanner. **No simulated market data, trade execution, login, or private API keys.**

## Architecture

- Next.js App Router frontend on port 3000; all browser calls use `/api/...` relative paths.
- Next.js server-side reverse proxy to Python FastAPI (`BACKEND_URL`).
- FastAPI scanner task, SQLite snapshot storage, and Python deterministic pattern engine.
- Scanner fetches CoinW all-contract tickers and selects top 50 USDT linear perpetual contracts by the **raw CoinW `total_volume` metric**. Documentation does not define the unit or precise time window, so this is **not** represented as USDT turnover. Set `MIN_COINW_VOLUME` in the same raw unit.
- Klines use official `currencyCode`, `granularity` (15m=2, 1H=3, 4H=4), `klineType=0`, `limit=300`. They are validated and incomplete bars excluded. Data unavailability remains visible.

## Run with Docker

```bash
cp .env.example .env
docker compose up --build -d
# Dashboard: http://localhost:3000
# Scanner health inside container: docker compose exec scanner python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"
docker compose logs -f scanner
```

Docker and internet access must be available on your own machine. Initial scan may take several minutes. No CoinW API access means no invented results.

## Run without Docker

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
DATABASE_PATH=./scanner.sqlite uvicorn main:app --host 0.0.0.0 --port 8000
# in another terminal, from repository root:
cd frontend
npm install
BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

On Windows PowerShell use `$env:BACKEND_URL='http://127.0.0.1:8000'` before `npm run dev`.

## Share via temporary HTTPS

Install Cloudflare `cloudflared` (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/), then:

```bash
./scripts/tunnel.sh
# or: cloudflared tunnel --url http://localhost:3000
```

Copy the printed `https://...trycloudflare.com` address. No Cloudflare account or custom domain required for Quick Tunnels. **The URL is temporary, changes on restart, and only works while both the web service and tunnel run.** Do not publicly expose the FastAPI port. The tunnel shares the full dashboard without login. Cloudflare Quick Tunnel is intended for testing, not production availability.

## Persistent HTTPS

Deploy on a Docker-capable VPS with Docker Compose and a managed HTTPS reverse proxy, or use Railway: create two services from the same repository, `scanner` with root directory `/backend` and Dockerfile, `web` with root directory `/frontend` and Dockerfile. Add a persistent volume at `/data` to scanner. Set `DATABASE_PATH=/data/scanner.sqlite` on scanner; set `BACKEND_URL=http://scanner.railway.internal:8000` on web, replacing `scanner` with the actual Railway service name. Expose port 3000 publicly on the web service only and use Railway's generated `*.up.railway.app` HTTPS domain. Verify internal service DNS and health checks in Railway before use. **Do not run multiple scanner replicas against one SQLite database.** Persistent storage and always-on background scanning require a hosting plan that supports long-lived services.

## Detection and scoring

- Swing pivots require 3 closed candles to the right; no forward-looking pivots.
- Zones cluster pivots within 0.65 × ATR(14); band half-width = 0.4 × ATR; minimum 2 touches. Strength includes touch count and recency.
- Forming support/resistance tests are within roughly 1.1 ATR of confirmed zones.
- Consolidation checks a 30-bar range against a prior 30-bar range. Breakout watch requires volatility contraction and proximity to a prior boundary; it never claims confirmation before a close.
- Breakout retest requires a closed breakout beyond a 30-bar historical boundary by 0.15 ATR, then a retest within 8 bars; an adverse move beyond 2 ATR invalidates the candidate. Historical search is limited to the most recent 12 bars.
- **Score weights:** clarity 25%, zone strength 25%, structural proximity 20%, volume context 10%, volatility context 10%, data completeness 10%. Score is 0–100 and **not** a win probability. Scores are heuristic and not backtested.
- Duplicate detection is limited by stable symbol/timeframe/pattern/status keys. Each successful scan atomically replaces the snapshot. No look-ahead candles are used. Historical invalidated states are not persisted as separate records in this MVP.

## Data and operational cautions

Official docs: https://www.coinw.com/api-doc/en/futures-trading/market/get-k-line-of-an-instrument and https://www.coinw.com/api-doc/en/futures-trading/market/get-last-trade-summary-of-all-instruments . Published limits: kline 20 requests/2 seconds/IP, all tickers 5 requests/second/IP, shared global group 30 requests/second/IP. Concurrency is capped at 3 and retries use exponential backoff. The environment where this project was assembled could not resolve `api.coinw.com`; validate live payloads on your deployment before relying on scans. The app deliberately does not fallback to other exchanges.

## Checks

```bash
cd backend && python -m pytest -q
cd ../frontend && npm install && npm run typecheck && npm run build
```

Health: `GET /health` on internal API. Public dashboard: `GET /api/setups`, detail: `GET /api/setup/{id}`. Public API limited to 120 requests/minute/client IP at the backend. When deployed behind a reverse proxy, configure trusted forwarded IP handling separately; the default limiter sees the proxy IP. Production deployments should also enforce provider-side WAF/rate limiting.

## Easiest Railway setup (one service, no terminal)

This repository now includes a **root Dockerfile** and `railway.json` to run the website and Python scanner in **one Railway service**. No separate backend service or private networking is required.

1. Create a **private** GitHub repository and upload the *contents* of this project folder (not the ZIP itself) via GitHub's **Add file → Upload files** interface. GitHub's web upload may not preserve empty folders, which is fine here.
2. In https://railway.com/new choose **Deploy from GitHub repo**, connect your account, and select the repository. Railway detects the root `railway.json` / `Dockerfile`.
3. In Railway service **Settings → Networking**, choose **Generate Domain**. The resulting `*.up.railway.app` address is the shareable HTTPS URL.
4. For persistence, in Railway add a **Volume** mounted at `/data` (scanner SQLite database). If you skip this, data may be lost on redeployment and the scanner must rebuild it.
5. Check **Deploy Logs** and then open the public URL. Allow a few minutes for the first CoinW scan. A network error must be shown as unavailable, not as sample market data.

Important: Railway does not deploy arbitrary ZIP files directly from a chat. A truly one-click public template requires publishing a real GitHub repository or Railway template first. This project has not been deployed or live-API-verified from this environment. Hosting costs and account requirements depend on Railway's current plan.
