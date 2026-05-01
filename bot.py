import os, time, hmac, hashlib, requests, json, logging
from datetime import datetime, timezone
from threading import Thread

# ─── CONFIG ───────────────────────────────────────────────────────────────────
CFG = {
    "min_trade_usd":   10,       # Minimum trade size in USDT
    "max_trade_usd":   20,       # Maximum trade size in USDT
    "max_positions":   8,        # Max concurrent open trades
    "take_profit":     0.025,    # 2.5% take profit
    "stop_loss":       0.020,    # 2.0% hard stop loss
    "trailing_stop":   0.015,    # 1.5% trailing stop from peak
    "min_score":       50,       # Minimum signal score to buy
    "max_pump":        12,       # Ignore coins already pumped > 15%
    "min_rise":        2.5,      # Minimum 24h rise % to consider
    "scan_interval":   30,       # Seconds between scans
    "peak_hours":      (9, 23), # UTC hours for peak market activity
    "partial_tp_trailing": 0.010,  # 1% trailing stop after partial TP
    "max_trade_hours":     6,      # Close trade if open longer than this
}

COINS = [
    "BTCUSDT", "SOLUSDT", "PEPEUSDT", "DOGEUSDT", "SHIBUSDT",
    "FLOKIUSDT", "BONKUSDT", "WIFUSDT", "MEMEUSDT", "AVAXUSDT",
    "APTUSDT", "SUIUSDT", "SEIUSDT", "ARBUSDT", "OPUSDT",
    "FETUSDT", "RENDERUSDT", "WLDUSDT", "1000SATSUSDT",
    "ORDIUSDT", "STXUSDT", "TIAUSDT"
]

BASE       = "https://api.binance.com"
API_KEY    = os.environ.get("BINANCE_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("apexbot.log", mode="a")
    ]
)
log = logging.getLogger("apexbot")

# ─── STATE ────────────────────────────────────────────────────────────────────
state = {
    "running":       False,
    "open_trades":   {},
    "closed_trades": [],
    "logs":          [],
    "scan_count":    0,
    "total_pnl":     0.0,
    "daily_pnl":     0.0,
    "last_day":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
}

# ─── EXCHANGE INFO CACHE ───────────────────────────────────────────────────────
_exchange_info = {}

def load_exchange_info():
    """Cache symbol precision/step info so we don't spam the API."""
    global _exchange_info
    try:
        data = pub("/api/v3/exchangeInfo")
        for sym in data.get("symbols", []):
            s = sym["symbol"]
            step = None
            min_qty = None
            min_notional = 5.0
            for f in sym.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step    = float(f["stepSize"])
                    min_qty = float(f["minQty"])
                if f["filterType"] == "NOTIONAL":
                    min_notional = float(f.get("minNotional", 5.0))
            _exchange_info[s] = {
                "step":         step or 0.001,
                "min_qty":      min_qty or 0.001,
                "min_notional": min_notional,
            }
        addlog(f"Exchange info loaded for {len(_exchange_info)} symbols")
    except Exception as e:
        addlog(f"Failed to load exchange info: {e}", "error")

def round_step(qty, step):
    """Round quantity down to the nearest valid step size."""
    if step == 0:
        return qty
    from decimal import Decimal, ROUND_DOWN
    precision = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
    qty = float((Decimal(str(qty)) // Decimal(str(step))) * Decimal(str(step)))
    return round(qty, precision)

# ─── PERSISTENCE ──────────────────────────────────────────────────────────────
def save():
    try:
        with open("state.json", "w") as f:
            json.dump(state, f, default=str)
    except Exception as e:
        log.error(f"Save failed: {e}")

def load():
    if os.path.exists("state.json"):
        try:
            with open("state.json") as f:
                s = json.load(f)
            state["closed_trades"] = s.get("closed_trades", [])
            state["total_pnl"]     = s.get("total_pnl", 0.0)
            state["daily_pnl"]     = s.get("daily_pnl", 0.0)
            state["last_day"]      = s.get("last_day", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            state["open_trades"]   = s.get("open_trades", {})
            addlog(f"State loaded — {len(state['open_trades'])} open, {len(state['closed_trades'])} closed")
        except Exception as e:
            log.error(f"Load failed: {e}")

# ─── LOGGING HELPER ───────────────────────────────────────────────────────────
def addlog(msg, level="info"):
    entry = {
        "time":  datetime.now().strftime("%H:%M:%S"),
        "msg":   msg,
        "level": level,
    }
    state["logs"] = [entry] + state["logs"][:299]
    getattr(log, level if level in ("info", "warning", "error") else "info")(msg)

# ─── API HELPERS ──────────────────────────────────────────────────────────────
def sign(params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()

def pub(path, params=None):
    r = requests.get(BASE + path, params=params or {}, timeout=10)
    r.raise_for_status()
    return r.json()

def signed(path, method="GET", params=None):
    p = dict(params or {})
    p["timestamp"]  = int(time.time() * 1000)
    sig = sign(p)
    h = {"X-MBX-APIKEY": API_KEY}
    if method == "GET":
        p["signature"] = sig
        r = requests.get(BASE + path, params=p, headers=h, timeout=10)
    else:
        r = requests.post(BASE + path, params={"signature": sig}, data=p, headers=h, timeout=10)
    if not r.ok:
        log.error(f"Binance error {r.status_code}: {r.text}")
    r.raise_for_status()
    d = r.json()
    if isinstance(d, dict) and d.get("code", 0) < 0:
        raise Exception(d.get("msg", "Binance error"))
    return d

# ─── BALANCE ──────────────────────────────────────────────────────────────────
def get_balance():
    try:
        d = signed("/api/v3/account")
        return round(float(next((b["free"] for b in d["balances"] if b["asset"] == "USDT"), 0)), 2)
    except Exception as e:
        addlog(f"Balance check failed: {e}", "error")
        return None

def get_coin_balance(asset):
    """Get free balance of a specific coin asset."""
    try:
        d = signed("/api/v3/account")
        return float(next((b["free"] for b in d["balances"] if b["asset"] == asset), 0))
    except Exception as e:
        addlog(f"Coin balance check failed for {asset}: {e}", "error")
        return 0.0

# ─── PEAK HOURS ───────────────────────────────────────────────────────────────
def is_peak():
    h = datetime.now(timezone.utc).hour
    return CFG["peak_hours"][0] <= h < CFG["peak_hours"][1]

# ─── DAILY PNL RESET ──────────────────────────────────────────────────────────
def check_daily_reset():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state["last_day"] != today:
        state["daily_pnl"] = 0.0
        state["last_day"]  = today
        addlog("Daily PnL reset for new day")

# ─── SIGNAL SCORING ───────────────────────────────────────────────────────────
def score(ticker):
    try:
        pct  = float(ticker["priceChangePercent"])
        price = float(ticker["lastPrice"])
        avg  = float(ticker["weightedAvgPrice"])
        vol  = float(ticker["quoteVolume"])

        if pct < CFG["min_rise"] or pct > CFG["max_pump"] or price <= 0 or avg <= 0:
            return 0

        s = min(pct * 3, 40)

        # Price vs weighted average (momentum above avg = bullish)
        pva = ((price - avg) / avg) * 100
        if pva > 0:
            s += min(pva * 4, 20)

        # Volume bonus
        if vol > 5_000_000:  s += 10
        if vol > 20_000_000: s += 10

        # Peak hours bonus
        if is_peak(): s += 15

        return min(int(s), 100)
    except:
        return 0

# ─── TRADE SIZE ───────────────────────────────────────────────────────────────
def calc_trade_size(balance):
    """Dynamically size trade between min and max based on available balance."""
    if balance is None or balance < CFG["min_trade_usd"]:
        return None
    # Use 8% of balance per trade, clamped between min and max
    size = round(balance * 0.08, 2)
    size = max(CFG["min_trade_usd"], min(CFG["max_trade_usd"], size))
    # Make sure we have enough left after this trade
    if balance < size + CFG["min_trade_usd"]:
        size = CFG["min_trade_usd"]
    if balance < size:
        return None
    return size

# ─── BUY ──────────────────────────────────────────────────────────────────────
def buy(symbol, price):
    balance = get_balance()
    trade_usd = calc_trade_size(balance)

    if trade_usd is None:
        addlog(f"Skipping {symbol} — insufficient balance (${balance})", "warning")
        return

    info = _exchange_info.get(symbol, {})
    step     = info.get("step", 0.001)
    min_qty  = info.get("min_qty", 0.001)
    min_not  = info.get("min_notional", 5.0)

    raw_qty = trade_usd / price
    qty     = round_step(raw_qty, step)

    if qty < min_qty:
        addlog(f"Skipping {symbol} — qty {qty} below min {min_qty}", "warning")
        return
    if qty * price < min_not:
        addlog(f"Skipping {symbol} — notional ${qty*price:.2f} below min ${min_not}", "warning")
        return

    try:
        signed("/api/v3/order", "POST", {
            "symbol":        symbol,
            "side":          "BUY",
            "type":          "MARKET",
            "quoteOrderQty": f"{trade_usd:.2f}",
        })

        tp = price * (1 + CFG["take_profit"])
        sl = price * (1 - CFG["stop_loss"])

        tid   = f"{symbol}_{int(time.time())}"
        trade = {
            "id":          tid,
            "symbol":      symbol,
            "entry_price": price,
            "take_profit": tp,
            "stop_loss":   sl,
            "high_price":  price,
            "qty":         qty,
            "usd_size":    trade_usd,
            "status":      "open",
            "open_time":   datetime.now().strftime("%H:%M %d/%m"),
        }
        state["open_trades"][tid] = trade
        addlog(f"✅ BOUGHT {symbol} @ {price:.6f} | Size:${trade_usd} | TP:{tp:.6f} | SL:{sl:.6f}")
        save()

    except Exception as e:
        try:
            addlog(f"❌ BUY FAILED {symbol}: {e} | Response: {e.response.text if hasattr(e, 'response') else 'no response'}", "error")
        except:
            addlog(f"❌ BUY FAILED {symbol}: {e}", "error")

# ─── SELL ─────────────────────────────────────────────────────────────────────
def close(trade, price, reason):
    symbol = trade["symbol"]
    asset  = symbol.replace("USDT", "").replace("1000SATS", "1000SATS")

    # Get actual coin balance to sell — avoids "insufficient balance" on sells
    coin_bal = get_coin_balance(asset)
    info     = _exchange_info.get(symbol, {})
    step     = info.get("step", 0.001)
    min_qty  = info.get("min_qty", 0.001)

    qty = round_step(coin_bal, step)

    if qty < min_qty or qty * price < info.get("min_notional", 5.0):
        addlog(f"⚠️ Can't sell {symbol} — qty {qty} too small (held: {coin_bal})", "warning")
        # Remove from open trades anyway if balance is dust
        if coin_bal * price < 1.0:
            pnl = (price - trade["entry_price"]) / trade["entry_price"] * trade["usd_size"]
            _close_record(trade, price, pnl, reason + "_dust")
        return

    try:
        signed("/api/v3/order", "POST", {
            "symbol":   symbol,
            "side":     "SELL",
            "type":     "MARKET",
            "quantity": f"{qty:.8f}".rstrip("0").rstrip("."),
        })

        pnl = (price - trade["entry_price"]) / trade["entry_price"] * trade["usd_size"]
        _close_record(trade, price, pnl, reason)

    except Exception as e:
        addlog(f"❌ SELL FAILED {symbol}: {e}", "error")

def _close_record(trade, price, pnl, reason):
    pnl = round(pnl, 3)
    state["total_pnl"] = round(state.get("total_pnl", 0) + pnl, 3)
    state["daily_pnl"] = round(state.get("daily_pnl", 0) + pnl, 3)

    closed = {
        **trade,
        "close_price": price,
        "close_time":  datetime.now().strftime("%H:%M %d/%m"),
        "pnl":         pnl,
        "reason":      reason,
        "status":      "closed",
    }
    state["closed_trades"].insert(0, closed)
    if trade["id"] in state["open_trades"]:
        del state["open_trades"][trade["id"]]

    emoji = "🟢" if pnl >= 0 else "🔴"
    addlog(f"{emoji} {reason} {trade['symbol']} @ {price:.6f} | PnL: {'+' if pnl>=0 else ''}{pnl:.2f} | Day: {'+' if state['daily_pnl']>=0 else ''}{state['daily_pnl']:.2f} | Total: {'+' if state['total_pnl']>=0 else ''}{state['total_pnl']:.2f}")
    save()

# ─── STOP CHECKER ─────────────────────────────────────────────────────────────
def check_stops():
    for tid, trade in list(state["open_trades"].items()):
        try:
            price = float(pub("/api/v3/ticker/price", {"symbol": trade["symbol"]})["price"])

            # Update peak price for trailing stop
            if price > trade["high_price"]:
                state["open_trades"][tid]["high_price"] = price
                trade["high_price"] = price

            # Time-based exit — close if open longer than max_trade_hours
            if trade.get("open_time") and trade["open_time"] != "imported":
                try:
                    opened = datetime.strptime(trade["open_time"], "%H:%M %d/%m").replace(
                        year=datetime.now().year)
                    hours_open = (datetime.now() - opened).total_seconds() / 3600
                    if hours_open > CFG["max_trade_hours"]:
                        close(trade, price, "TimeExit")
                        time.sleep(0.3)
                        continue
                except:
                    pass

            # Tiered exit — sell half at TP, tighten trailing stop on remainder
            if not trade.get("partial") and price >= trade["take_profit"]:
                symbol = trade["symbol"]
                asset  = symbol.replace("USDT", "")
                info   = _exchange_info.get(symbol, {})
                step   = info.get("step", 0.001)
                min_qty = info.get("min_qty", 0.001)
                coin_bal = get_coin_balance(asset)
                half_qty = round_step(coin_bal / 2, step)
                if half_qty >= min_qty and half_qty * price >= info.get("min_notional", 5.0):
                    try:
                        signed("/api/v3/order", "POST", {
                            "symbol":   symbol,
                            "side":     "SELL",
                            "type":     "MARKET",
                            "quantity": f"{half_qty:.8f}".rstrip("0").rstrip("."),
                        })
                        partial_pnl = round((price - trade["entry_price"]) / trade["entry_price"] * (trade["usd_size"] / 2), 3)
                        state["total_pnl"] = round(state.get("total_pnl", 0) + partial_pnl, 3)
                        state["daily_pnl"] = round(state.get("daily_pnl", 0) + partial_pnl, 3)
                        state["open_trades"][tid]["partial"] = True
                        state["open_trades"][tid]["usd_size"] = round(trade["usd_size"] / 2, 2)
                        state["open_trades"][tid]["trailing_stop"] = CFG["partial_tp_trailing"]
                        trade["partial"] = True
                        addlog(f"⚡ PARTIAL TP {symbol} @ {price:.6f} | Half sold | PnL: +{partial_pnl:.2f} | Trailing tightened to 1%")
                        save()
                    except Exception as e:
                        addlog(f"❌ PARTIAL SELL FAILED {symbol}: {e}", "error")
                else:
                    close(trade, price, "TP")
            elif price <= trade["stop_loss"]:
                close(trade, price, "SL")
            else:
                trail_pct = trade.get("trailing_stop", CFG["trailing_stop"])
                trail_sl = trade["high_price"] * (1 - trail_pct)
                if price <= trail_sl and price < trade["entry_price"] * 1.003:
                    close(trade, price, "TrailSL")

            time.sleep(0.3)

        except Exception as e:
            addlog(f"Stop check error {trade['symbol']}: {e}", "warning")

# ─── MAIN SCAN LOOP ───────────────────────────────────────────────────────────
def scan_loop():
    load_exchange_info()
    addlog("🚀 ApexBot V3 started")

    while state["running"]:
        try:
            check_daily_reset()
            state["scan_count"] += 1

            # Always check stops first
            if state["open_trades"]:
                check_stops()

            # Only scan for new signals if under max positions
            if len(state["open_trades"]) < CFG["max_positions"]:
                balance = get_balance()
                if balance is None:
                    addlog("Skipping scan — balance unavailable", "warning")
                elif balance < CFG["min_trade_usd"]:
                    addlog(f"Skipping scan — low balance ${balance}", "warning")
                else:
                    tickers    = pub("/api/v3/ticker/24hr")
                    relevant   = [t for t in tickers if t["symbol"] in COINS]
                    open_syms  = {t["symbol"] for t in state["open_trades"].values()}
                    candidates = [
                        (t, score(t)) for t in relevant
                        if t["symbol"] not in open_syms and score(t) >= CFG["min_score"]
                    ]
                    candidates.sort(key=lambda x: x[1], reverse=True)

                    mode = "peak" if is_peak() else "off-peak"
                    if not candidates:
                        addlog(f"Scan #{state['scan_count']} — no signals ({mode}) | Balance:${balance} | Open:{len(state['open_trades'])}")
                    else:
                        for ticker, sc in candidates[:3]:
                            if len(state["open_trades"]) >= CFG["max_positions"]:
                                break
                            price = float(ticker["lastPrice"])
                            addlog(f"📡 Signal [{sc}] {ticker['symbol']} +{float(ticker['priceChangePercent']):.1f}% | Vol:${float(ticker['quoteVolume'])/1e6:.1f}M")
                            buy(ticker["symbol"], price)
                            time.sleep(1)
            else:
                addlog(f"Max positions ({CFG['max_positions']}) open — monitoring only")

        except Exception as e:
            addlog(f"Scan error: {e}", "error")

        time.sleep(CFG["scan_interval"])

    addlog("Bot stopped")

# ─── START / STOP ─────────────────────────────────────────────────────────────
def start():
    if not state["running"]:
        load()
        state["running"] = True
        Thread(target=scan_loop, daemon=True).start()
        addlog("Bot thread started")

def stop():
    state["running"] = False
    addlog("Bot stopping...")
