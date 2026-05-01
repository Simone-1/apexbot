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
  <div class="coins-bar">
    <span class="coin-tag">BTC</span><span class="coin-tag">SOL</span><span class="coin-tag">PEPE</span>
    <span class="coin-tag">DOGE</span><span class="coin-tag">SHIB</span><span class="coin-tag">FLOKI</span>
    <span class="coin-tag">BONK</span><span class="coin-tag">WIF</span><span class="coin-tag">MEME</span>
    <span class="coin-tag">AVAX</span><span class="coin-tag">APT</span><span class="coin-tag">SUI</span>
    <span class="coin-tag">SEI</span><span class="coin-tag">ARB</span><span class="coin-tag">OP</span>
    <span class="coin-tag">FETU</span><span class="coin-tag">RENDER</span><span class="coin-tag">WLD</span>
    <span class="coin-tag">1000SATS</span>
  </div>
</div>

<div class="section">
  <div class="section-title">Open Positions</div>
  <table id="open-table">
    <thead><tr><th>Coin</th><th>Entry</th><th>Current</th><th>PnL%</th><th>TP</th><th>SL</th><th>Size</th><th>Time</th></tr></thead>
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
    document.getElementById('m-open').textContent    = Object.keys(data.open_trades || {}).length;
    document.getElementById('m-scans').textContent   = data.scan_count || 0;
    document.getElementById('m-closed').textContent  = (data.closed_trades || []).length;

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
</script>
</body>
</html>"""

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
            payload = {**state, "balance": balance}
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
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    from bot import load
    load()
    print("ApexBot V3 dashboard → http://0.0.0.0:8080")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
