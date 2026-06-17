#!/usr/bin/env bash
# Full redeploy on a fresh kind cluster.
# Usage: bash deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing ingress-nginx controller..."
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/kind/deploy.yaml

echo "==> Waiting for ingress-nginx to be ready..."
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s

echo "==> Applying ConfigMaps (HTML pages)..."
kubectl apply -f "$SCRIPT_DIR/01-configmap-blue.yaml"
kubectl apply -f "$SCRIPT_DIR/02-configmap-green.yaml"

echo "==> Applying Deployments..."
kubectl apply -f "$SCRIPT_DIR/03-deployment-blue.yaml"
kubectl apply -f "$SCRIPT_DIR/04-deployment-green.yaml"

echo "==> Applying Service..."
kubectl apply -f "$SCRIPT_DIR/05-service.yaml"

echo "==> Applying Ingress..."
kubectl apply -f "$SCRIPT_DIR/06-ingress.yaml"

echo "==> Waiting for pods to be ready..."
kubectl rollout status deployment/webapp-blue  --timeout=60s
kubectl rollout status deployment/webapp-green --timeout=60s

echo ""
echo "==> Active slot: $(kubectl get svc webapp -o jsonpath='{.spec.selector.version}')"
echo ""
echo "==> Starting port-forward on http://localhost:8080 ..."
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &
sleep 1
echo ""
echo "App is live at: http://localhost:8080"
echo ""
echo "Switch to green:  kubectl patch svc webapp -p '{\"spec\":{\"selector\":{\"version\":\"green\"}}}'"
echo "Switch to blue:   kubectl patch svc webapp -p '{\"spec\":{\"selector\":{\"version\":\"blue\"}}}'"
