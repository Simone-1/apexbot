import os, time, hmac, hashlib, requests, json, logging, threading
from datetime import datetime, timezone
from threading import Thread

_save_lock = threading.Lock()


# ─── TELEGRAM ALERTS ──────────────────────────────────────────────────────────
def telegram(msg):
    try:
        token = os.environ.get("TELEGRAM_TOKEN","")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID","")
        if not token or not chat_id:
            # fallback to /etc/environment
            env = open("/etc/environment").read()
            if not token:
                token = env.split("TELEGRAM_TOKEN=")[1].split("\n")[0]
            if not chat_id:
                chat_id = env.split("TELEGRAM_CHAT_ID=")[1].split("\n")[0]
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=5
        )
    except:
        pass
# ─── CONFIG ───────────────────────────────────────────────────────────────────
CFG = {
    "min_trade_usd":   20,       # Minimum trade size in USDT
    "max_trade_usd":   20,       # Maximum trade size in USDT
    "max_positions":   8,        # Max concurrent open trades
    "take_profit":     0.030,    # 3.0% take profit
    "stop_loss":       0.020,    # 2.0% hard stop loss
    "trailing_stop":   0.025,    # 2.5% trailing stop from peak
    "min_score":       35,       # Minimum signal score to buy
    "max_pump":        15,       # Ignore coins already pumped > 15%
    "min_rise":        1.5,      # Minimum 24h rise % to consider
    "scan_interval":   30,       # Seconds between scans
    "peak_hours":      (9, 23), # UTC hours for peak market activity
    "partial_tp_trailing": 0.015,  # 1.5% trailing stop after partial TP
    "max_trade_hours":     6,      # Close trade if open longer than this
}

COINS = [
    # Confirmed working on this account
    "AVAXUSDT", "DOGEUSDT", "FETUSDT", "GALAUSDT",
    "OPUSDT", "PEPEUSDT", "RENDERUSDT", "SUIUSDT",
    # Likely working — similar tier
    "SOLUSDT", "SHIBUSDT", "WIFUSDT", "MEMEUSDT",
    "FLOKIUSDT", "ARBUSDT", "SEIUSDT", "NEARUSDT",
    "APTUSDT", "STXUSDT", "LINKUSDT",
    "ADAUSDT", "DOTUSDT", "LTCUSDT", "BNBUSDT",
    "UNIUSDT", "AAVEUSDT", "INJUSDT", "RUNEUSDT",
    "PENDLEUSDT", "STRKUSDT", "BLURUSDT", "ZETAUSDT",
    "ICPUSDT", "JTOUSDT"
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
    "last_buy_time": 0,  # timestamp of last buy — for cooldown
    "market_mode":   "neutral",
    "btc_change_24h": 0.0,
    "btc_change_7d":  0.0,
    "balance_cache":  0.0,
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
    with _save_lock:
        try:
            # Preserve keys written by other processes (e.g. scanner.py)
            try:
                with open("state.json") as f:
                    existing = json.load(f)
            except:
                existing = {}
            data = {**existing, **state}
            with open("state.json", "w") as f:
                json.dump(data, f, default=str)
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
    save()

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
def get_short_term_momentum(symbol):
    """Get 15min momentum: recent price change and volume spike."""
    try:
        candles = pub("/api/v3/klines", params={"symbol": symbol, "interval": "15m", "limit": 10})
        if not candles or len(candles) < 6:
            return 0.0, 1.0
        # Price change over last 2 candles (30 mins)
        open_price  = float(candles[-3][1])
        close_price = float(candles[-1][4])
        pct_15m = ((close_price - open_price) / open_price) * 100 if open_price > 0 else 0.0
        # Volume spike: last 2 candles vs previous 4
        recent_vol = sum(float(candles[i][5]) * float(candles[i][4]) for i in [-3, -2, -1])
        prev_vol   = sum(float(candles[i][5]) * float(candles[i][4]) for i in range(-7, -3))
        avg_prev   = prev_vol / 4 if prev_vol > 0 else 1.0
        vol_ratio  = (recent_vol / 3) / avg_prev if avg_prev > 0 else 1.0
        return pct_15m, vol_ratio
    except:
        return 0.0, 1.0

def get_hourly_volume(symbol):
    """Get volume for the last hour vs previous 4 hours average."""
    try:
        candles = pub("/api/v3/klines", params={"symbol": symbol, "interval": "1h", "limit": 5})
        if not candles or len(candles) < 5:
            return 1.0
        last_hour_vol = float(candles[-2][5]) * float(candles[-2][4])
        prev_vols = [float(candles[i][5]) * float(candles[i][4]) for i in range(-5, -2)]
        avg_vol = sum(prev_vols) / len(prev_vols)
        if avg_vol <= 0:
            return 1.0
        return last_hour_vol / avg_vol
    except:
        return 1.0

def score(ticker):
    try:
        pct   = float(ticker["priceChangePercent"])
        price = float(ticker["lastPrice"])
        avg   = float(ticker["weightedAvgPrice"])
        vol   = float(ticker["quoteVolume"])

        if pct < CFG["min_rise"] or price <= 0 or avg <= 0:
            return 0

        # Minimum volume filter
        if vol < 20_000_000:
            return 0

        # Get short-term momentum (primary signal)
        pct_15m, vol_ratio_15m = get_short_term_momentum(ticker["symbol"])

        # Must be moving up in last 30 mins — if not, skip entirely
        if pct_15m <= 0:
            return 0

        s = 0

        # SHORT-TERM MOMENTUM — primary signal (up to 40 pts)
        if pct_15m >= 3.0:   s += 40
        elif pct_15m >= 2.0: s += 30
        elif pct_15m >= 1.0: s += 20
        elif pct_15m >= 0.5: s += 10

        # SHORT-TERM VOLUME SPIKE (up to 25 pts)
        if vol_ratio_15m >= 5:    s += 25
        elif vol_ratio_15m >= 3:  s += 18
        elif vol_ratio_15m >= 2:  s += 12
        elif vol_ratio_15m >= 1.5: s += 6

        # 24h trend confirmation — coin should be in uptrend on the day (up to 15 pts)
        if pct >= 3:   s += 15
        elif pct >= 1: s += 8

        # Price above weighted average — still bullish on day (up to 10 pts)
        pva = ((price - avg) / avg) * 100
        if pva > 0:
            s += min(pva * 2, 10)

        # Peak hours bonus
        if is_peak(): s += 10

        return min(int(s), 100)
    except:
        return 0

# ─── TRADE SIZE ───────────────────────────────────────────────────────────────
def calc_trade_size(balance, score=None):
    """Size trade between min and max based on balance and signal confidence."""
    if balance is None or balance < CFG["min_trade_usd"]:
        return None
    mn = CFG["min_trade_usd"]
    mx = CFG["max_trade_usd"]
    # Scale size by signal score if provided
    if score is not None:
        if score >= 80:
            size = mx                          # high confidence -> max
        elif score >= 65:
            size = round(mn + (mx - mn) * 0.5, 2)  # medium -> midpoint
        else:
            size = mn                          # low confidence -> min
    else:
        size = round(balance * 0.08, 2)
        size = max(mn, min(mx, size))
    # Make sure we have enough left after this trade
    if balance < size + mn:
        size = mn
    if balance < size:
        return None
    return size

# ─── BUY ──────────────────────────────────────────────────────────────────────
BLOCKED_SYMBOLS = {"1000SATSUSDT", "ORDIUSDT"}  # Permanently restricted on this account

BUY_COOLDOWN_SECS = 0  # 15 minutes between new position opens

def buy(symbol, price, score=None):
    if symbol in BLOCKED_SYMBOLS:
        return
    # Cooldown check — don't open positions too close together
    last_buy = state.get("last_buy_time", 0)
    if time.time() - last_buy < BUY_COOLDOWN_SECS:
        remaining = int((BUY_COOLDOWN_SECS - (time.time() - last_buy)) / 60)
        addlog(f"Skipping {symbol} — cooldown active ({remaining}min remaining)", "warning")
        return
    balance = get_balance()
    trade_usd = calc_trade_size(balance, score)

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
        state["last_buy_time"] = time.time()
        telegram(f"📈 BUY {symbol} @ {price:.6f} | ${trade_usd}")
        addlog(f"✅ BOUGHT {symbol} @ {price:.6f} | Size:${trade_usd} | TP:{tp:.6f} | SL:{sl:.6f}")
        save()

    except Exception as e:
        try:
            msg = e.response.text if hasattr(e, 'response') else 'no response'
            addlog(f"❌ BUY FAILED {symbol}: {e} | Response: {msg}", "error")
            if '-2010' in str(msg):
                BLOCKED_SYMBOLS.add(symbol)
                addlog(f"⛔ Auto-blocked {symbol} — not permitted on this account", "warning")
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
    # Reset cooldown after a loss — don't buy again for 15 minutes
    if pnl < 0:
        state["last_buy_time"] = time.time()
        addlog(f"⏸ Cooldown reset after loss — no new buys for 15 minutes")

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
    telegram(f"{emoji} {reason} {trade['symbol']} | PnL: {'+' if pnl>=0 else ''}{pnl:.2f}")
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
            # Note: "imported" trades skip time exit since we don't know when they opened
            if trade.get("open_time") and trade["open_time"] != "imported":
                try:
                    opened = datetime.strptime(trade["open_time"], "%H:%M %d/%m").replace(
                        year=datetime.now(timezone.utc).year)
                    hours_open = (datetime.now(timezone.utc) - opened.replace(tzinfo=timezone.utc)).total_seconds() / 3600
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
                # Use half of actual coin balance (more reliable than stored qty)
                half_qty = round_step(coin_bal / 2, step)
                # Fallback to stored qty if balance lookup fails
                if half_qty < min_qty:
                    half_qty = round_step(trade.get("qty", 0) / 2, step)
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
                if price <= trail_sl:
                    close(trade, price, "TrailSL")

            time.sleep(0.3)

        except Exception as e:
            addlog(f"Stop check error {trade['symbol']}: {e}", "warning")

# ─── MARKET MODE ──────────────────────────────────────────────────────────────
# Settings for each market mode
MARKET_MODES = {
    "bull":    {"take_profit": 0.045, "trailing_stop": 0.035, "stop_loss": 0.020, "partial_tp_trailing": 0.020},
    "neutral": {"take_profit": 0.030, "trailing_stop": 0.025, "stop_loss": 0.020, "partial_tp_trailing": 0.015},
    "bear":    {"take_profit": 0.020, "trailing_stop": 0.015, "stop_loss": 0.015, "partial_tp_trailing": 0.010},
}

def get_market_mode():
    """Determine market mode based on BTC 24h and 7d performance."""
    try:
        # 24h change
        ticker = pub("/api/v3/ticker/24hr", {"symbol": "BTCUSDT"})
        change_24h = float(ticker["priceChangePercent"])

        # 7d change — use weekly klines
        candles_7d = pub("/api/v3/klines", params={"symbol": "BTCUSDT", "interval": "1d", "limit": 8})
        if candles_7d and len(candles_7d) >= 7:
            week_open = float(candles_7d[-7][1])
            week_close = float(candles_7d[-1][4])
            change_7d = (week_close - week_open) / week_open * 100
        else:
            change_7d = 0

        # Determine mode
        if change_24h >= 2 and change_7d >= 5:
            mode = "bull"
        elif change_24h <= -2 or change_7d <= -5:
            mode = "bear"
        else:
            mode = "neutral"

        return mode, change_24h, change_7d
    except:
        return "neutral", 0, 0

def apply_market_mode():
    """Apply dynamic settings based on current market mode."""
    mode, change_24h, change_7d = get_market_mode()
    settings = MARKET_MODES[mode]
    prev_mode = state.get("market_mode", "neutral")

    # Update CFG with mode settings
    CFG["take_profit"]         = settings["take_profit"]
    CFG["trailing_stop"]       = settings["trailing_stop"]
    CFG["stop_loss"]           = settings["stop_loss"]
    CFG["partial_tp_trailing"] = settings["partial_tp_trailing"]

    state["market_mode"]    = mode
    state["btc_change_24h"] = round(change_24h, 2)
    state["btc_change_7d"]  = round(change_7d, 2)

    if mode != prev_mode:
        emoji = "🟢" if mode == "bull" else "🔴" if mode == "bear" else "🟡"
        msg = (emoji + " Market mode changed: " + prev_mode.upper() + " -> " + mode.upper() + "\n"
               + "BTC 24h: " + f"{change_24h:+.1f}%" + " | 7d: " + f"{change_7d:+.1f}%" + "\n"
               + "TP: " + f"{settings['take_profit']*100:.1f}%" + " | Trail: " + f"{settings['trailing_stop']*100:.1f}%" + " | SL: " + f"{settings['stop_loss']*100:.1f}%")
        addlog(msg)
        telegram(msg)

    return mode, change_24h, change_7d

def send_daily_report():
    """Send daily BTC analysis and bot summary to Telegram."""
    try:
        mode, change_24h, change_7d = get_market_mode()
        settings = MARKET_MODES[mode]
        emoji = "🟢" if mode == "bull" else "🔴" if mode == "bear" else "🟡"

        # Trade summary
        trades = state.get("closed_trades", [])
        today = datetime.now(timezone.utc).strftime("%d/%m")
        today_trades = [t for t in trades if today in str(t.get("close_time", ""))]
        wins = [t for t in today_trades if t.get("pnl", 0) > 0]
        losses = [t for t in today_trades if t.get("pnl", 0) < 0]
        daily_pnl = sum(t.get("pnl", 0) for t in today_trades)

        btc_price = pub("/api/v3/ticker/price", {"symbol": "BTCUSDT"})["price"]

        divider = "-" * 30
        tp_str = f"{settings['take_profit']*100:.1f}%"
        trail_str = f"{settings['trailing_stop']*100:.1f}%"
        sl_str = f"{settings['stop_loss']*100:.1f}%"
        btc_fmt = f"${float(btc_price):,.0f}"
        msg = ("📊 ApexBot Daily Report\n"
               + divider + "\n"
               + "BTC: " + btc_fmt + "\n"
               + "24h: " + f"{change_24h:+.1f}%" + " | 7d: " + f"{change_7d:+.1f}%" + "\n"
               + "\n" + emoji + " Market Mode: " + mode.upper() + "\n"
               + "TP: " + tp_str + " | Trail: " + trail_str + " | SL: " + sl_str + "\n"
               + "\n📈 Yesterday trades:\n"
               + "Wins: " + str(len(wins)) + " | Losses: " + str(len(losses)) + "\n"
               + "PnL: " + f"{daily_pnl:+.2f}" + "\n"
               + "Total PnL: " + f"{state.get('total_pnl', 0):+.2f}" + "\n"
               + "Balance: $" + f"{state.get('balance_cache', 0):.2f}")
        telegram(msg)
        addlog("Daily report sent to Telegram")
    except Exception as e:
        addlog(f"Daily report failed: {e}", "error")

# ─── BTC MARKET FILTER ────────────────────────────────────────────────────────
def btc_is_dumping():
    """Return True if BTC is dumping on short or medium timeframe."""
    try:
        # Check 1: dropped more than 1.5% in last 15 minutes (3 x 5m candles)
        candles_5m = pub("/api/v3/klines", params={"symbol":"BTCUSDT","interval":"5m","limit":4})
        if candles_5m and len(candles_5m) >= 3:
            open_15m  = float(candles_5m[-3][1])
            close_15m = float(candles_5m[-1][4])
            change_15m = (close_15m - open_15m) / open_15m * 100
            if change_15m < -1.5:
                addlog(f"⚠️ BTC down {change_15m:.1f}% in last 15min — pausing new buys", "warning")
                return True

        # Check 2: dropped more than 3% in last hour
        candles_1h = pub("/api/v3/klines", params={"symbol":"BTCUSDT","interval":"1h","limit":2})
        if candles_1h and len(candles_1h) >= 2:
            open_1h  = float(candles_1h[-1][1])
            close_1h = float(candles_1h[-1][4])
            change_1h = (close_1h - open_1h) / open_1h * 100
            if change_1h < -3:
                addlog(f"⚠️ BTC down {change_1h:.1f}% in last hour — pausing new buys", "warning")
                return True

        # Check 3: BTC is in a slow downtrend — below today's open price
        try:
            midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            midnight_ts = int(midnight.timestamp() * 1000)
            candles_day = pub("/api/v3/klines", params={"symbol":"BTCUSDT","interval":"1h","limit":1,"startTime":midnight_ts})
            if candles_day:
                day_open = float(candles_day[0][1])
                current_btc = float(pub("/api/v3/ticker/price", {"symbol":"BTCUSDT"})["price"])
                btc_day_change = (current_btc - day_open) / day_open * 100
                if btc_day_change < -1.5:
                    addlog(f"⚠️ BTC down {btc_day_change:.1f}% today — slow downtrend, pausing new buys", "warning")
                    return True
        except:
            pass

        return False
    except:
        return False

# ─── MAIN SCAN LOOP ───────────────────────────────────────────────────────────
def scan_loop():
    load_exchange_info()
    addlog("🚀 ApexBot V3 started")
    state["symbols"] = COINS  # populate dashboard coin list

    # Track daily report time
    last_report_day = ""
    last_mode_check = 0

    while state["running"]:
        try:
            check_daily_reset()
            state["scan_count"] += 1

            # Apply market mode every 5 minutes
            if time.time() - last_mode_check > 300:
                apply_market_mode()
                last_mode_check = time.time()

            # Send daily report at 08:00 UTC
            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.strftime("%Y-%m-%d")
            if now_utc.hour == 8 and now_utc.minute < 1 and last_report_day != today_str:
                send_daily_report()
                last_report_day = today_str

            # Always check stops first
            if state["open_trades"]:
                check_stops()

            # Market breadth check — if majority of watchlist is falling, don't buy
            def market_is_weak(tickers_data, coins_list):
                try:
                    relevant_t = [t for t in tickers_data if t["symbol"] in set(coins_list)]
                    if not relevant_t: return False
                    down = sum(1 for t in relevant_t if float(t["priceChangePercent"]) < 0)
                    pct_down = down / len(relevant_t)
                    if pct_down > 0.6:
                        addlog(f"⚠️ Market weak — {pct_down*100:.0f}% of watchlist coins falling, pausing new buys", "warning")
                        return True
                    return False
                except:
                    return False

            # Only scan for new signals if under max positions
            if len(state["open_trades"]) < CFG["max_positions"] and not btc_is_dumping():
                balance = get_balance()
                if balance is not None:
                    state["balance_cache"] = balance
                if balance is None:
                    addlog("Skipping scan — balance unavailable", "warning")
                elif balance < CFG["min_trade_usd"]:
                    addlog(f"Skipping scan — low balance ${balance}", "warning")
                else:
                    tickers    = pub("/api/v3/ticker/24hr")
                    coins = state.get("symbols", COINS)
                    relevant   = [t for t in tickers if t["symbol"] in coins]
                    open_syms  = {t["symbol"] for t in state["open_trades"].values()}

                    # Save all scores and 24h changes to state for dashboard (always, even if market weak)
                    all_scores = {t["symbol"]: score(t) for t in relevant}
                    all_changes = {t["symbol"]: round(float(t["priceChangePercent"]), 2) for t in relevant}
                    state["coin_scores"] = all_scores
                    state["coin_changes"] = all_changes
                    state["coin_volumes"] = {t["symbol"]: round(float(t["quoteVolume"])/1e6, 1) for t in relevant}
                    state["coin_price_vs_avg"] = {t["symbol"]: round(((float(t["lastPrice"])-float(t["weightedAvgPrice"]))/float(t["weightedAvgPrice"]))*100, 2) for t in relevant}

                    # Skip if market breadth is weak
                    if market_is_weak(tickers, coins):
                        mode = "peak" if is_peak() else "off-peak"
                        addlog(f"Scan #{state['scan_count']} — market weak ({mode}) | Balance:${balance} | Open:{len(state['open_trades'])}")
                        time.sleep(CFG["scan_interval"])
                        continue

                    candidates = [
                        (t, score(t)) for t in relevant
                        if t["symbol"] not in open_syms and t["symbol"] not in BLOCKED_SYMBOLS
                        and score(t) >= CFG["min_score"]
                    ]
                    candidates.sort(key=lambda x: x[1], reverse=True)

                    mode = "peak" if is_peak() else "off-peak"
                    if not candidates:
                        # Log top 3 scores for debugging
                        top = sorted([(t["symbol"], score(t)) for t in relevant], key=lambda x: x[1], reverse=True)[:3]
                        top_str = " | ".join([f"{s[0]}:{s[1]}" for s in top if s[1] > 0])
                        addlog(f"Scan #{state['scan_count']} — no signals ({mode}) | Balance:${balance} | Open:{len(state['open_trades'])}" + (f" | Top: {top_str}" if top_str else ""))
                    else:
                        for ticker, sc in candidates[:3]:
                            if len(state["open_trades"]) >= CFG["max_positions"]:
                                break
                            price = float(ticker["lastPrice"])
                            addlog(f"📡 Signal [{sc}] {ticker['symbol']} +{float(ticker['priceChangePercent']):.1f}% | Vol:${float(ticker['quoteVolume'])/1e6:.1f}M")
                            buy(ticker["symbol"], price, sc)
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
        telegram("🚀 ApexBot started")

def stop():
    state["running"] = False
    addlog("Bot stopping...")
