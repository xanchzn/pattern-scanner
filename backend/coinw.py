import asyncio, logging, math, time
import httpx
from engine import normalize, GRANULARITY
log=logging.getLogger(__name__)
class CoinWError(Exception): pass
class CoinW:
    def __init__(self,base='https://api.coinw.com'):
        self.base=base.rstrip('/'); self.sem=asyncio.Semaphore(3)
        self.client=httpx.AsyncClient(timeout=14,follow_redirects=False)
    async def close(self): await self.client.aclose()
    async def get(self,path,params=None):
        async with self.sem:
            for attempt in range(4):
                try:
                    response=await self.client.get(self.base+path,params=params)
                    response.raise_for_status()
                    payload=response.json()
                    if not isinstance(payload,dict) or payload.get('code') != 0 or not isinstance(payload.get('data'),list):
                        raise CoinWError(f'CoinW returned invalid/error response: {str(payload)[:180]}')
                    return payload['data']
                except (httpx.HTTPError,ValueError,CoinWError) as e:
                    if attempt==3: raise CoinWError(f'{path}: {e}') from e
                    await asyncio.sleep(.6*(2**attempt))
    async def symbols(self,limit=50,min_volume=0):
        data=await self.get('/v1/perpumPublic/tickers')
        pairs=[]
        for x in data:
            if not isinstance(x,dict): continue
            try:
                name=str(x['name']).upper(); base=str(x['base_coin']).upper()
                vol=float(x['total_volume']); price=float(x['last_price'])
                if str(x.get('quote_coin','')).upper()!='USDT' or int(x.get('contract_id',0))!=1: continue
                if not name.endswith('USDT') or name[:-4]!=base or not math.isfinite(vol) or not math.isfinite(price) or price<=0 or vol<min_volume: continue
                pairs.append({'symbol':name,'base':base,'volume':vol,'volume_unit':'CoinW total_volume (unit not independently verified)'})
            except (ValueError,KeyError,TypeError): continue
        return sorted(pairs,key=lambda x:x['volume'],reverse=True)[:limit]
    async def candles(self,base,timeframe,count=300):
        rows=await self.get('/v1/perpumPublic/klines',{'currencyCode':base,'granularity':GRANULARITY[timeframe],'klineType':'0','limit':str(count)})
        return normalize(rows,timeframe,int(time.time()*1000))
