#!/bin/bash
cd /root/apexbot
source venv/bin/activate

ok()  { echo "OK  $1"; }
warn(){ echo "WARN $1"; }
fix() { echo "FIX $1"; }
FIXES=0

echo ""
echo "=== ApexBot Health Check ==="
echo ""

echo "[ Dashboard ]"
SPY_PID=$(pgrep -f "python.*s.py" | head -1)
if [ -z "$SPY_PID" ]; then
    fix "s.py not running - starting"
    nohup python s.py >> /root/apexbot/nohup.out 2>&1 &
    sleep 3
    SPY_PID=$(pgrep -f "python.*s.py" | head -1)
    [ -n "$SPY_PID" ] && ok "s.py started PID $SPY_PID" || warn "s.py failed"
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
    fix "Dashboard not responding HTTP $HTTP_CODE - restarting"
    pkill -f "python.*s.py"
    sleep 1
    nohup python s.py >> /root/apexbot/nohup.out 2>&1 &
    sleep 3
    FIXES=$((FIXES+1))
fi

echo ""
echo "[ Bot Scanning ]"
LAST_SCAN=$(grep "Scan #" /root/apexbot/nohup.out 2>/dev/null | tail -1)
if [ -z "$LAST_SCAN" ]; then
    warn "No scan log found"
else
    LAST_SCAN_TIME=$(echo "$LAST_SCAN" | awk "{print \$1, \$2}")
    LAST_SCAN_EPOCH=$(date -d "$LAST_SCAN_TIME" +%s 2>/dev/null)
    AGE=$(( ($(date +%s) - LAST_SCAN_EPOCH) / 60 ))
    if [ "$AGE" -lt 5 ]; then
        ok "Bot scanning - last scan ${AGE}m ago"
    else
        fix "Last scan ${AGE}m ago - restarting"
        pkill -f "python.*s.py"
        sleep 1
        nohup python s.py >> /root/apexbot/nohup.out 2>&1 &
        sleep 3
        FIXES=$((FIXES+1))
    fi
fi

echo ""
echo "[ state.json ]"
if [ ! -f /root/apexbot/state.json ]; then
    fix "state.json missing"
    FIXES=$((FIXES+1))
else
    ok "state.json exists"
    SYMBOLS=$(python3 -c 'import json; s=json.load(open("state.json")); print(len(s.get("symbols") or []))' 2>/dev/null)
    if [ "${SYMBOLS:-0}" -lt 5 ]; then
        fix "symbols missing $SYMBOLS"
        FIXES=$((FIXES+1))
    else
        ok "symbols present $SYMBOLS coins"
    fi
    OPEN=$(python3 -c "import json; s=json.load(open("state.json")); print(len(s.get("open_trades") or {}))" 2>/dev/null)
    ok "Open trades: $OPEN"
fi

echo ""
echo "[ Scanner ]"
if ! systemctl is-active --quiet apexbot-scanner; then
    fix "scanner service not running - restarting"
    systemctl restart apexbot-scanner
    sleep 3
    systemctl is-active --quiet apexbot-scanner && ok "scanner restarted" || warn "scanner failed to start"
    FIXES=$((FIXES+1))
else
    ok "scanner service running (PID $(systemctl show -p MainPID --value apexbot-scanner))"
fi

echo ""
echo "[ Screen Sessions ]"
screen -ls

echo ""
echo "=========================="
[ "$FIXES" -eq 0 ] && echo "ALL GOOD - No fixes needed" || echo "Applied $FIXES fixes - check dashboard"
echo "=========================="
echo ""
