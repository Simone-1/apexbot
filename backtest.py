import os, json, time, requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

DAYS=30; INTERVAL="15m"; CANDLE_LIMIT=1000; BASE="https://api.binance.com"
TRADE_USD=15; TP_PCT=2.5/100; SL_PCT=2.0/100; TRAIL_PCT=1.5/100
MIN_SCORE=55; RS_CANDLES=8; REPLACE_BOTTOM=0.30; MIN_VOL_USD=5_000_000
MAX_POSITIONS=8; PEAK_START=9; PEAK_END=23

ORIGINAL_COINS=["SOLUSDT","PEPEUSDT","DOGEUSDT","SHIBUSDT","FLOKIUSDT","BONKUSDT","WIFUSDT","MEMEUSDT","AVAXUSDT","APTUSDT","SUIUSDT","SEIUSDT","ARBUSDT","OPUSDT","FETUSDT","RENDERUSDT","WLDUSDT","1000SATSUSDT","ORDIUSDT","STXUSDT","TIAUSDT","JUPUSDT","EIGENUSDT","PYTHUSDT"]
EXCLUDE={"USDCUSDT","BUSDUSDT","TUSDUSDT","USDTUSDT","DAIUSDT","FDUSDUSDT","EURUSDT","GBPUSDT","BTCUSDT","ETHUSDT","WBTCUSDT","STETHUSDT","WETHUSDT","BETHUSDT","LDOETH","USD1USDT","UUSDT","LUNCUSDT","BANANAS31USDT","RLUSDUSDT","XAUTUSDT","PAXGUSDT","ZECUSDT","XUSDUSDT"}

def pub(path, params=None):
    try:
        r=requests.get(BASE+path, params=params, timeout=15); r.raise_for_status(); return r.json()
    except: return None

def get_candles(symbol, start_ms, end_ms):
    candles=[]; current=start_ms
    while current < end_ms:
        data=pub("/api/v3/klines",params={"symbol":symbol,"interval":INTERVAL,"startTime":current,"endTime":end_ms,"limit":CANDLE_LIMIT})
        if not data: break
        candles.extend(data)
        if len(data)<CANDLE_LIMIT: break
        current=data[-1][0]+1; time.sleep(0.05)
    return candles

def candles_to_dict(candles):
    return {c[0]:{"open":float(c[1]),"high":float(c[2]),"low":float(c[3]),"close":float(c[4]),"volume":float(c[5]),"quote_vol":float(c[7])} for c in candles}

def score_ticker(open_p, close_p, vol_usd, ts_ms):
    if open_p==0: return 0
    change=(close_p-open_p)/open_p*100; vol_m=vol_usd/1_000_000
    dt=datetime.fromtimestamp(ts_ms/1000,tz=timezone.utc); is_peak=PEAK_START<=dt.hour<PEAK_END
    score=0
    if change>1: score+=20
    if change>2: score+=15
    if change>3: score+=10
    if change>5: score+=10
    if vol_m>10: score+=10
    if vol_m>50: score+=10
    if vol_m>100: score+=5
    if is_peak: score+=10
    if change<0: score-=30
    return score

def fetch_all_candles(symbols, start_ms, end_ms):
    print(f"Fetching {len(symbols)} coins..."); all_data={}
    for i,sym in enumerate(symbols):
        print(f"  [{i+1}/{len(symbols)}] {sym}...",end=" ",flush=True)
        candles=get_candles(sym,start_ms,end_ms)
        if candles: all_data[sym]=candles_to_dict(candles); print(f"{len(candles)} candles")
        else: print("FAILED")
        time.sleep(0.1)
    return all_data

def calc_rs(symbol, ts_idx, timestamps, candle_data):
    if ts_idx<RS_CANDLES: return None
    sym_c=candle_data.get(symbol,{}); btc_c=candle_data.get("BTCUSDT",{})
    st=timestamps[ts_idx-RS_CANDLES]; et=timestamps[ts_idx]
    if st not in sym_c or et not in sym_c or st not in btc_c or et not in btc_c: return None
    so=sym_c[st]["open"]; sc=sym_c[et]["close"]; bo=btc_c[st]["open"]; bc=btc_c[et]["close"]
    if so==0 or bo==0: return None
    return (sc-so)/so*100-(bc-bo)/bo*100

def simulate(candle_data, timestamps, coin_selector, label):
    trades=[]; open_trades={}; trade_id=0
    for i,ts in enumerate(timestamps):
        for sym in list(open_trades.keys()):
            t=open_trades[sym]
            if sym not in candle_data or ts not in candle_data[sym]: continue
            c=candle_data[sym][ts]; price=c["close"]; high=c["high"]; low=c["low"]
            if high>t["high"]: t["high"]=high; t["trail_stop"]=t["high"]*(1-TRAIL_PCT)
            if high>=t["tp"]:
                pnl=(t["tp"]-t["entry"])/t["entry"]*TRADE_USD
                trades.append({**t,"exit":t["tp"],"pnl":round(pnl,3),"reason":"TP","close_ts":ts}); del open_trades[sym]; continue
            if low<=t["trail_stop"] and t["trail_stop"]>t["sl"]:
                pnl=(t["trail_stop"]-t["entry"])/t["entry"]*TRADE_USD
                trades.append({**t,"exit":t["trail_stop"],"pnl":round(pnl,3),"reason":"TrailSL","close_ts":ts}); del open_trades[sym]; continue
            if low<=t["sl"]:
                pnl=(t["sl"]-t["entry"])/t["entry"]*TRADE_USD
                trades.append({**t,"exit":t["sl"],"pnl":round(pnl,3),"reason":"SL","close_ts":ts}); del open_trades[sym]; continue
            if i-t["open_idx"]>=24:
                pnl=(price-t["entry"])/t["entry"]*TRADE_USD
                trades.append({**t,"exit":price,"pnl":round(pnl,3),"reason":"TimeExit","close_ts":ts}); del open_trades[sym]
        if len(open_trades)>=MAX_POSITIONS: continue
        watch=coin_selector(i); open_syms=set(open_trades.keys()); candidates=[]
        for sym in watch:
            if sym in open_syms or sym not in candle_data or ts not in candle_data[sym]: continue
            c=candle_data[sym][ts]; sc=score_ticker(c["open"],c["close"],c["quote_vol"],ts)
            if sc>=MIN_SCORE: candidates.append((sym,sc,c["close"]))
        candidates.sort(key=lambda x:x[1],reverse=True)
        for sym,sc,price in candidates[:3]:
            if len(open_trades)>=MAX_POSITIONS: break
            trade_id+=1
            open_trades[sym]={"id":trade_id,"symbol":sym,"entry":price,"tp":price*(1+TP_PCT),"sl":price*(1-SL_PCT),"trail_stop":price*(1-TRAIL_PCT),"high":price,"open_ts":ts,"open_idx":i,"score":sc}
    last_ts=timestamps[-1]
    for sym,t in open_trades.items():
        if sym in candle_data and last_ts in candle_data[sym]:
            price=candle_data[sym][last_ts]["close"]; pnl=(price-t["entry"])/t["entry"]*TRADE_USD
            trades.append({**t,"exit":price,"pnl":round(pnl,3),"reason":"Open","close_ts":last_ts})
    return trades

def make_rs_selector(candle_data, timestamps, all_symbols):
    cache={}; current_list=list(ORIGINAL_COINS)
    def selector(ts_idx):
        nonlocal current_list
        bucket=ts_idx//60
        if bucket not in cache:
            scores={}
            for sym in all_symbols:
                rs=calc_rs(sym,ts_idx,timestamps,candle_data)
                if rs is not None: scores[sym]=rs
            if scores:
                ranked=sorted(scores,key=lambda s:scores[s],reverse=True)
                n=len(current_list); n_keep=max(1,round(n*(1-REPLACE_BOTTOM)))
                cur_ranked=sorted(current_list,key=lambda s:scores.get(s,-999),reverse=True)
                keep=cur_ranked[:n_keep]
                new_entrants=[s for s in ranked if s not in set(keep)][:(n-len(keep))]
                current_list=list(dict.fromkeys(keep+new_entrants))
            cache[bucket]=current_list[:]
        return cache[bucket]
    return selector

def analyse(trades, label):
    if not trades: return {"label":label,"trades":0}
    pnls=[t["pnl"] for t in trades]; wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    total_pnl=round(sum(pnls),2); win_rate=round(len(wins)/len(pnls)*100,1)
    avg_pnl=round(sum(pnls)/len(pnls),3)
    avg_win=round(sum(wins)/len(wins),3) if wins else 0
    avg_loss=round(sum(losses)/len(losses),3) if losses else 0
    running=peak=max_dd=0
    for p in pnls:
        running+=p
        if running>peak: peak=running
        dd=peak-running
        if dd>max_dd: max_dd=dd
    reasons=defaultdict(int)
    for t in trades: reasons[t["reason"]]+=1
    return {"label":label,"trades":len(trades),"win_rate":win_rate,"total_pnl":total_pnl,"avg_pnl":avg_pnl,"avg_win":avg_win,"avg_loss":avg_loss,"max_drawdown":round(max_dd,2),"reasons":dict(reasons)}

def verdict(orig, rs):
    print("\n"+"="*50)
    print("   ApexBot Backtest Results - Last 30 Days")
    print("="*50)
    for r in [orig,rs]:
        print(f"\n{r['label']}"); print("-"*50)
        if r["trades"]==0: print("  No trades generated."); continue
        print(f"  Trades:        {r['trades']}"); print(f"  Win rate:      {r['win_rate']}%")
        print(f"  Total PnL:     ${r['total_pnl']:+.2f}"); print(f"  Avg PnL/trade: ${r['avg_pnl']:+.3f}")
        print(f"  Max drawdown:  ${r['max_drawdown']:.2f}"); print(f"  Exit reasons:  {r['reasons']}")
    print("\n"+"="*50); print("  VERDICT"); print("="*50)
    if orig["trades"]==0 or rs["trades"]==0: print("\n  Not enough trades to compare."); return
    pnl_diff=rs["total_pnl"]-orig["total_pnl"]; wr_diff=rs["win_rate"]-orig["win_rate"]
    dd_diff=orig["max_drawdown"]-rs["max_drawdown"]; points=0; reasons=[]
    if rs["total_pnl"]>orig["total_pnl"]: points+=1; reasons.append(f"RS Scanner made ${pnl_diff:+.2f} more PnL")
    else: points-=1; reasons.append(f"RS Scanner made ${pnl_diff:.2f} less PnL")
    if wr_diff>2: points+=1; reasons.append(f"Win rate improved by {wr_diff:.1f} points")
    elif wr_diff<-2: points-=1; reasons.append(f"Win rate dropped by {abs(wr_diff):.1f} points")
    else: reasons.append(f"Win rate similar ({wr_diff:+.1f} points)")
    if dd_diff>0: points+=1; reasons.append(f"Lower max drawdown by ${dd_diff:.2f}")
    else: reasons.append(f"Higher max drawdown by ${abs(dd_diff):.2f}")
    if rs["trades"]>=30: points+=1; reasons.append(f"Enough trades for confidence ({rs['trades']})")
    else: reasons.append(f"Low trade count ({rs['trades']}) - results may not be reliable")
    print()
    for r in reasons: print(f"  {r}")
    print()
    if points>=3: print("  CONCLUSION: RS Scanner is performing better.\n  SAFE TO RAISE TRADE SIZE TO $20")
    elif points>=1: print("  CONCLUSION: RS Scanner slightly better but not conclusive.\n  KEEP TRADE SIZE AT $10-15 for 2 more weeks.")
    else: print("  CONCLUSION: RS Scanner is NOT outperforming.\n  DO NOT raise trade size. Review scanner logic.")
    print("\n"+"="*50+"\n")

if __name__=="__main__":
    print("\n=== ApexBot Backtester ===")
    now_ms=int(time.time()*1000); start_ms=now_ms-DAYS*24*60*60*1000
    print("\nFetching eligible symbols...")
    tickers=pub("/api/v3/ticker/24hr"); eligible=[]
    if tickers:
        for t in tickers:
            sym=t["symbol"]
            if not sym.endswith("USDT") or sym in EXCLUDE or not sym.isascii(): continue
            try:
                if float(t["quoteVolume"])>=MIN_VOL_USD: eligible.append(sym)
            except: continue
    print(f"Found {len(eligible)} eligible symbols")
    all_symbols=list(set(eligible+ORIGINAL_COINS+["BTCUSDT"]))
    candle_data=fetch_all_candles(all_symbols,start_ms,now_ms)
    if "BTCUSDT" not in candle_data: print("ERROR: No BTC data."); exit(1)
    timestamps=sorted(candle_data["BTCUSDT"].keys())
    print(f"Timeline: {len(timestamps)} candles")
    print("\nRunning simulation 1: Original list...")
    orig_trades=simulate(candle_data,timestamps,lambda i:ORIGINAL_COINS,"Original Hardcoded List")
    print(f"Done - {len(orig_trades)} trades")
    print("\nRunning simulation 2: RS Scanner...")
    rs_selector=make_rs_selector(candle_data,timestamps,eligible)
    rs_trades=simulate(candle_data,timestamps,rs_selector,"RS Scanner (Dynamic List)")
    print(f"Done - {len(rs_trades)} trades")
    verdict(analyse(orig_trades,"Original Hardcoded List"),analyse(rs_trades,"RS Scanner (Dynamic List)"))
