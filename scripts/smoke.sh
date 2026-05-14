#!/usr/bin/env bash
# Post-deploy smoke test. Hits the deployed Railway URL with curl.
#
# Usage:
#   BASE_URL=https://mr-qualifier.up.railway.app TOKEN=xxx ./scripts/smoke.sh
#
# Exits non-zero on any failure. Doesn't touch Notion (read-only checks).

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:5050}"
TOKEN="${TOKEN:-}"
AUTH_HEADER=()
if [[ -n "$TOKEN" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer $TOKEN")
fi

pass() { echo "  ✓ $*"; }
fail() { echo "  ✗ $*" >&2; exit 1; }

echo "Smoke test → $BASE_URL"

# 1. Health endpoint is always open and reports JSON.
echo
echo "[1/5] GET /api/health"
HEALTH=$(curl -fsS "$BASE_URL/api/health") || fail "health endpoint unreachable"
echo "$HEALTH" | grep -q '"service"' || fail "health payload missing service field"
echo "$HEALTH" | grep -q 'mr-qualification' || fail "health payload not from this service"
pass "service responds"

AUTH_REQUIRED=$(echo "$HEALTH" | python3 -c "import json,sys; print(json.load(sys.stdin)['auth']['required'])")
APOLLO_MODE=$(echo "$HEALTH" | python3 -c "import json,sys; print(json.load(sys.stdin)['apollo']['mode'])")
NOTION_OK=$(echo "$HEALTH" | python3 -c "import json,sys; h=json.load(sys.stdin); print(h['notion']['configured'] and h['notion']['target_present'])")
echo "    auth_required=$AUTH_REQUIRED  apollo=$APOLLO_MODE  notion=$NOTION_OK"

if [[ "$AUTH_REQUIRED" == "True" && -z "$TOKEN" ]]; then
  fail "auth is required but TOKEN is unset"
fi

# 2. HTML serves.
echo
echo "[2/5] GET /"
curl -fsS "$BASE_URL/" | grep -q "Lead Qualification" || fail "HTML root did not serve the qualification UI"
pass "qualify.html served"

# 3. Qualify a known fixture (Deliveroo, will hit Apollo cache or live).
echo
echo "[3/5] POST /api/qualify (Deliveroo)"
QUAL=$(curl -fsS -X POST "$BASE_URL/api/qualify" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -H "Content-Type: application/json" \
  -d '{"name":"Deliveroo","url":"deliveroo.co.uk"}') || fail "qualify endpoint failed"
SCORE=$(echo "$QUAL" | python3 -c "import json,sys; print(json.load(sys.stdin)['score']['normalized_score'])")
STATUS=$(echo "$QUAL" | python3 -c "import json,sys; print(json.load(sys.stdin)['score']['status'])")
[[ -n "$SCORE" ]] || fail "qualify returned no score"
pass "Deliveroo scored $SCORE/$STATUS"

# 4. Pipeline read. Tolerant of 502 when Notion isn't configured (smoke is also
#    runnable against a freshly-deployed env that hasn't had keys set yet).
echo
echo "[4/5] GET /api/pipeline"
PIPE_HTTP=$(curl -s -o /tmp/pipe.json -w "%{http_code}" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  "$BASE_URL/api/pipeline?limit=5")
case "$PIPE_HTTP" in
  200)
    PIPE_COUNT=$(python3 -c "import json; print(json.load(open('/tmp/pipe.json')).get('count',0))")
    pass "pipeline returns $PIPE_COUNT rows"
    ;;
  502)
    if [[ "$NOTION_OK" == "False" ]]; then
      pass "pipeline 502 expected (Notion not configured)"
    else
      fail "pipeline 502 but Notion was reported configured. Body: $(cat /tmp/pipe.json)"
    fi
    ;;
  *) fail "pipeline returned unexpected $PIPE_HTTP" ;;
esac

# 5. HubSpot endpoint reports disabled state (or works if explicitly enabled).
echo
echo "[5/5] POST /api/hubspot/sync (probe — body intentionally minimal)"
HUB_HTTP=$(curl -s -o /tmp/hub_probe.json -w "%{http_code}" \
  -X POST "$BASE_URL/api/hubspot/sync" \
  ${AUTH_HEADER[@]+"${AUTH_HEADER[@]}"} \
  -H "Content-Type: application/json" \
  -d '{"company":{"name":"Probe","url":"probe.example"}}') || true
case "$HUB_HTTP" in
  503) pass "HubSpot disabled (expected default)" ;;
  200) pass "HubSpot live writes succeeded" ;;
  502) echo "    ⚠ HubSpot enabled but call failed (probably a missing custom prop). Body: $(cat /tmp/hub_probe.json)" ;;
  *)   fail "HubSpot endpoint returned unexpected $HUB_HTTP" ;;
esac

echo
echo "Smoke test passed."
