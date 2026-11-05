import asyncio, json, logging, os, sqlite3, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from coinw import CoinW, CoinWError
from engine import detect
logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))
log=logging.getLogger('scanner')
DB=Path(os.getenv('DATABASE_PATH','/data/scanner.sqlite')); DB.parent.mkdir(parents=True,exist_ok=True)
INTERVAL=int(os.getenv('SCAN_INTERVAL_SECONDS','900'))
PAIR_LIMIT=min(200,max(1,int(os.getenv('PAIR_LIMIT','50'))))
MIN_VOLUME=float(os.getenv('MIN_COINW_VOLUME','0'))
lock=asyncio.Lock(); scanner_task=None

def db():
    con=sqlite3.connect(DB,timeout=20);con.row_factory=sqlite3.Row;con.execute('PRAGMA journal_mode=WAL');return con

def initialize():
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS setups (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated INTEGER NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS candles (symbol TEXT, timeframe TEXT, payload TEXT NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY(symbol,timeframe))')
        con.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')

def meta():
    with db() as con: return {r['key']:r['value'] for r in con.execute('SELECT * FROM meta')}

def setmeta(con,key,value): con.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(key,str(value)))

async def scan():
    if lock.locked(): return
    async with lock:
        started=int(time.time()); success=0;errors=[];results=[];candles=[]
        coinw=CoinW(os.getenv('COINW_BASE_URL','https://api.coinw.com'))
        try:
            pairs=await coinw.symbols(PAIR_LIMIT,MIN_VOLUME)
            if not pairs: raise CoinWError('CoinW returned no eligible USDT perpetual instruments')
            async def work(pair,tf):
                nonlocal success
                try:
                    c=await coinw.candles(pair['base'],tf)
                    if len(c)<65: raise CoinWError(f'Only {len(c)} valid closed candles')
                    found=detect(c,pair['symbol'],tf)
                    candles.append((pair['symbol'],tf,json.dumps([x.__dict__ for x in c])))
                    results.extend(found);success+=1
                except Exception as e: errors.append(f"{pair['symbol']} {tf}: {e}")
            await asyncio.gather(*(work(p,tf) for p in pairs for tf in ('15m','1H','4H')))
            if success==0: raise CoinWError('; '.join(errors[:3]) or 'No successful market requests')
            with db() as con:
                con.execute('DELETE FROM setups')
                con.executemany('INSERT INTO setups VALUES (?,?,?)',[(x['id'],json.dumps(x),started) for x in results])
                con.executemany('INSERT OR REPLACE INTO candles VALUES (?,?,?,?)',[(s,t,p,started) for s,t,p in candles])
                setmeta(con,'last_success',started);setmeta(con,'pairs_scanned',len(set(s for s,_,_ in candles)))
                setmeta(con,'timeframes_scanned',success);setmeta(con,'last_error','; '.join(errors[:8]))
            log.info('scan complete: %s timeframes %s setups %s errors',success,len(results),len(errors))
        except Exception as e:
            log.exception('scan failed')
            with db() as con: setmeta(con,'last_error',str(e)[:1200])
        finally: await coinw.close()

async def loop():
    while True:
        await scan()
        # Wait for the next 15-minute UTC boundary plus 10 seconds, never too fast.
        now=time.time();wait=max(INTERVAL,900-(now%900)+10) if INTERVAL>=900 else INTERVAL
        await asyncio.sleep(wait)

@asynccontextmanager
async def lifespan(app):
    initialize(); task=asyncio.create_task(loop())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass

app=FastAPI(title='CoinW Pattern Scanner API',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
rate={}
@app.middleware('http')
async def limiter(request:Request,call_next):
    if request.url.path.startswith('/api/'):
        ip=request.client.host if request.client else 'unknown';now=time.monotonic()
        bucket=[t for t in rate.get(ip,[]) if now-t<60]
        if len(bucket)>=120: return JSONResponse({'detail':'Rate limit exceeded'},status_code=429)
        bucket.append(now);rate[ip]=bucket
        if len(rate)>10000: rate.clear()
    return await call_next(request)

@app.get('/health')
def health():
    m=meta();return {'status':'ok' if m.get('last_success') else 'waiting_for_data','last_success':m.get('last_success'),'last_error':m.get('last_error')}

@app.get('/api/setups')
def setups(timeframe:str|None=Query(None,pattern='^(15m|1H|4H)$'),status:str|None=Query(None,pattern='^(forming|confirmed|invalidated)$'),pattern:str|None=Query(None,max_length=60),q:str|None=Query(None,max_length=40),sort:str=Query('score',pattern='^(score|updated)$')):
    with db() as con: items=[json.loads(r['payload']) for r in con.execute('SELECT payload FROM setups')]
    if timeframe:items=[x for x in items if x['timeframe']==timeframe]
    if status:items=[x for x in items if x['status']==status]
    if pattern:items=[x for x in items if pattern.lower() in x['pattern'].lower()]
    if q:items=[x for x in items if q.upper() in x['symbol']]
    items.sort(key=lambda x:(x['status']!='forming',-x['score'] if sort=='score' else -x['updated_at']))
    m=meta();return {'items':items,'summary':{'pairs_scanned':int(m.get('pairs_scanned','0')),'active_setups':len([x for x in items if x['status'] in ('forming','confirmed')]),'last_success':int(m['last_success']) if m.get('last_success') else None,'last_error':m.get('last_error') or None,'source':'CoinW perpetual futures'}}

@app.get('/api/setup/{setup_id}')
def setup(setup_id:str):
    if len(setup_id)>160:raise HTTPException(400,'Invalid id')
    with db() as con:
        r=con.execute('SELECT payload FROM setups WHERE id=?',(setup_id,)).fetchone()
        if not r:raise HTTPException(404,'Setup not found or expired')
        item=json.loads(r['payload'])
        c=con.execute('SELECT payload FROM candles WHERE symbol=? AND timeframe=?',(item['symbol'],item['timeframe'])).fetchone()
    return {'setup':item,'candles':json.loads(c['payload']) if c else [],'source':'CoinW'}
