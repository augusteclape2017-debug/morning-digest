#!/bin/bash
cd "$(dirname "$0")" || exit 1

clear
echo "=================================================="
echo "  Morning Digest"
echo "=================================================="
echo ""

echo "Clearing any previous session..."
PIDS=$(lsof -ti:8000 2>/dev/null)
if [ -n "$PIDS" ]; then
  kill -9 $PIDS 2>/dev/null
fi
sleep 0.5

if [ -z "$ANTHROPIC_API_KEY" ] && [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo ""
  echo "No API key found yet."
  echo "Paste your Anthropic API key (starts with sk-ant-) and press Enter:"
  read -r ANTHROPIC_API_KEY
  export ANTHROPIC_API_KEY
  echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" > .env
  echo "Saved — you won't be asked again on this Mac."
  echo ""
fi

echo "Generating today's digest (usually 30-90 seconds)..."
echo ""
python3 generate_digest.py
DIGEST_STATUS=$?

if [ $DIGEST_STATUS -ne 0 ]; then
  echo ""
  echo "Digest generation failed — see error above."
  echo "Press Enter to close this window."
  read -r
  exit 1
fi

echo ""
echo "Digest ready."
echo ""

cd docs || exit 1
nohup python3 -m http.server 8000 > /tmp/morning-digest-server.log 2>&1 &
cd ..

sleep 1
if ! lsof -ti:8000 > /dev/null 2>&1; then
  echo "Server failed to start. Check /tmp/morning-digest-server.log"
  echo "Press Enter to close this window."
  read -r
  exit 1
fi

TIMESTAMP=$(date +%s)
open -a Safari "http://localhost:8000?t=${TIMESTAMP}"

echo "Done — your briefing is open in Safari."
echo "This window will close automatically in 5 seconds..."
sleep 5
osascript -e 'tell application "Terminal" to close (every window whose name contains "Run Morning Digest")' >/dev/null 2>&1
exit 0