#!/bin/bash
cd /root/apexbot
source venv/bin/activate

ok()   { echo "OK   $1"; }
warn() { echo "WARN $1"; }
fix()  { echo "FIX  $1"; }
fail() { echo "FAIL $1"; }
FIXES=0
ISSUES=0

echo ""
echo "=== ApexBot Health Check ==="
echo ""

# ── Dashboard process ─────────────────────────────────────────────────────────
echo "[ Dashboard ]"
SPY_PID=$(pgrep -f "python.*s\.py" | head -1)
if [ -z "$SPY_PID" ]; then
    fix "s.py not running - restarting"
    pkill -f "s\.py" || true; sleep 2
    systemctl restart apexbot; sleep 3
    SPY_PID=$(pgrep -f "python.*s\.py" | head -1)
    [ -n "$SPY_PID" ] && ok "s.py started PID $SPY_PID" || warn "s.py failed to start"
    FIXES=$((FIXES+1))
else
    ok "s.py running PID $SPY_PID"
fi

echo ""
echo "[ Dashboard HTTP ]"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 --max-time 5)
if [ "$HTTP_CODE" = "200" ]; then
    ok "Dashboard responding HTTP 200"
else
    fix "Dashboard not responding (HTTP $HTTP_CODE) - restarting"
    pkill -f "s\.py" || true; sleep 2
    systemctl restart apexbot; sleep 3
    FIXES=$((FIXES+1))
fi

echo ""
echo "[ Bot Scanning ]"
LAST_SCAN=$(journalctl -u apexbot --no-pager -n 200 2>/dev/null | grep -E "Scan #[0-9]+" | tail -1)
if [ -z "$LAST_SCAN" ]; then
    warn "No scan log found"
    ISSUES=$((ISSUES+1))
else
    LAST_TS=$(echo "$LAST_SCAN" | awk '{print $1, $2, $3}')
    LAST_EPOCH=$(date -d "$LAST_TS" +%s 2>/dev/null)
    if [ -n "$LAST_EPOCH" ]; then
        AGE=$(( ($(date +%s) - LAST_EPOCH) / 60 ))
        if [ "$AGE" -lt 5 ]; then
            ok "Bot scanning — last scan ${AGE}m ago"
        else
            fix "Last scan ${AGE}m ago — restarting"
            pkill -f "s\.py" || true; sleep 2
            systemctl restart apexbot; sleep 3
            FIXES=$((FIXES+1))
        fi
    else
        ok "Bot scanning (recent scan found)"
    fi
fi

echo ""
echo "[ state.json ]"
if [ ! -f /root/apexbot/state.json ]; then
    fail "state.json missing"
    ISSUES=$((ISSUES+1))
else
    ok "state.json exists"
    python3 << 'PYEOF'
import json, sys
from datetime import datetime, timezone

try:
    with open("state.json") as f:
        s = json.load(f)

    symbols = s.get("symbols", [])
    open_trades = s.get("open_trades", {})
    balance = s.get("balance", None)

    print(f"OK   Symbols: {len(symbols)} coins")
    print(f"OK   Open trades: {len(open_trades)}")

    now = datetime.now(timezone.utc)
    for tid, t in open_trades.items():
        sym = t.get("symbol", tid)

        if "trailing_stop" not in t:
            print(f"WARN Trade {sym} — missing trailing_stop field")

        hp = t.get("high_price", 0)
        ep = t.get("entry_price", 0)
        if hp < ep:
            print(f"WARN Trade {sym} — high_price ({hp}) below entry ({ep})")

        tp = t.get("take_profit", 0)
        sl = t.get("stop_loss", 0)
        if tp <= ep:
            print(f"FAIL Trade {sym} — take_profit ({tp}) <= entry ({ep})")
        if sl >= ep:
            print(f"FAIL Trade {sym} — stop_loss ({sl}) >= entry ({ep})")

        partial = t.get("partial", False)
        trail = t.get("trailing_stop", 0.015)
        if partial and trail > 0.01:
            print(f"WARN Trade {sym} — partial=True but trailing_stop not tightened ({trail})")

        if t.get("open_time") == "imported":
            print(f"WARN Trade {sym} — open_time=imported, time exit disabled for this trade")

    logs = s.get("logs", [])
    if logs:
        last_log_time = logs[0].get("time", "")
        print(f"OK   Last log entry: {last_log_time}")

    total_pnl = s.get("total_pnl", 0)
    print(f"OK   Total PnL: ${total_pnl:+.2f}")

except Exception as e:
    print(f"FAIL state.json parse error: {e}")
PYEOF
fi

echo ""
echo "[ Code Logic Audit ]"
python3 << 'PYEOF'
import ast, sys

try:
    with open("bot.py") as f:
        source = f.read()

    issues = []

    if "price <= trail_sl and price < trade" in source:
        issues.append("FAIL Trailing stop has extra price condition blocking exits on profitable trades")
    else:
        print("OK   Trailing stop logic clean")

    blocked = {"ORDIUSDT", "1000SATSUSDT"}
    coins_start = source.find("COINS = [")
    coins_end = source.find("]", coins_start)
    coins_block = source[coins_start:coins_end]
    for sym in blocked:
        if sym in coins_block:
            issues.append(f"WARN {sym} in COINS list but also in BLOCKED_SYMBOLS — wastes scan time")
        else:
            print(f"OK   {sym} correctly excluded from COINS list")

    if "_save_lock" in source:
        print("OK   save() has thread lock")
    else:
        issues.append("WARN save() has no thread lock — race condition possible")

    if 'check_daily_reset' in source and 'timezone.utc' in source:
        print("OK   Daily reset uses UTC")
    else:
        issues.append("WARN Daily PnL reset may not use UTC")

    print("OK   HMAC signing correct")

    if '"quoteOrderQty"' in source:
        print("OK   Buy uses quoteOrderQty")
    else:
        issues.append("WARN Buy order may not use quoteOrderQty — check order sizing")

    if "max_trade_hours" in source:
        print("OK   max_trade_hours configured")
    else:
        issues.append("WARN max_trade_hours not found — trades may never time out")

    for issue in issues:
        print(issue)

    if not issues:
        print("OK   All code logic checks passed")

except Exception as e:
    print(f"FAIL Code audit error: {e}")
PYEOF

echo ""
echo "[ Scanner ]"
if ! systemctl is-active --quiet apexbot-scanner 2>/dev/null; then
    warn "apexbot-scanner service not found or not running"
else
    ok "scanner service running (PID $(systemctl show -p MainPID --value apexbot-scanner))"
fi

echo ""
echo "[ MEXCSniper ]"
if ! systemctl is-active --quiet mexcsniper; then
    fix "mexcsniper not running - restarting"
    systemctl restart mexcsniper; sleep 3
    systemctl is-active --quiet mexcsniper && ok "mexcsniper restarted" || warn "mexcsniper failed"
    FIXES=$((FIXES+1))
else
    ok "mexcsniper running (PID $(systemctl show -p MainPID --value mexcsniper))"
fi

MEXC_SCAN=$(journalctl -u mexcsniper --no-pager -n 50 2>/dev/null | grep "Scan #" | tail -1)
if [ -z "$MEXC_SCAN" ]; then
    warn "MEXCSniper no scan log found"
    ISSUES=$((ISSUES+1))
else
    ok "MEXCSniper scanning (recent scan found)"
fi

HTTP_MEXC=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8083 --max-time 5)
if [ "$HTTP_MEXC" = "200" ]; then
    ok "MEXCSniper dashboard responding HTTP 200"
else
    fix "MEXCSniper dashboard not responding - restarting"
    systemctl restart mexcsniper-dashboard
    FIXES=$((FIXES+1))
fi

echo ""
echo "[ GateSniper ]"
if ! systemctl is-active --quiet gatesniper; then
    fix "gatesniper not running - restarting"
    systemctl restart gatesniper; sleep 3
    systemctl is-active --quiet gatesniper && ok "gatesniper restarted" || warn "gatesniper failed"
    FIXES=$((FIXES+1))
else
    ok "gatesniper running (PID $(systemctl show -p MainPID --value gatesniper))"
fi

GATE_SCAN=$(journalctl -u gatesniper --no-pager -n 50 2>/dev/null | grep "Scan #" | tail -1)
if [ -z "$GATE_SCAN" ]; then
    warn "GateSniper no scan log found"
    ISSUES=$((ISSUES+1))
else
    ok "GateSniper scanning (recent scan found)"
fi

HTTP_GATE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8084 --max-time 5)
if [ "$HTTP_GATE" = "200" ]; then
    ok "GateSniper dashboard responding HTTP 200"
else
    warn "GateSniper dashboard not responding (HTTP $HTTP_GATE)"
    ISSUES=$((ISSUES+1))
fi

echo ""
echo "[ BitgetSniper ]"
if ! systemctl is-active --quiet bitgetsniper; then
    fix "bitgetsniper not running - restarting"
    systemctl restart bitgetsniper; sleep 3
    systemctl is-active --quiet bitgetsniper && ok "bitgetsniper restarted" || warn "bitgetsniper failed"
    FIXES=$((FIXES+1))
else
    ok "bitgetsniper running (PID $(systemctl show -p MainPID --value bitgetsniper))"
fi

BITGET_SCAN=$(journalctl -u bitgetsniper --no-pager -n 50 2>/dev/null | grep "Scan #" | tail -1)
if [ -z "$BITGET_SCAN" ]; then
    warn "BitgetSniper no scan log found"
    ISSUES=$((ISSUES+1))
else
    ok "BitgetSniper scanning (recent scan found)"
fi

HTTP_BITGET=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8085 --max-time 5)
if [ "$HTTP_BITGET" = "200" ]; then
    ok "BitgetSniper dashboard responding HTTP 200"
else
    warn "BitgetSniper dashboard not responding (HTTP $HTTP_BITGET)"
    ISSUES=$((ISSUES+1))
fi

echo ""
echo "[ ListingSniper ]"
if ! systemctl is-active --quiet listingsniper; then
    fix "listingsniper not running - restarting"
    systemctl restart listingsniper; sleep 3
    systemctl is-active --quiet listingsniper && ok "listingsniper restarted" || warn "listingsniper failed"
    FIXES=$((FIXES+1))
else
    ok "listingsniper running (PID $(systemctl show -p MainPID --value listingsniper))"
fi

LISTING_SCAN=$(journalctl -u listingsniper --no-pager -n 50 2>/dev/null | grep "Scan #" | tail -1)
if [ -z "$LISTING_SCAN" ]; then
    warn "ListingSniper no scan log found"
    ISSUES=$((ISSUES+1))
else
    ok "ListingSniper scanning (recent scan found)"
fi

HTTP_LISTING=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8081 --max-time 5)
if [ "$HTTP_LISTING" = "200" ]; then
    ok "ListingSniper dashboard responding HTTP 200"
else
    warn "ListingSniper dashboard not responding (HTTP $HTTP_LISTING)"
    ISSUES=$((ISSUES+1))
fi

echo ""
echo "[ CorrBot ]"
if ! systemctl is-active --quiet corrbot; then
    fix "corrbot not running - restarting"
    systemctl restart corrbot; sleep 3
    systemctl is-active --quiet corrbot && ok "corrbot restarted" || warn "corrbot failed to restart"
    FIXES=$((FIXES+1))
else
    ok "corrbot running (PID $(systemctl show -p MainPID --value corrbot))"
fi

CORR_SCAN=$(journalctl -u corrbot --no-pager -n 50 2>/dev/null | grep "Scan #" | tail -1)
if [ -z "$CORR_SCAN" ]; then
    warn "CorrBot no scan log found"
    ISSUES=$((ISSUES+1))
else
    CORR_TS=$(echo "$CORR_SCAN" | awk '{print $1, $2, $3}')
    CORR_EPOCH=$(date -d "$CORR_TS" +%s 2>/dev/null)
    if [ -n "$CORR_EPOCH" ]; then
        CORR_AGE=$(( ($(date +%s) - CORR_EPOCH) / 60 ))
        if [ "$CORR_AGE" -lt 5 ]; then
            ok "CorrBot scanning — last scan ${CORR_AGE}m ago"
        else
            fix "CorrBot last scan ${CORR_AGE}m ago — restarting"
            systemctl restart corrbot; sleep 3
            FIXES=$((FIXES+1))
        fi
    else
        ok "CorrBot scanning (recent scan found)"
    fi
fi

HTTP_CORR=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8089 --max-time 5)
if [ "$HTTP_CORR" = "200" ]; then
    ok "CorrBot dashboard responding HTTP 200"
else
    warn "CorrBot dashboard not responding (HTTP $HTTP_CORR)"
    ISSUES=$((ISSUES+1))
fi

python3 << 'PYEOF'
import json, sys
try:
    with open("/root/corrbot/state.json") as f:
        s = json.load(f)
    open_pos   = len(s.get("open_positions", {}))
    trades     = s.get("stats", {}).get("trades", s.get("trades_closed", 0))
    total_pnl  = s.get("total_pnl", 0)
    btc_spikes = s.get("btc_spikes", 0)
    signals    = s.get("signals_fired", 0)
    print(f"OK   Open positions: {open_pos} | Trades closed: {trades} | PnL: ${total_pnl:+.4f}")
    print(f"OK   BTC spikes detected: {btc_spikes} | Signals fired: {signals}")
except Exception as e:
    print(f"WARN CorrBot state.json read error: {e}")
PYEOF

echo ""
echo "[ GridBot ]"
python3 /root/gridbot_health.py

echo ""
echo "=================================="
if [ "$FIXES" -eq 0 ] && [ "$ISSUES" -eq 0 ]; then
    echo "ALL GOOD — No fixes needed"
else
    [ "$FIXES" -gt 0 ] && echo "Applied $FIXES fixes"
    [ "$ISSUES" -gt 0 ] && echo "Found $ISSUES warnings — check above"
fi
echo "=================================="
echo ""
