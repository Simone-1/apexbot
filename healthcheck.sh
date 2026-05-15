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
echo "=== Bot Health Check ==="
echo ""

# ── ApexBot Dashboard ─────────────────────────────────────────────────────────
echo "[ ApexBot Dashboard ]"
SPY_PID=$(pgrep -f "python.*s\.py" | head -1)
if [ -z "$SPY_PID" ]; then
    warn "s.py not running — start manually if needed"
    ISSUES=$((ISSUES+1))
else
    ok "s.py running PID $SPY_PID"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080 --max-time 5)
    if [ "$HTTP_CODE" = "200" ]; then
        ok "Dashboard responding HTTP 200"
    else
        warn "Dashboard not responding (HTTP $HTTP_CODE)"
        ISSUES=$((ISSUES+1))
    fi
fi

echo ""
echo "[ ApexBot state.json ]"
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

    print(f"OK   Symbols: {len(symbols)} coins")
    print(f"OK   Open trades: {len(open_trades)}")
    print(f"OK   Running: {s.get('running', False)}")

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
        if t.get("open_time") == "imported":
            print(f"WARN Trade {sym} — open_time=imported, time exit disabled")

    total_pnl = s.get("total_pnl", 0)
    print(f"OK   Total PnL: ${total_pnl:+.2f}")

except Exception as e:
    print(f"FAIL state.json parse error: {e}")
PYEOF
fi

echo ""
echo "[ MEXCSniper ]"
MEXC_PID=$(pgrep -f "mexcsniper.py" | head -1)
if [ -z "$MEXC_PID" ]; then
    warn "mexcsniper not running"
    ISSUES=$((ISSUES+1))
else
    ok "mexcsniper running (PID $MEXC_PID)"
fi
HTTP_MEXC=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8083 --max-time 5)
[ "$HTTP_MEXC" = "200" ] && ok "MEXCSniper dashboard HTTP 200" || { warn "MEXCSniper dashboard not responding (HTTP $HTTP_MEXC)"; ISSUES=$((ISSUES+1)); }

echo ""
echo "[ GateSniper ]"
GATE_PID=$(pgrep -f "gatesniper.py" | head -1)
if [ -z "$GATE_PID" ]; then
    warn "gatesniper not running"
    ISSUES=$((ISSUES+1))
else
    ok "gatesniper running (PID $GATE_PID)"
fi
HTTP_GATE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8084 --max-time 5)
[ "$HTTP_GATE" = "200" ] && ok "GateSniper dashboard HTTP 200" || warn "GateSniper dashboard not responding (HTTP $HTTP_GATE)"

echo ""
echo "[ BitgetSniper ]"
BITGET_PID=$(pgrep -f "bitgetsniper.py" | head -1)
if [ -z "$BITGET_PID" ]; then
    warn "bitgetsniper not running"
    ISSUES=$((ISSUES+1))
else
    ok "bitgetsniper running (PID $BITGET_PID)"
fi
HTTP_BITGET=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8090 --max-time 5)
[ "$HTTP_BITGET" = "200" ] && ok "BitgetSniper dashboard HTTP 200" || { warn "BitgetSniper dashboard not responding (HTTP $HTTP_BITGET)"; ISSUES=$((ISSUES+1)); }

echo ""
echo "[ ListingSniper ]"
LISTING_PID=$(pgrep -f "sniper.py" | head -1)
if [ -z "$LISTING_PID" ]; then
    warn "listingsniper not running"
    ISSUES=$((ISSUES+1))
else
    ok "listingsniper running (PID $LISTING_PID)"
fi
HTTP_LISTING=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8082 --max-time 5)
[ "$HTTP_LISTING" = "200" ] && ok "ListingSniper dashboard HTTP 200" || { warn "ListingSniper dashboard not responding (HTTP $HTTP_LISTING)"; ISSUES=$((ISSUES+1)); }

echo ""
echo "[ ScalpBot ]"
SCALP_PID=$(pgrep -f "scalpbot.py" | head -1)
if [ -z "$SCALP_PID" ]; then
    warn "scalpbot not running"
    ISSUES=$((ISSUES+1))
else
    ok "scalpbot running (PID $SCALP_PID)"
fi
HTTP_SCALP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8087 --max-time 5)
[ "$HTTP_SCALP" = "200" ] && ok "ScalpBot dashboard HTTP 200" || { warn "ScalpBot dashboard not responding (HTTP $HTTP_SCALP)"; ISSUES=$((ISSUES+1)); }

echo ""
echo "[ MeanBot ]"
MEAN_PID=$(pgrep -f "meanbot.py" | head -1)
if [ -z "$MEAN_PID" ]; then
    warn "meanbot not running"
    ISSUES=$((ISSUES+1))
else
    ok "meanbot running (PID $MEAN_PID)"
fi
HTTP_MEAN=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8088 --max-time 5)
[ "$HTTP_MEAN" = "200" ] && ok "MeanBot dashboard HTTP 200" || { warn "MeanBot dashboard not responding (HTTP $HTTP_MEAN)"; ISSUES=$((ISSUES+1)); }

echo ""
echo "[ CorrBot ]"
CORR_PID=$(pgrep -f "corrbot.py" | head -1)
if [ -z "$CORR_PID" ]; then
    warn "corrbot not running"
    ISSUES=$((ISSUES+1))
else
    ok "corrbot running (PID $CORR_PID)"
    CORR_SCAN=$(journalctl -u corrbot --no-pager -n 50 2>/dev/null | grep "Scan #" | tail -1)
    if [ -z "$CORR_SCAN" ]; then
        warn "CorrBot no scan log found"
        ISSUES=$((ISSUES+1))
    else
        CORR_TS=$(echo "$CORR_SCAN" | awk '{print $1, $2, $3}')
        CORR_EPOCH=$(date -d "$CORR_TS" +%s 2>/dev/null)
        if [ -n "$CORR_EPOCH" ]; then
            CORR_AGE=$(( ($(date +%s) - CORR_EPOCH) / 60 ))
            [ "$CORR_AGE" -lt 5 ] && ok "CorrBot scanning — last scan ${CORR_AGE}m ago" || warn "CorrBot last scan ${CORR_AGE}m ago — may be stalled"
        else
            ok "CorrBot scanning (recent scan found)"
        fi
    fi
    HTTP_CORR=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8089 --max-time 5)
    [ "$HTTP_CORR" = "200" ] && ok "CorrBot dashboard HTTP 200" || warn "CorrBot dashboard not responding (HTTP $HTTP_CORR)"
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
    echo "ALL GOOD — No issues found"
else
    [ "$FIXES" -gt 0 ] && echo "Applied $FIXES fixes"
    [ "$ISSUES" -gt 0 ] && echo "Found $ISSUES warnings — check above"
fi
echo "=================================="
echo ""
