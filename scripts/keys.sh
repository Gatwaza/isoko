#!/usr/bin/env bash
# Control who can use the Isôko API on the hosted deployment (Vercel). Every change takes effect after a
# ~1 minute redeploy. Keys are kept locally in .api_keys (git-ignored), one "label key" pair per line.
#
#   scripts/keys.sh list               show who has access (keys masked)
#   scripts/keys.sh new c4ir           issue a key for an evaluator (prints it once: send it privately)
#   scripts/keys.sh revoke c4ir        remove that evaluator's access
#   scripts/keys.sh pause              emergency stop: every API call returns 401 until resume
#   scripts/keys.sh resume             restore all keys in .api_keys
#   scripts/keys.sh dashboard          create/rotate the dashboard token and print the private dashboard link
set -euo pipefail
cd "$(dirname "$0")/.."
FILE=.api_keys
URL=https://isoko-agri.vercel.app
touch "$FILE"; chmod 600 "$FILE"

push() {  # $1 = env var name, $2 = value
  vercel env rm "$1" production -y >/dev/null 2>&1 || true
  printf '%s' "$2" | vercel env add "$1" production >/dev/null
  echo "Redeploying (about 1 minute)..."
  vercel deploy --prod --yes >/dev/null && echo "Live."
}
keys() { awk '{print $2}' "$FILE" | paste -sd, -; }

case "${1:-list}" in
  list)
    [ -s "$FILE" ] || { echo "No keys yet. Run: scripts/keys.sh new <label>"; exit 0; }
    awk '{printf "%-12s %s…%s\n", $1, substr($2,1,8), substr($2,length($2)-3)}' "$FILE" ;;
  new)
    label="${2:?label, e.g. c4ir}"
    grep -q "^$label " "$FILE" && { echo "Label '$label' exists; revoke it first."; exit 1; }
    key="isk_${label}_$(python3 -c 'import secrets;print(secrets.token_hex(16))')"
    echo "$label $key" >> "$FILE"
    push API_KEYS "$(keys)"
    echo; echo "Key for $label (send privately; it is not shown again):"; echo "  $key" ;;
  revoke)
    label="${2:?label}"
    grep -v "^$label " "$FILE" > "$FILE.tmp" || true; mv "$FILE.tmp" "$FILE"
    push API_KEYS "$(keys)"; echo "Revoked: $label" ;;
  pause)
    push API_KEYS "paused-$(python3 -c 'import secrets;print(secrets.token_hex(24))')"
    echo "API paused: every call now gets 401. Run 'scripts/keys.sh resume' to restore." ;;
  resume)
    [ -s "$FILE" ] || { echo "No keys in $FILE"; exit 1; }
    push API_KEYS "$(keys)"; echo "Resumed for: $(awk '{print $1}' "$FILE" | paste -sd' ' -)" ;;
  dashboard)
    tok=$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')
    push DASHBOARD_TOKEN "$tok"
    echo "Private dashboard link (full detail): $URL/dashboard?token=$tok"
    echo "Without the token the dashboard shows aggregate counts only." ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
