"""Deterministic, closed-candle structural scanner. No trading signals."""
from dataclasses import dataclass, asdict
from statistics import median, mean
import math

INTERVAL_MS = {'15m': 900000, '1H': 3600000, '4H': 14400000}
GRANULARITY = {'15m': '2', '1H': '3', '4H': '4'}

@dataclass
class Candle:
    time: int  # UTC seconds
    open: float
    high: float
    low: float
    close: float
    volume: float

def normalize(rows, timeframe, now_ms):
    """CoinW format: [epoch_ms, open, high, low, close, volume]. Only closed bars."""
    out = {}
    for r in rows:
        try:
            if not isinstance(r, (list, tuple)) or len(r) < 6: continue
            t = int(r[0]); o,h,l,c,v = map(float,r[1:6])
            if not all(map(math.isfinite,(o,h,l,c,v))): continue
            if min(o,h,l,c) <= 0 or v < 0 or h < max(o,c,l) or l > min(o,c,h): continue
            if t <= 0 or t + INTERVAL_MS[timeframe] > now_ms or t > now_ms: continue
            out[t] = Candle(t//1000,o,h,l,c,v)
        except (ValueError, TypeError, OverflowError): continue
    return [out[t] for t in sorted(out)]

def atr(c, period=14):
    if len(c) < period+1: return 0
    tr = [max(c[i].high-c[i].low, abs(c[i].high-c[i-1].close),abs(c[i].low-c[i-1].close)) for i in range(1,len(c))]
    return mean(tr[-period:])

def pivots(c, window=3):
    """Confirmation requires window bars to the RIGHT; newest bars cannot pivot."""
    hi, lo = [], []
    for i in range(window,len(c)-window):
        left = c[i-window:i]; right = c[i+1:i+window+1]
        if all(c[i].high > x.high for x in left) and all(c[i].high >= x.high for x in right): hi.append((i,c[i].high))
        if all(c[i].low < x.low for x in left) and all(c[i].low <= x.low for x in right): lo.append((i,c[i].low))
    return hi,lo

def zones(points, a, count, kind):
    groups = []
    for idx,price in points:
        match = next((g for g in groups if abs(g['price']-price) <= a*.65),None)
        if match:
            match['points'].append((idx,price));match['price']=median(p for _,p in match['points'])
        else: groups.append({'price':price,'points':[(idx,price)]})
    result=[]
    for g in groups:
        touches=len(g['points']); last=max(i for i,_ in g['points']); center=g['price']
        if touches<2: continue
        result.append({'kind':kind,'low':round(center-a*.4,10),'high':round(center+a*.4,10),'center':center,'touches':touches,'last_index':last,'strength':min(100,round(35+touches*12+20*last/max(1,count-1)))})
    return sorted(result,key=lambda z:(z['strength'],z['last_index']),reverse=True)

def detect(c, symbol, timeframe):
    if len(c)<65: return []
    a=atr(c)
    if a<=0: return []
    hi,lo=pivots(c)
    supports=zones(lo,a,len(c),'support'); resistances=zones(hi,a,len(c),'resistance')
    last=c[-1]; vol=mean(x.volume for x in c[-21:-1]); volratio=last.volume/vol if vol>0 else 1
    recent=c[-30:]; width=(max(x.high for x in recent)-min(x.low for x in recent))/last.close
    prior=c[-60:-30]; priorwidth=(max(x.high for x in prior)-min(x.low for x in prior))/max(1e-12,prior[-1].close)
    contraction=width < priorwidth*.8
    results=[]
    def emit(pattern,status,zone,clarity,reason,observe,invalidate):
        dist=abs(last.close-zone['center'])/a if zone else 2
        proximity=max(0,100-35*dist)
        strength=zone['strength'] if zone else 45
        completeness=min(100,len(c)/200*100)
        score=round(.25*clarity+.25*strength+.20*proximity+.10*min(100,50+volratio*20)+.10*(90 if contraction else 55)+.10*completeness)
        results.append({'id':f'{symbol}-{timeframe}-{pattern.lower().replace(" ","-")}-{status}-{zone["kind"] if zone else "none"}', 'symbol':symbol,'timeframe':timeframe,'pattern':pattern,'status':status,'score':max(0,min(100,score)),'updated_at':last.time,'reason':reason,'observe':observe,'invalidation':invalidate,'zones':(supports[:3]+resistances[:3]),'candle_count':len(c),'volume_ratio':round(volratio,2),'last_closed_candle':last.time})
    for z in supports[:3]:
        d=(last.close-z['center'])/a
        if -.25 <= d <= 1.1:
            emit('Support zone test','forming',z,75,'Price is testing a support cluster confirmed by historical swing lows.','Watch whether future closed candles hold above the support band.','A closed candle materially below the band weakens this structure.')
    for z in resistances[:3]:
        d=(z['center']-last.close)/a
        if -.25 <= d <= 1.1:
            emit('Resistance zone test','forming',z,75,'Price is testing a resistance cluster confirmed by historical swing highs.','Watch whether future closed candles reject or absorb the resistance band.','A sustained close above the band weakens the resistance interpretation.')
    # Range uses only historical closed candles; boundaries derived from prior 30 candles.
    base=c[-31:-1]; upper=max(x.high for x in base); lower=min(x.low for x in base)
    band=(upper-lower)/max(1e-12,last.close)
    if band < .10 and width <= priorwidth*1.15:
        z={'center':upper,'strength':65,'low':upper-a*.3,'high':upper+a*.3,'kind':'resistance','touches':2,'last_index':len(c)-2}
        emit('Consolidation','forming',z,72,'Recent closed candles occupy a relatively narrow trading range.','Observe range boundaries and volatility expansion.','A sustained close outside the range ends the consolidation.')
        if contraction and (upper-last.close)/a <= 1.25 and last.close <= upper:
            emit('Forming breakout','forming',z,85,'Volatility has contracted and price is approaching the previous range high; no breakout is confirmed.','A closed candle above the previous boundary is needed to confirm a breakout.','A move away from the boundary or renewed range expansion invalidates this setup.')
        if contraction and (last.close-lower)/a <= 1.25 and last.close >= lower:
            zz={**z,'center':lower,'kind':'support','low':lower-a*.3,'high':lower+a*.3}
            emit('Forming breakout','forming',zz,85,'Volatility has contracted near the previous range low; no breakdown is confirmed.','Watch for a closed candle outside the previous boundary.','A move away from the boundary invalidates this forming structure.')
    # Breakout/retest state machine: use prior historical boundary, confirm at close,
    # retest within 8 subsequent bars, expire after 12, invalidate after 2 ATR.
    for direction in ('up','down'):
        for i in range(max(31,len(c)-12),len(c)-1):
            previous=c[i-30:i]
            boundary=max(x.high for x in previous) if direction=='up' else min(x.low for x in previous)
            breakout=(c[i].close > boundary+a*.15) if direction=='up' else (c[i].close < boundary-a*.15)
            if not breakout: continue
            later=c[i+1: min(len(c),i+9)]
            if not later: continue
            invalid=any(x.close < boundary-2*a for x in later) if direction=='up' else any(x.close > boundary+2*a for x in later)
            if invalid: continue
            retest=any(x.low <= boundary+a*.4 and x.close >= boundary for x in later) if direction=='up' else any(x.high >= boundary-a*.4 and x.close <= boundary for x in later)
            if retest and i+8 >= len(c)-1:
                z={'center':boundary,'strength':70,'low':boundary-a*.4,'high':boundary+a*.4,'kind':'support' if direction=='up' else 'resistance','touches':2,'last_index':i}
                emit('Breakout retest','confirmed',z,88,'A closed candle crossed the historical range boundary and a later candle retested it.','Observe whether the retested boundary continues to hold.','A close more than two ATR beyond the retested boundary invalidates the structure.')
                break
    return sorted(results,key=lambda x:(x['status']!='forming',-x['score']))
