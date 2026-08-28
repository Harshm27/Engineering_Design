#!/usr/bin/env bash
#
# Deploy Drawing to Solid to Google Cloud Run.
#
#   ./cloudrun.sh <gcp-project-id> [region]
#
# Cloud Run scales to zero, so an idle service costs nothing, and this app's
# usage sits far inside Google's always-free monthly allowance. See DEPLOY.md
# for the arithmetic.
set -euo pipefail

PROJECT="${1:?usage: ./cloudrun.sh <gcp-project-id> [region]}"
REGION="${2:-europe-west2}"          # London
SERVICE="drawing-to-solid"

command -v gcloud >/dev/null || { echo "gcloud CLI not found: https://cloud.google.com/sdk/docs/install"; exit 1; }

echo "==> project ${PROJECT}, region ${REGION}"
gcloud config set project "${PROJECT}" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com --quiet

if ! gcloud secrets describe d2s-auth-pass >/dev/null 2>&1; then
  PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  printf '%s' "${PASS}" | gcloud secrets create d2s-auth-pass --data-file=- --quiet
  echo "==> generated a password and stored it in Secret Manager"
  echo "    username: ujjwal"
  echo "    password: ${PASS}"
  echo "    (retrieve later with: gcloud secrets versions access latest --secret=d2s-auth-pass)"
else
  echo "==> reusing the existing d2s-auth-pass secret"
fi

SA="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding d2s-auth-pass \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor --quiet >/dev/null

echo "==> building and deploying (first build takes several minutes)"
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --concurrency 4 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "AUTH_USER=ujjwal,OUTDIR=/tmp/out" \
  --set-secrets "AUTH_PASS=d2s-auth-pass:latest" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
echo
echo "==> live at ${URL}"
echo "    username ujjwal, password as printed above or from Secret Manager"
