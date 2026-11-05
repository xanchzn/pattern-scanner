import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import normalize,pivots,detect,Candle

def test_normalize_closed_and_invalid():
    rows=[[0,1,2,0.5,1.5,2],[900000,1,2,.5,1.5,2],[1800000,1,2,.5,1.5,2],[2700000,1,0,.5,1.5,2]]
    result=normalize(rows,'15m',2700000)
    assert len(result)==2 and result[0].time==900
    assert all(x.high>=x.close for x in result)

def test_pivot_requires_future_confirmation():
    c=[Candle(i*60,1,float(h),.5,1,1) for i,h in enumerate([1,2,5,2,1,3,10])]
    hi,_=pivots(c,2)
    assert (2,5.) in hi and all(i!=6 for i,_ in hi)

def test_no_future_candle_effect():
    c=[Candle(i*900,100,102+i%5,98-i%4,100,10) for i in range(100)]
    assert detect(c,'BTCUSDT','15m')==detect(c[:], 'BTCUSDT','15m')
