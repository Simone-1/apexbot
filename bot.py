import os,time,hmac,hashlib,requests,json,logging
from datetime import datetime,timezone
from threading import Thread

CFG={"trade_size":15,"max_trades":8,"tp":0.062,"sl":0.028,"trail":0.022,"min_score":60,"max_pump":14,"min_rise":1.6,"scan_sec":35,"peak_sec":20,"peak_hours":(13,22)}
COINS=["PEPEUSDT","DOGEUSDT","SHIBUSDT","FLOKIUSDT","BONKUSDT","WIFUSDT","MEMEUSDT","NEIROUSDT","SOLUSDT","AVAXUSDT","APTUSDT","SUIUSDT","SEIUSDT","ARBUSDT","OPUSDT","INJUSDT","TIAUSDT","JUPUSDT","FETUSDT","RNDRUSDT","WLDUSDT","ORDIUSDT","1000SATSUSDT"]
BASE="https://api.binance.com"
API_KEY=os.environ.get("BINANCE_API_KEY","")
API_SECRET=os.environ.get("BINANCE_API_SECRET","")
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(message)s",handlers=[logging.StreamHandler(),logging.FileHandler("apexbot.log",mode="a")])
log=logging.getLogger("apexbot")
state={"open_trades":{},"closed_trades":[],"logs":[],"running":False,"scan_count":0}

def save():
    json.dump(state,open("state.json","w"),default=str)

def load():
    if os.path.exists("state.json"):
        s=json.load(open("state.json"))
        state["closed_trades"]=s.get("closed_trades",[])

def addlog(msg,level="info"):
    state["logs"]=[{"time":datetime.now().strftime("%H:%M:%S"),"msg":msg,"level":level}]+state["logs"][:199]
    getattr(log,level if level in("info","warning","error") else "info")(msg)

def sign(p):
    qs="&".join(f"{k}={v}" for k,v in p.items())
    return hmac.new(API_SECRET.encode(),qs.encode(),hashlib.sha256).hexdigest()

def pub(path,params=None):
    r=requests.get(BASE+path,params=params or {},timeout=10)
    r.raise_for_status()
    return r.json()

def signed(path,method="GET",params=None):
    p=dict(params or {})
    p["timestamp"]=int(time.time()*1000)
    p["signature"]=sign(p)
    h={"X-MBX-APIKEY":API_KEY}
    r=requests.get(BASE+path,params=p,headers=h,timeout=10) if method=="GET" else requests.post(BASE+path,params=p,headers=h,timeout=10)
    r.raise_for_status()
    d=r.json()
    if isinstance(d,dict) and d.get("code",0)<0:
        raise Exception(d.get("msg","error"))
    return d

def is_peak():
    h=datetime.now(timezone.utc).hour
    return CFG["peak_hours"][0]<=h<CFG["peak_hours"][1]

def score(t):
    pct=float(t["priceChangePercent"])
    price=float(t["lastPrice"])
    avg=float(t["weightedAvgPrice"])
    vol=float(t["quoteVolume"])
    if pct<CFG["min_rise"] or pct>CFG["max_pump"] or price<=0 or avg<=0:
        return 0
    s=min(pct*3,40)
    pva=((price-avg)/avg)*100
    if pva>0:s+=min(pva*4,20)
    if vol>5000000:s+=10
    if vol>20000000:s+=10
    if is_peak():s+=20
    return min(int(s),100)

def get_balance():
    try:
        d=signed("/api/v3/account")
        return round(float(next((b["free"] for b in d["balances"] if b["asset"]=="USDT"),0)),2)
    except:
        return None

def buy(symbol,price):
    tp=price*(1+CFG["tp"])
    sl=price*(1-CFG["sl"])
    qty=CFG["trade_size"]/price
    try:
        signed("/api/v3/order","POST",{"symbol":symbol,"side":"BUY","type":"MARKET","quoteOrderQty":f"{CFG['trade_size']:.2f}"})
        tid=f"{symbol}_{int(time.time())}"
        trade={"id":tid,"symbol":symbol,"entry_price":price,"take_profit":tp,"stop_loss":sl,"qty":qty,"usd_size":CFG["trade_size"],"high_price":price,"status":"open","open_time":datetime.now().strftime("%H:%M %d/%m")}
        state["open_trades"][tid]=trade
        addlog(f"BOUGHT {symbol} @ {price:.6f} TP:{tp:.6f} SL:{sl:.6f}")
        try:
            signed("/api/v3/order/oco","POST",{"symbol":symbol,"side":"SELL","quantity":f"{qty:.6f}","price":f"{tp:.8f}","stopPrice":f"{sl:.8f}","stopLimitPrice":f"{sl*0.997:.8f}","stopLimitTimeInForce":"GTC"})
            addlog(f"OCO set {symbol}")
        except Exception as e:
            addlog(f"OCO failed {symbol}: {e}","warning")
        save()
    except Exception as e:
        addlog(f"BUY FAILED {symbol}: {e}","error")

def close(trade,price,reason):
    try:
        signed("/api/v3/order","POST",{"symbol":trade["symbol"],"side":"SELL","type":"MARKET","quantity":f"{trade['qty']:.6f}"})
        pnl=(price-trade["entry_price"])/trade["entry_price"]*trade["usd_size"]
        c={**trade,"close_price":price,"pnl":round(pnl,3),"close_time":datetime.now().strftime("%H:%M %d/%m"),"reason":reason,"status":"closed"}
        state["closed_trades"].insert(0,c)
        del state["open_trades"][trade["id"]]
        addlog(f"{reason} {trade['symbol']} PnL:{'+' if pnl>=0 else ''}{pnl:.2f}")
        save()
    except Exception as e:
        addlog(f"CLOSE ERROR {trade['symbol']}: {e}","error")

def check_stops():
    for tid,trade in list(state["open_trades"].items()):
        try:
            price=float(pub("/api/v3/ticker/price",{"symbol":trade["symbol"]})["price"])
            if price>trade["high_price"]:
                state["open_trades"][tid]["high_price"]=price
                trade["high_price"]=price
            trail_sl=trade["high_price"]*(1-CFG["trail"])
            if price>=trade["take_profit"]:
                close(trade,price,"TP")
            elif price<=trail_sl and price<trade["entry_price"]*1.005:
                close(trade,price,"TrailSL")
            elif price<=trade["stop_loss"]:
                close(trade,price,"SL")
            time.sleep(0.2)
        except Exception as e:
            addlog(f"STOP CHECK ERROR {trade['symbol']}: {e}","warning")

def scan_loop():
    addlog("ApexBot V2 started — 23 coins, trailing stop, peak hours")
    while state["running"]:
        try:
            state["scan_count"]+=1
            if state["open_trades"]:
                check_stops()
            if len(state["open_trades"])<CFG["max_trades"]:
                tickers=pub("/api/v3/ticker/24hr")
                relevant=[t for t in tickers if t["symbol"] in COINS]
                open_syms={t["symbol"] for t in state["open_trades"].values()}
                scored=sorted([(t,score(t)) for t in relevant if t["symbol"] not in open_syms and score(t)>=CFG["min_score"]],key=lambda x:x[1],reverse=True)[:3]
                if not scored:
                    addlog(f"Scan {state['scan_count']} — no signals ({'peak' if is_peak() else 'off-peak'})")
                for ticker,sc in scored:
                    if len(state["open_trades"])>=CFG["max_trades"]:break
                    price=float(ticker["lastPrice"])
                    addlog(f"Signal [{sc}] {ticker['symbol']} +{float(ticker['priceChangePercent']):.1f}%")
                    buy(ticker["symbol"],price)
                    time.sleep(1)
            else:
                addlog("Max positions open — waiting")
        except Exception as e:
            addlog(f"SCAN ERROR: {e}","error")
        time.sleep(CFG["peak_sec"] if is_peak() else CFG["scan_sec"])
    addlog("Bot stopped")
