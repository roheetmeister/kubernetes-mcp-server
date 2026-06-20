#!/usr/bin/env bash
set -euo pipefail

WEIGHT=${1:-}

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "$WEIGHT" ]]; then
  echo "Usage: $0 <canary-weight>"
  echo "       weight must be an integer between 1 and 99"
  echo ""
  echo "Examples:"
  echo "  $0 20    →  v1: 80%  v2: 20%"
  echo "  $0 50    →  v1: 50%  v2: 50%"
  echo "  $0 80    →  v1: 20%  v2: 80%"
  exit 1
fi

if ! [[ "$WEIGHT" =~ ^[0-9]+$ ]] || (( WEIGHT < 1 || WEIGHT > 99 )); then
  echo "Error: weight must be an integer between 1 and 99 (got: $WEIGHT)"
  exit 1
fi

export STABLE_PCT=$(( 100 - WEIGHT ))
export CANARY_PCT=$WEIGHT
export WEIGHT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "  Canary Weight Update"
echo "  ─────────────────────────────────────────────"
echo "  v1  (stable)   →  ${STABLE_PCT}%  of traffic"
echo "  v2  (canary)   →  ${CANARY_PCT}%  of traffic"
echo "  canary-weight  →  ${WEIGHT}"
echo "  ─────────────────────────────────────────────"
echo ""

# ── Step 1: Patch ingress annotation ─────────────────────────────────────────
echo "[1/3] Patching ingress webapp-canary (canary-weight=${WEIGHT})..."
kubectl annotate ingress webapp-canary \
  nginx.ingress.kubernetes.io/canary-weight="${WEIGHT}" \
  --overwrite
echo "      ingress.networking.k8s.io/webapp-canary annotated"

# ── Step 2: Rebuild ConfigMaps (sed substitution) ────────────────────────────
echo ""
echo "[2/3] Updating ConfigMaps with new percentages..."
substitute() {
  sed \
    -e "s/\${STABLE_PCT}/${STABLE_PCT}/g" \
    -e "s/\${CANARY_PCT}/${CANARY_PCT}/g" \
    -e "s/\${WEIGHT}/${WEIGHT}/g" \
    "$1"
}
substitute "${SCRIPT_DIR}/01-configmap-v1.yaml" | kubectl apply -f -
substitute "${SCRIPT_DIR}/02-configmap-v2.yaml" | kubectl apply -f -

# ── Step 3: Rolling restart to pick up ConfigMap changes ─────────────────────
echo ""
echo "[3/3] Rolling restart to pick up new ConfigMaps..."
kubectl rollout restart deployment/webapp-stable deployment/webapp-canary
kubectl rollout status deployment/webapp-stable deployment/webapp-canary --timeout=90s

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  Done!"
echo "  Traffic is now ${STABLE_PCT}% stable (v1) / ${CANARY_PCT}% canary (v2)"
echo "  Refresh http://localhost:8080 to see the update."
echo ""
