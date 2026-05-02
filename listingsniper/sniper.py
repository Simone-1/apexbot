import os, json, time, re, requests, logging, tempfile
from datetime import datetime, timezone
from threading import Thread

def telegram(msg):
    try:
        env = open("/etc/environment").read()
        token = env.split("TELEGRAM_TOKEN=")[1].split("\n")[0]
        chat_id = env.split("TELEGRAM_CHAT_ID=")[1].split("\n")[0]
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg}, timeout=5)
    except: pass

PAPER_MODE=True; TRADE_USD=30; TAKE_PROFIT_PCT=0.50; STOP_LOSS_PCT=0.08
TIME_EXIT_MINS=60; POLL_INTERVAL=300; PRICE_CHECK_SECS=10
STATE_FILE="/root/listingsniper/state.json"
BASE="https://api.binance.com"
ANNOUNCE_URL="https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"

os.makedirs("/root/listingsniper", exist_ok=True)
logging.basicConfig(level=logging.INFO,format="%(asctime)s [SNIPER] %(message)s",handlers=[logging.StreamHandler(),logging.FileHandler("/root/listingsniper/sniper.log",mode="a")])
log = logging.getLogger("sniper")

state = {"running":True,"paper_mode":PAPER_MODE,"seen_listings":[],"trades":[],"open_trade":None,"total_pnl":0.0,"logs":[],"scan_count":0}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f: saved=json.load(f)
            state["seen_listings"]=saved.get("seen_listings",[])
            state["trades"]=saved.get("trades",[])
            state["total_pnl"]=saved.get("total_pnl",0.0)
            state["logs"]=saved.get("logs",[])
            log.info(f"State loaded — {len(state['trades'])} trades, PnL: ${state['total_pnl']:.2f}")
        except Exception as e: log.error(f"Failed to load state: {e}")

def save_state():
    try:
        dir_=os.path.dirname(STATE_FILE)
        with tempfile.NamedTemporaryFile("w",dir=dir_,delete=False,suffix=".tmp") as tmp:
            json.dump(state,tmp,indent=2,default=str); tmp_path=tmp.name
        os.replace(tmp_path,STATE_FILE)
    except Exception as e: log.error(f"Failed to save state: {e}")

def addlog(msg, level="info"):
    entry={"time":datetime.now(timezone.utc).strftime("%H:%M:%S"),"msg":msg,"level":level}
    state["logs"]=[entry]+state["logs"][:499]
    getattr(log,level if level in ("info","warning","error") else "info")(msg)
    save_state()

def get_price(symbol):
    try:
        r=requests.get(f"{BASE}/api/v3/ticker/price",params={"symbol":symbol},timeout=5)
        return float(r.json()["price"])
    except: return None

def symbol_exists(symbol):
    try:
        r=requests.get(f"{BASE}/api/v3/ticker/price",params={"symbol":symbol},timeout=5)
        return r.status_code==200 and "price" in r.json()
    except: return False

def get_announcements():
    try:
        headers={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r=requests.get(ANNOUNCE_URL,params={"type":1,"pageNo":1,"pageSize":20,"catalogId":48},headers=headers,timeout=10)
        if r.status_code!=200: return []
        return r.json()["data"]["catalogs"][0]["articles"]
    except Exception as e: log.error(f"Failed to fetch announcements: {e}"); telegram(f"⚠️ ListingSniper: Failed to fetch announcements\n{e}"); return []

def extract_symbol(title):
    match=re.search(r'\(([A-Z0-9]{2,10})\)',title)
    return match.group(1)+"USDT" if match else None

def is_spot_listing(title):
    t=title.lower()
    if "will list" not in t: return False
    return not any(w in t for w in ["futures","margin","earn","airdrop","perpetual","trading pair","hodler","launchpool","launchpad","convert","vip","loan"])

def monitor_trade(symbol, entry_price, article_id):
    tp=entry_price*(1+TAKE_PROFIT_PCT); sl=entry_price*(1-STOP_LOSS_PCT)
    open_time=time.time()
    addlog(f"{'PAPER' if PAPER_MODE else 'LIVE'} Entered {symbol} @ ${entry_price:.6f} | TP: ${tp:.6f} | SL: ${sl:.6f}")
    state["open_trade"]={"symbol":symbol,"entry":entry_price,"tp":tp,"sl":sl,"open_time":datetime.now(timezone.utc).isoformat(),"article_id":article_id,"paper":PAPER_MODE}
    save_state()
    while state["running"]:
        time.sleep(PRICE_CHECK_SECS)
        price=get_price(symbol)
        if price is None: continue
        elapsed=(time.time()-open_time)/60
        pct=(price-entry_price)/entry_price*100
        if price>=tp: close_trade(symbol,entry_price,price,"TP",pct); return
        if price<=sl: close_trade(symbol,entry_price,price,"SL",pct); return
        if elapsed>=TIME_EXIT_MINS: close_trade(symbol,entry_price,price,"TimeExit",pct); return

def close_trade(symbol, entry, exit_price, reason, pct):
    pnl=(exit_price-entry)/entry*TRADE_USD
    state["total_pnl"]=round(state["total_pnl"]+pnl,2)
    trade={"symbol":symbol,"entry":entry,"exit":exit_price,"pct":round(pct,2),"pnl":round(pnl,2),"reason":reason,"paper":PAPER_MODE,"closed":datetime.now(timezone.utc).isoformat()}
    state["trades"].insert(0,trade); state["open_trade"]=None
    emoji="✅" if pnl>0 else "❌"
    telegram(f"{emoji} ListingSniper: {'PAPER ' if PAPER_MODE else ''}Closed {symbol} | {reason} | {pct:+.1f}% | PnL: ${pnl:+.2f}")
    addlog(f"{emoji} {'PAPER ' if PAPER_MODE else ''}CLOSED {symbol} @ ${exit_price:.6f} ({pct:+.1f}%) | PnL: ${pnl:+.2f} | Total: ${state['total_pnl']:+.2f} | Reason: {reason}")

def wait_and_trade(symbol, article_id):
    if state["open_trade"]:
        addlog(f"Skipping {symbol} — already have open trade","warning"); return
    deadline=time.time()+24*3600
    while time.time()<deadline and state["running"]:
        if symbol_exists(symbol):
            price=get_price(symbol)
            if price and price>0:
                addlog(f"🚀 {symbol} is now trading at ${price:.6f} — entering position")
                telegram(f"🚀 ListingSniper: {'PAPER ' if PAPER_MODE else ''}Entered {symbol} @ ${price:.6f}\nTP: ${price*(1+TAKE_PROFIT_PCT):.6f} | SL: ${price*(1-STOP_LOSS_PCT):.6f}")
                state["pending"] = [p for p in state["pending"] if p["symbol"] != symbol]
                monitor_trade(symbol,price,article_id); return
        time.sleep(5)
    addlog(f"⏰ {symbol} never started trading within 24h — skipping","warning")

def scan_loop():
    load_state()
    mode="PAPER TRADING" if PAPER_MODE else "LIVE TRADING"
    addlog(f"🎯 ListingSniper started — {mode} MODE")
    telegram(f"🎯 ListingSniper started — {mode}\nTrade: ${TRADE_USD} | TP: +{TAKE_PROFIT_PCT*100:.0f}% | SL: -{STOP_LOSS_PCT*100:.0f}% | Exit: {TIME_EXIT_MINS}mins")
    addlog(f"Settings: Trade ${TRADE_USD} | TP +{TAKE_PROFIT_PCT*100:.0f}% | SL -{STOP_LOSS_PCT*100:.0f}% | Exit after {TIME_EXIT_MINS}mins")
    while state["running"]:
        state["scan_count"]+=1
        articles=get_announcements()
        for article in articles:
            article_id=article.get("id"); title=article.get("title","")
            if article_id in state["seen_listings"]: continue
            state["seen_listings"].append(article_id)
            state["seen_listings"]=state["seen_listings"][-200:]
            # Skip old announcements - only act on listings within last 6 hours
            age_hours = (int(time.time()*1000) - article.get('releaseDate', 0)) / 3600000
            if age_hours > 48:
                continue
            if not is_spot_listing(title): continue
            symbol=extract_symbol(title)
            if not symbol: addlog(f"Could not extract symbol from: {title}","warning"); continue
            addlog(f"🔔 New listing detected: {title}")
            telegram(f"🔔 ListingSniper: New listing detected\n{title}\nWaiting for trading to open...")
            addlog(f"   Symbol: {symbol} — waiting for trading to open...")
            state["pending"].append({"symbol": symbol, "title": title, "detected": datetime.now(timezone.utc).isoformat()})
            save_state()
            Thread(target=wait_and_trade,args=(symbol,article_id),daemon=True).start()
        save_state()
        time.sleep(POLL_INTERVAL)

if __name__=="__main__":
    try:
        scan_loop()
    except Exception as e:
        telegram(f"🔴 ListingSniper crashed: {e}")
        raise
