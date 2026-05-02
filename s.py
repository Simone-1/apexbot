import json, os, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from bot import state, start, stop, get_balance, CFG

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ApexBot V3</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d0f14;color:#e2e8f0;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
  .header{background:#161b27;border-bottom:1px solid #2d3748;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
  .logo{font-size:1.4rem;font-weight:700;color:#63b3ed;letter-spacing:1px}
  .status-pill{padding:6px 16px;border-radius:999px;font-size:.8rem;font-weight:600;letter-spacing:.5px}
  .status-pill.running{background:#22543d;color:#68d391}
  .status-pill.stopped{background:#742a2a;color:#fc8181}
  .controls{display:flex;gap:10px}
  button{padding:8px 20px;border:none;border-radius:8px;cursor:pointer;font-size:.85rem;font-weight:600;transition:opacity .2s}
  button:hover{opacity:.85}
  .btn-start{background:#38a169;color:#fff}
  .btn-stop{background:#e53e3e;color:#fff}
  .btn-restart{background:#3182ce;color:#fff}
  .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;padding:20px 24px}
  .card{background:#161b27;border:1px solid #2d3748;border-radius:12px;padding:16px}
  .card-label{font-size:.72rem;color:#718096;text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px}
  .card-value{font-size:1.4rem;font-weight:700}
  .green{color:#68d391}.red{color:#fc8181}.blue{color:#63b3ed}.yellow{color:#f6e05e}
  .section{padding:0 24px 20px}
  .section-title{font-size:.85rem;font-weight:600;color:#718096;text-transform:uppercase;letter-spacing:.8px;margin-bottom:12px}
  table{width:100%;border-collapse:collapse;font-size:.82rem}
  th{text-align:left;padding:8px 12px;color:#718096;border-bottom:1px solid #2d3748;font-weight:500}
  td{padding:8px 12px;border-bottom:1px solid #1a202c}
  tr:hover td{background:#1a202c}
  .badge{padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:600}
  .badge-open{background:#2a4365;color:#63b3ed}
  .badge-tp{background:#22543d;color:#68d391}
  .badge-sl{background:#742a2a;color:#fc8181}
  .badge-trail{background:#44337a;color:#b794f4}
  .logs{background:#0a0c10;border:1px solid #2d3748;border-radius:12px;padding:16px;max-height:320px;overflow-y:auto;font-family:'JetBrains Mono','Courier New',monospace;font-size:.75rem}
  .log-info{color:#a0aec0}
  .log-warning{color:#f6e05e}
  .log-error{color:#fc8181}
  .log-time{color:#4a5568;margin-right:8px}
  .empty{color:#4a5568;font-style:italic;padding:12px 0}
  .pnl-pos{color:#68d391}
  .pnl-neg{color:#fc8181}
  .config-bar{display:flex;flex-wrap:wrap;gap:8px;padding:0 24px 16px}
  .config-tag{background:#1a202c;border:1px solid #2d3748;border-radius:6px;padding:4px 12px;font-size:.75rem;color:#a0aec0}
  .config-tag span{color:#e2e8f0;font-weight:600}
  .coins-bar{display:flex;flex-wrap:wrap;gap:6px;padding:0 24px 20px}
  .coin-tag{background:#1a1f2e;border:1px solid #2d3748;border-radius:4px;padding:2px 8px;font-size:.72rem;color:#63b3ed;font-weight:600}
  .tip{position:relative;cursor:help}
  .tip::after{content:attr(data-tip);position:absolute;bottom:130%;left:50%;transform:translateX(-50%);background:#1a202c;color:#e2e8f0;padding:6px 10px;border-radius:6px;font-size:.72rem;white-space:nowrap;border:1px solid #2d3748;opacity:0;pointer-events:none;transition:opacity .2s;z-index:99}
  .tip:hover::after{opacity:1}
  @media(max-width:600px){.metrics{grid-template-columns:1fr 1fr}.header{flex-direction:column;align-items:flex-start}}
</style>
</head>
<body>
<div class="header">
  <div class="logo">⚡ ApexBot V3</div>
  <div id="status-pill" class="status-pill stopped">STOPPED</div>
  <div class="controls">
    <button class="btn-start" onclick="action('start')">▶ Start</button>
    <button class="btn-stop" onclick="action('stop')">■ Stop</button>
    <button class="btn-restart" onclick="action('restart')">↺ Restart</button>
  </div>
</div>

<div class="metrics" id="metrics">
  <div class="card"><div class="card-label">Balance</div><div class="card-value blue" id="m-balance">—</div></div>
  <div class="card"><div class="card-label">Portfolio Value</div><div class="card-value blue" id="m-portfolio">—</div></div>
  <div class="card"><div class="card-label">Open Positions</div><div class="card-value yellow" id="m-open">—</div></div>
  <div class="card"><div class="card-label">Today's PnL</div><div class="card-value" id="m-daily">—</div></div>
  <div class="card"><div class="card-label">Total PnL</div><div class="card-value" id="m-total">—</div></div>
  <div class="card"><div class="card-label">Scans</div><div class="card-value" id="m-scans">—</div></div>
  <div class="card"><div class="card-label">Closed Trades</div><div class="card-value" id="m-closed">—</div></div>
</div>

<div class="config-bar">
  <div class="config-tag tip" data-tip="Hours when the bot actively looks for new trades">⏰ Peak Hours <span>09:00–23:00 UTC</span></div>
  <div class="config-tag tip" data-tip="Sells half your position when price rises 2.5% from entry">🎯 Take Profit <span>2.5%</span></div>
  <div class="config-tag tip" data-tip="Closes the full position if price drops 2% from entry to limit losses">🛑 Stop Loss <span>2.0%</span></div>
  <div class="config-tag tip" data-tip="Follows price upward and sells if price drops 1.5% from its peak">📉 Trailing Stop <span>1.5%</span></div>
  <div class="config-tag tip" data-tip="Amount spent per trade, sized at 8% of available balance">💰 Trade Size <span>$10–$20</span></div>
  <div class="config-tag tip" data-tip="Maximum number of trades open at the same time">📊 Max Positions <span>8</span></div>
  <div class="config-tag tip" data-tip="Minimum score a coin must reach before the bot buys. Score is based on price momentum, volume and time of day">🔍 Min Signal <span>50</span></div>
</div>

<div class="section">
  <div class="section-title">Coins Being Traded</div>
  <div class="coins-bar" id="coins-bar"></div>
</div>

<div class="section">
  <div class="section-title">Open Positions</div>
  <table id="open-table">
    <thead><tr><th>Coin</th><th>Entry</th><th>Current</th><th class="tip" data-tip="Profit/Loss as % and $ vs entry price">PnL%</th><th class="tip" data-tip="Take Profit — sells half your position at this price">TP</th><th class="tip" data-tip="Stop Loss — closes full position if price drops to here">SL</th><th class="tip" data-tip="Amount invested in this trade in USD">Size</th><th>Time</th></tr></thead>
    <tbody id="open-body"><tr><td colspan="8" class="empty">No open positions</td></tr></tbody>
  </table>
</div>

<div class="section">
  <div class="section-title">Trade History</div>
  <table id="closed-table">
    <thead><tr><th>Coin</th><th>Entry</th><th>Exit</th><th>PnL $</th><th>Reason</th><th>Opened</th><th>Closed</th></tr></thead>
    <tbody id="closed-body"><tr><td colspan="7" class="empty">No closed trades yet</td></tr></tbody>
  </table>
</div>

<div class="section">
  <div class="section-title">Live Log</div>
  <div class="logs" id="log-box"><div class="empty">Waiting for logs...</div></div>
</div>

<div class="section">
  <div class="section-title">Weekly Backtest</div>
  <div style="color:#a0aec0;font-size:.82rem;margin-bottom:14px;">Run once a week to check if the scanner is working and whether to adjust trade size. Takes 20-30 minutes. Leave the page open.</div>
  <button id="bt-btn" onclick="runBacktest()" style="background:#3182ce;color:#fff;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:.85rem;font-weight:600;">Run Backtest</button>
  <div id="bt-status" style="margin-top:14px;color:#a0aec0;font-size:.82rem;"></div>
  <div id="bt-results" style="margin-top:16px;display:none;">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
      <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:14px;">
        <div style="font-size:.72rem;color:#718096;text-transform:uppercase;margin-bottom:8px;">Original Coin List</div>
        <div id="bt-orig"></div>
      </div>
      <div style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:14px;">
        <div style="font-size:.72rem;color:#718096;text-transform:uppercase;margin-bottom:8px;">RS Scanner (Current)</div>
        <div id="bt-rs"></div>
      </div>
    </div>
    <div id="bt-verdict" style="background:#1a1f2e;border:1px solid #2d3748;border-radius:8px;padding:16px;"></div>
  </div>
</div>

<script>
let prices = {};

async function fetchPrices(symbols) {
  try {
    const res = await fetch('/prices?symbols=' + symbols.join(','));
    prices = await res.json();
  } catch(e) {}
}

function pnlClass(v) { return v >= 0 ? 'pnl-pos' : 'pnl-neg'; }
function pnlStr(v)   { return (v >= 0 ? '+' : '') + v.toFixed(2); }

function badgeReason(r) {
  if (!r) return '';
  if (r.startsWith('TP'))     return `<span class="badge badge-tp">${r}</span>`;
  if (r.startsWith('SL'))     return `<span class="badge badge-sl">${r}</span>`;
  if (r.startsWith('Trail'))  return `<span class="badge badge-trail">${r}</span>`;
  return `<span class="badge badge-open">${r}</span>`;
}

async function refresh() {
  try {
    const res  = await fetch('/state');
    const data = await res.json();

    // Status pill
    const pill = document.getElementById('status-pill');
    pill.textContent = data.running ? 'RUNNING' : 'STOPPED';
    pill.className   = 'status-pill ' + (data.running ? 'running' : 'stopped');

    // Metrics
    document.getElementById('m-balance').textContent = data.balance != null ? '$' + data.balance.toFixed(2) : '—';
    const openVal = Object.values(data.open_trades || {}).reduce((s,t) => s + (prices[t.symbol] || t.entry_price) / t.entry_price * t.usd_size, 0);
    document.getElementById('m-portfolio').textContent = '$' + ((data.balance || 0) + openVal).toFixed(2);
    document.getElementById('m-open').textContent    = Object.keys(data.open_trades || {}).length;
    document.getElementById('m-scans').textContent   = data.scan_count || 0;
    document.getElementById('m-closed').textContent  = (data.closed_trades || []).length;

    // Coins being traded
    const coinsBar = document.getElementById('coins-bar');
    if (coinsBar) {
      const symbols = data.symbols || [];
      coinsBar.innerHTML = symbols.map(s => `<span class="coin-tag">${s.replace('USDT','')}</span>`).join('');
    }

    const dp = data.daily_pnl || 0;
    const tp = data.total_pnl || 0;
    const dm = document.getElementById('m-daily');
    const tm = document.getElementById('m-total');
    dm.textContent = (dp >= 0 ? '+' : '') + dp.toFixed(2);
    dm.className   = 'card-value ' + pnlClass(dp);
    tm.textContent = (tp >= 0 ? '+' : '') + tp.toFixed(2);
    tm.className   = 'card-value ' + pnlClass(tp);

    // Open trades
    const trades = Object.values(data.open_trades || {});
    const openBody = document.getElementById('open-body');
    if (trades.length === 0) {
      openBody.innerHTML = '<tr><td colspan="8" class="empty">No open positions</td></tr>';
    } else {
      const syms = trades.map(t => t.symbol);
      await fetchPrices(syms);
      openBody.innerHTML = trades.map(t => {
        const cur    = prices[t.symbol] || t.entry_price;
        const pct    = ((cur - t.entry_price) / t.entry_price * 100);
        const pnlUsd = (cur - t.entry_price) / t.entry_price * t.usd_size;
        return `<tr>
          <td><b>${t.symbol.replace('USDT','')}</b></td>
          <td>${parseFloat(t.entry_price).toPrecision(5)}</td>
          <td>${parseFloat(cur).toPrecision(5)}</td>
          <td class="${pnlClass(pct)}">${pnlStr(pct)}%<br><small>${pnlStr(pnlUsd)}</small></td>
          <td class="green">${parseFloat(t.take_profit).toPrecision(5)}</td>
          <td class="red">${parseFloat(t.stop_loss).toPrecision(5)}</td>
          <td>$${t.usd_size}</td>
          <td>${t.open_time}</td>
        </tr>`;
      }).join('');
    }

    // Closed trades
    const closed     = (data.closed_trades || []).slice(0, 50);
    const closedBody = document.getElementById('closed-body');
    if (closed.length === 0) {
      closedBody.innerHTML = '<tr><td colspan="7" class="empty">No closed trades yet</td></tr>';
    } else {
      closedBody.innerHTML = closed.map(t => `<tr>
        <td><b>${t.symbol.replace('USDT','')}</b></td>
        <td>${parseFloat(t.entry_price).toPrecision(5)}</td>
        <td>${parseFloat(t.close_price).toPrecision(5)}</td>
        <td class="${pnlClass(t.pnl)}">${pnlStr(t.pnl)}</td>
        <td>${badgeReason(t.reason)}</td>
        <td>${t.open_time}</td>
        <td>${t.close_time}</td>
      </tr>`).join('');
    }

    // Logs
    const logs   = data.logs || [];
    const logBox = document.getElementById('log-box');
    if (logs.length === 0) {
      logBox.innerHTML = '<div class="empty">Waiting for logs...</div>';
    } else {
      logBox.innerHTML = logs.map(l =>
        `<div class="log-${l.level}"><span class="log-time">${l.time}</span>${l.msg}</div>`
      ).join('');
    }

  } catch(e) {
    console.error('Refresh error', e);
  }
}

async function action(cmd) {
  await fetch('/action?cmd=' + cmd, {method:'POST'});
  setTimeout(refresh, 800);
}

refresh();
setInterval(refresh, 5000);

let btPolling = null;
async function runBacktest() {
  document.getElementById('bt-btn').disabled = true;
  document.getElementById('bt-btn').textContent = 'Running...';
  document.getElementById('bt-status').textContent = 'Starting backtest... this takes 20-30 minutes. You can leave this page open.';
  document.getElementById('bt-results').style.display = 'none';
  try {
    await fetch('/backtest/run', {method:'POST'});
    btPolling = setInterval(pollBacktest, 5000);
  } catch(e) {
    document.getElementById('bt-status').textContent = 'Failed to start.';
    document.getElementById('bt-btn').disabled = false;
    document.getElementById('bt-btn').textContent = 'Run Backtest';
  }
}
async function pollBacktest() {
  try {
    const res = await fetch('/backtest/status');
    const d = await res.json();
    document.getElementById('bt-status').textContent = d.status || '';
    if (d.done && d.results) {
      clearInterval(btPolling);
      document.getElementById('bt-btn').disabled = false;
      document.getElementById('bt-btn').textContent = 'Run Backtest Again';
      showBacktestResults(d.results);
    }
  } catch(e) {}
}
function btStat(label, value) {
  return '<div style="display:flex;justify-content:space-between;margin-bottom:6px;font-size:.82rem;"><span style="color:#a0aec0;">' + label + '</span><span style="color:#e2e8f0;font-weight:600;">' + value + '</span></div>';
}
function showBacktestResults(r) {
  document.getElementById('bt-results').style.display = 'block';
  const orig = r.orig; const rs = r.rs;
  document.getElementById('bt-orig').innerHTML =
    btStat('Trades', orig.trades) + btStat('Win Rate', orig.win_rate + '%') +
    btStat('Total PnL', '$' + (orig.total_pnl >= 0 ? '+' : '') + orig.total_pnl.toFixed(2)) +
    btStat('Avg/Trade', '$' + (orig.avg_pnl >= 0 ? '+' : '') + orig.avg_pnl.toFixed(3)) +
    btStat('Max Drawdown', '$' + orig.max_drawdown.toFixed(2));
  document.getElementById('bt-rs').innerHTML =
    btStat('Trades', rs.trades) + btStat('Win Rate', rs.win_rate + '%') +
    btStat('Total PnL', '$' + (rs.total_pnl >= 0 ? '+' : '') + rs.total_pnl.toFixed(2)) +
    btStat('Avg/Trade', '$' + (rs.avg_pnl >= 0 ? '+' : '') + rs.avg_pnl.toFixed(3)) +
    btStat('Max Drawdown', '$' + rs.max_drawdown.toFixed(2));
  const v = r.verdict;
  let color = v.points >= 3 ? '#68d391' : v.points >= 1 ? '#f6e05e' : '#fc8181';
  let html = '<div style="font-size:.9rem;font-weight:700;color:' + color + ';margin-bottom:12px;">' + v.conclusion + '</div>';
  html += '<div style="font-size:.85rem;color:#e2e8f0;font-weight:600;margin-bottom:6px;">What you should do:</div>';
  html += '<div style="font-size:.84rem;color:#cbd5e0;line-height:1.7;margin-bottom:12px;">' + v.action + '</div>';
  html += '<div style="border-top:1px solid #2d3748;padding-top:10px;">';
  v.reasons.forEach(function(reason) { html += '<div style="font-size:.78rem;color:#718096;margin-bottom:3px;">' + reason + '</div>'; });
  html += '</div><div style="margin-top:8px;font-size:.72rem;color:#4a5568;">Last run: ' + new Date().toLocaleString() + '</div>';
  document.getElementById('bt-verdict').innerHTML = html;
}
</script>
</body>
</html>"""

import threading as _threading
_bt_state = {"running": False, "done": False, "status": "", "results": None}

def run_backtest_thread():
    global _bt_state
    _bt_state = {"running": True, "done": False, "status": "Starting...", "results": None}
    try:
        import time as _t, requests as _rq
        from collections import defaultdict
        from datetime import datetime, timezone
        def pub(path, params=None):
            try:
                r=_rq.get("https://api.binance.com"+path,params=params,timeout=15); r.raise_for_status(); return r.json()
            except: return None
        DAYS=30;TRADE=15;TP=0.025;SL=0.02;TR=0.015;MS=55;RSC=8;REPL=0.30;MAX=8
        ORIG=["SOLUSDT","PEPEUSDT","DOGEUSDT","SHIBUSDT","FLOKIUSDT","BONKUSDT","WIFUSDT","MEMEUSDT","AVAXUSDT","APTUSDT","SUIUSDT","SEIUSDT","ARBUSDT","OPUSDT","FETUSDT","RENDERUSDT","WLDUSDT","1000SATSUSDT","ORDIUSDT","STXUSDT","TIAUSDT","JUPUSDT","EIGENUSDT","PYTHUSDT"]
        EXCL={"USDCUSDT","BUSDUSDT","TUSDUSDT","USDTUSDT","DAIUSDT","FDUSDUSDT","EURUSDT","GBPUSDT","BTCUSDT","ETHUSDT","WBTCUSDT","STETHUSDT","WETHUSDT","BETHUSDT","LDOETH","USD1USDT","UUSDT","LUNCUSDT","BANANAS31USDT","RLUSDUSDT","XAUTUSDT","PAXGUSDT","ZECUSDT","XUSDUSDT"}
        now=int(_t.time()*1000); start=now-DAYS*24*60*60*1000
        _bt_state["status"]="Fetching eligible symbols..."
        tickers=pub("/api/v3/ticker/24hr"); eligible=[]
        if tickers:
            for t in tickers:
                s=t["symbol"]
                if not s.endswith("USDT") or s in EXCL or not s.isascii(): continue
                try:
                    if float(t["quoteVolume"])>=5_000_000: eligible.append(s)
                except: continue
        all_syms=list(set(eligible+ORIG+["BTCUSDT"]))
        def get_candles(sym):
            candles=[]; cur=start
            while cur<now:
                d=pub("/api/v3/klines",params={"symbol":sym,"interval":"15m","startTime":cur,"endTime":now,"limit":1000})
                if not d: break
                candles.extend(d)
                if len(d)<1000: break
                cur=d[-1][0]+1; _t.sleep(0.05)
            return {c[0]:{"open":float(c[1]),"high":float(c[2]),"low":float(c[3]),"close":float(c[4]),"qv":float(c[7])} for c in candles}
        cd={}
        for i,sym in enumerate(all_syms):
            cd[sym]=get_candles(sym); _bt_state["status"]=f"Fetching data... {i+1}/{len(all_syms)} coins"; _t.sleep(0.1)
        if "BTCUSDT" not in cd: _bt_state["status"]="ERROR: No BTC data"; _bt_state["running"]=False; return
        ts=sorted(cd["BTCUSDT"].keys())
        def sc(op,cl,vol,t):
            if op==0: return 0
            ch=(cl-op)/op*100; vm=vol/1e6
            dt=datetime.fromtimestamp(t/1000,tz=timezone.utc); pk=9<=dt.hour<23
            s=0
            if ch>1: s+=20
            if ch>2: s+=15
            if ch>3: s+=10
            if ch>5: s+=10
            if vm>10: s+=10
            if vm>50: s+=10
            if vm>100: s+=5
            if pk: s+=10
            if ch<0: s-=30
            return s
        def simulate(sel):
            trades=[]; ot={}; tid=0
            for i,t in enumerate(ts):
                for sym in list(ot.keys()):
                    tr=ot[sym]
                    if sym not in cd or t not in cd[sym]: continue
                    c=cd[sym][t]; pr=c["close"]; hi=c["high"]; lo=c["low"]
                    if hi>tr["hi"]: tr["hi"]=hi; tr["tr"]=tr["hi"]*(1-TR)
                    if hi>=tr["tp"]: trades.append({"pnl":round((tr["tp"]-tr["en"])/tr["en"]*TRADE,3),"reason":"TP"}); del ot[sym]; continue
                    if lo<=tr["tr"] and tr["tr"]>tr["sl"]: trades.append({"pnl":round((tr["tr"]-tr["en"])/tr["en"]*TRADE,3),"reason":"TrailSL"}); del ot[sym]; continue
                    if lo<=tr["sl"]: trades.append({"pnl":round((tr["sl"]-tr["en"])/tr["en"]*TRADE,3),"reason":"SL"}); del ot[sym]; continue
                    if i-tr["oi"]>=24: trades.append({"pnl":round((pr-tr["en"])/tr["en"]*TRADE,3),"reason":"Time"}); del ot[sym]
                if len(ot)>=MAX: continue
                watch=sel(i); cands=[]
                for sym in watch:
                    if sym in ot or sym not in cd or t not in cd[sym]: continue
                    c=cd[sym][t]; s=sc(c["open"],c["close"],c["qv"],t)
                    if s>=MS: cands.append((sym,s,c["close"]))
                cands.sort(key=lambda x:x[1],reverse=True)
                for sym,s,pr in cands[:3]:
                    if len(ot)>=MAX: break
                    tid+=1; ot[sym]={"en":pr,"tp":pr*(1+TP),"sl":pr*(1-SL),"tr":pr*(1-TR),"hi":pr,"oi":i}
            last=ts[-1]
            for sym,tr in ot.items():
                if sym in cd and last in cd[sym]:
                    pr=cd[sym][last]["close"]; trades.append({"pnl":round((pr-tr["en"])/tr["en"]*TRADE,3),"reason":"Open"})
            return trades
        def calc_rs(sym,idx):
            if idx<RSC: return None
            sc2=cd.get(sym,{}); bc=cd.get("BTCUSDT",{})
            st=ts[idx-RSC]; et=ts[idx]
            if st not in sc2 or et not in sc2 or st not in bc or et not in bc: return None
            so=sc2[st]["open"]; se=sc2[et]["close"]; bo=bc[st]["open"]; be=bc[et]["close"]
            if so==0 or bo==0: return None
            return (se-so)/so*100-(be-bo)/bo*100
        cur_list=list(ORIG); rs_cache={}
        def rs_sel(idx):
            nonlocal cur_list
            b=idx//60
            if b not in rs_cache:
                scores={sym:calc_rs(sym,idx) for sym in eligible}
                scores={k:v for k,v in scores.items() if v is not None}
                if scores:
                    ranked=sorted(scores,key=lambda s:scores[s],reverse=True)
                    n=len(cur_list); nk=max(1,round(n*(1-REPL)))
                    cr=sorted(cur_list,key=lambda s:scores.get(s,-999),reverse=True)
                    keep=cr[:nk]; ne=[s for s in ranked if s not in set(keep)][:(n-len(keep))]
                    cur_list=list(dict.fromkeys(keep+ne))
                rs_cache[b]=cur_list[:]
            return rs_cache[b]
        _bt_state["status"]="Running simulation 1: Original list..."
        orig_t=simulate(lambda i:ORIG)
        _bt_state["status"]="Running simulation 2: RS Scanner..."
        rs_t=simulate(rs_sel)
        def analyse(trades):
            if not trades: return {"trades":0,"win_rate":0,"total_pnl":0,"avg_pnl":0,"max_drawdown":0}
            pnls=[t["pnl"] for t in trades]; wins=[p for p in pnls if p>0]
            run=pk=mdd=0
            for p in pnls:
                run+=p
                if run>pk: pk=run
                if pk-run>mdd: mdd=pk-run
            return {"trades":len(trades),"win_rate":round(len(wins)/len(pnls)*100,1),"total_pnl":round(sum(pnls),2),"avg_pnl":round(sum(pnls)/len(pnls),3),"max_drawdown":round(mdd,2)}
        os=analyse(orig_t); rs=analyse(rs_t)
        pd=rs["total_pnl"]-os["total_pnl"]; wd=rs["win_rate"]-os["win_rate"]; dd=os["max_drawdown"]-rs["max_drawdown"]
        pts=0; reasons=[]
        if rs["total_pnl"]>os["total_pnl"]: pts+=1; reasons.append(f"RS Scanner made ${pd:+.2f} more profit")
        else: pts-=1; reasons.append(f"RS Scanner made ${abs(pd):.2f} less profit")
        if wd>2: pts+=1; reasons.append(f"Win rate improved by {wd:.1f}%")
        elif wd<-2: pts-=1; reasons.append(f"Win rate dropped by {abs(wd):.1f}%")
        else: reasons.append(f"Win rate similar ({wd:+.1f}%)")
        if dd>0: pts+=1; reasons.append(f"Lower max drawdown by ${dd:.2f}")
        else: reasons.append(f"Higher max drawdown by ${abs(dd):.2f}")
        if rs["trades"]>=30: pts+=1; reasons.append(f"Enough trades to be reliable ({rs['trades']})")
        else: reasons.append(f"Low trade count ({rs['trades']}) - not enough data yet")
        if pts>=3: conc="🟢 The scanner is working well"; act="Everything looks good. Keep running as-is. If your trade size is below $20, raise it to $20. Run again next week."
        elif pts>=1: conc="🟡 Scanner is slightly better but not conclusive"; act="Keep your current trade size for now. Run the backtest again in 2 weeks."
        else: conc="🔴 The scanner is not outperforming"; act="Do not raise your trade size. Contact your assistant — do not change anything yourself."
        _bt_state["results"]={"orig":os,"rs":rs,"verdict":{"points":pts,"reasons":reasons,"conclusion":conc,"action":act}}
        _bt_state["status"]="Backtest complete."; _bt_state["done"]=True; _bt_state["running"]=False
    except Exception as e:
        _bt_state["status"]=f"Error: {e}"; _bt_state["running"]=False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # suppress access logs

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/dashboard":
            self.send_html(HTML)

        elif path == "/state":
            balance = get_balance()
            try:
                with open("state.json") as f:
                    fresh = json.load(f)
            except:
                fresh = state
            payload = {**fresh, "balance": balance}
            self.send_json(payload)

        elif path == "/prices":
            from urllib.parse import parse_qs, urlparse
            qs      = parse_qs(urlparse(self.path).query)
            symbols = qs.get("symbols", [""])[0].split(",")
            result  = {}
            for sym in symbols:
                if sym:
                    try:
                        import requests as req
                        r = req.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", timeout=5)
                        result[sym] = float(r.json()["price"])
                    except:
                        pass
            self.send_json(result)

        elif path == "/backtest/status":
            self.send_json({"running":_bt_state["running"],"done":_bt_state["done"],"status":_bt_state["status"],"results":_bt_state["results"]})
        elif path == "/backtest/run":
            if not _bt_state["running"]:
                _threading.Thread(target=run_backtest_thread,daemon=True).start()
            self.send_json({"ok":True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        from urllib.parse import parse_qs, urlparse
        path = self.path.split("?")[0]

        if path == "/action":
            qs  = parse_qs(urlparse(self.path).query)
            cmd = qs.get("cmd", [""])[0]
            if cmd == "start":
                start()
            elif cmd == "stop":
                stop()
            elif cmd == "restart":
                stop()
                threading.Timer(2.0, start).start()
            self.send_json({"ok": True})
        elif path == "/backtest/status":
            self.send_json({"running":_bt_state["running"],"done":_bt_state["done"],"status":_bt_state["status"],"results":_bt_state["results"]})
        elif path == "/backtest/run":
            if not _bt_state["running"]:
                _threading.Thread(target=run_backtest_thread,daemon=True).start()
            self.send_json({"ok":True})
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    from bot import load, start
    load()
    start()
    print("Auto-started bot")
    print("ApexBot V3 dashboard → http://0.0.0.0:8080")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
