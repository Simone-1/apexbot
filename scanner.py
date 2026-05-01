import os, json, time, tempfile, logging, requests

STATE_FILE     = "/root/apexbot/state.json"
SCAN_INTERVAL  = 900
MIN_VOLUME_USD = 5_000_000
REPLACE_BOTTOM = 0.30
RS_CANDLES     = 8
BASE           = "https://api.binance.com"

EXCLUDE = {"USDCUSDT","BUSDUSDT","TUSDUSDT","USDTUSDT","DAIUSDT","FDUSDUSDT","EURUSDT","GBPUSDT","BTCUSDT","ETHUSDT","WBTCUSDT","STETHUSDT","WETHUSDT","BETHUSDT","LDOETH", "USD1USDT", "UUSDT", "LUNCUSDT", "BANANAS31USDT"}

FALLBACK_COINS = ["SOLUSDT","PEPEUSDT","DOGEUSDT","SHIBUSDT","FLOKIUSDT","BONKUSDT","WIFUSDT","MEMEUSDT","AVAXUSDT","APTUSDT","SUIUSDT","SEIUSDT","ARBUSDT","OPUSDT","FETUSDT","RENDERUSDT","WLDUSDT","1000SATSUSDT","ORDIUSDT","STXUSDT","TIAUSDT","JUPUSDT","EIGENUSDT","PYTHUSDT"]

logging.basicConfig(level=logging.INFO,format="%(asctime)s [SCANNER] %(message)s",handlers=[logging.StreamHandler(),logging.FileHandler("/root/apexbot/scanner.log",mode="a")])
log = logging.getLogger("scanner")

def pub(path, params=None):
    try:
        r = requests.get(BASE+path, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error(f"API error {path}: {e}")
        return None

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Failed to load state.json: {e}")
    return {}

def save_symbols(symbols):
    state = load_state()
    state["symbols"] = symbols
    try:
        dir_ = os.path.dirname(STATE_FILE)
        with tempfile.NamedTemporaryFile("w",dir=dir_,delete=False,suffix=".tmp") as tmp:
            json.dump(state,tmp,indent=2)
            tmp_path = tmp.name
        os.replace(tmp_path,STATE_FILE)
        log.info(f"state.json updated with {len(symbols)} symbols")
    except Exception as e:
        log.error(f"Failed to write state.json: {e}")

def get_eligible_symbols():
    tickers = pub("/api/v3/ticker/24hr")
    if not tickers:
        return []
    eligible = []
    for t in tickers:
        sym = t["symbol"]
        if not sym.endswith("USDT") or sym in EXCLUDE or not sym.isascii():
            continue
        try:
            if float(t["quoteVolume"]) >= MIN_VOLUME_USD:
                eligible.append(sym)
        except (KeyError,ValueError):
            continue
    log.info(f"Eligible universe: {len(eligible)} symbols")
    return eligible

def get_rs_score(symbol):
    ck = pub("/api/v3/klines",params={"symbol":symbol,"interval":"15m","limit":RS_CANDLES+1})
    bk = pub("/api/v3/klines",params={"symbol":"BTCUSDT","interval":"15m","limit":RS_CANDLES+1})
    if not ck or not bk or len(ck)<2 or len(bk)<2:
        return None
    try:
        cr = (float(ck[-1][4])-float(ck[0][1]))/float(ck[0][1])*100
        br = (float(bk[-1][4])-float(bk[0][1]))/float(bk[0][1])*100
        return round(cr-br,4)
    except:
        return None

def run_scan():
    log.info("--- Scanner cycle starting ---")
    state = load_state()
    current_coins = state.get("symbols",FALLBACK_COINS)
    n = len(current_coins)
    protected = {t["symbol"] for t in state.get("open_trades",{}).values()}
    if protected:
        log.info(f"Protected: {protected}")
    eligible = get_eligible_symbols()
    if not eligible:
        log.warning("No eligible symbols — skipping")
        return
    log.info(f"Scoring {len(eligible)} coins...")
    scores = {}
    for sym in eligible:
        s = get_rs_score(sym)
        if s is not None:
            scores[sym] = s
        time.sleep(0.1)
    if not scores:
        log.warning("No scores — skipping")
        return
    ranked = sorted(scores,key=lambda s:scores[s],reverse=True)
    n_keep = max(1,round(n*(1-REPLACE_BOTTOM)))
    current_ranked = sorted(current_coins,key=lambda s:scores.get(s,-999),reverse=True)
    keep = current_ranked[:n_keep]
    drop = current_ranked[n_keep:]
    for sym in drop[:]:
        if sym in protected:
            keep.append(sym)
            drop.remove(sym)
    new_entrants = [s for s in ranked if s not in set(keep)][:(n-len(keep))]
    new_coins = list(dict.fromkeys(keep+new_entrants))
    dropped = [s for s in current_coins if s not in new_coins]
    added   = [s for s in new_coins if s not in current_coins]
    if dropped: log.info(f"Dropped: {dropped}")
    if added:   log.info(f"Added:   {added}")
    log.info(f"Top 5 RS: {[(s,scores[s]) for s in ranked[:5]]}")
    save_symbols(new_coins)
    log.info(f"--- Done. Watching {len(new_coins)} coins ---")

if __name__ == "__main__":
    log.info("Scanner started")
    while True:
        try:
            run_scan()
        except Exception as e:
            log.error(f"Error: {e}")
        time.sleep(SCAN_INTERVAL)
