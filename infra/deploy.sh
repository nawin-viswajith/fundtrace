#!/usr/bin/env bash
# One-command deploy of FundTrace to Google Cloud (Cloud Run + Cloud SQL MySQL + Vertex AI + GCS).
# Run from the repo root in Cloud Shell or any shell with gcloud authenticated:
#   PROJECT=my-project REGION=asia-south1 ./infra/deploy.sh
# Re-running is safe: existing resources are reused, the service is redeployed.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT=<gcp project id>}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-fundtrace}"
INSTANCE="${INSTANCE:-fundtrace-sql}"
DB_NAME="${DB_NAME:-fundtrace}"
DB_USER="${DB_USER:-fundtrace}"
SQL_TIER="${SQL_TIER:-db-g1-small}"
BUCKET="${BUCKET:-${PROJECT}-fundtrace-evidence}"
SA_NAME="${SA_NAME:-fundtrace-run}"
GEMINI_FAST_MODELS="${GEMINI_FAST_MODELS:-gemini-3.8-flash,gemini-2.5-flash}"
GEMINI_PRO_MODELS="${GEMINI_PRO_MODELS:-gemini-3.1-pro-preview,gemini-2.5-pro}"
GEMINI_LOCATION="${GEMINI_LOCATION:-global}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

gcloud config set project "$PROJECT" >/dev/null

log "Enabling APIs"
gcloud services enable run.googleapis.com sqladmin.googleapis.com aiplatform.googleapis.com storage.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudtrace.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com iam.googleapis.com

log "Service account ($SA_EMAIL) with least-privilege roles"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="FundTrace Cloud Run"
for role in roles/aiplatform.user roles/cloudsql.client roles/secretmanager.secretAccessor roles/cloudtrace.agent \
            roles/logging.logWriter roles/monitoring.metricWriter; do
  bind "serviceAccount:$SA_EMAIL" "$role"
done

log "Allowing Cloud Build (default compute service account) to build from source"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
for role in roles/run.builder roles/logging.logWriter roles/artifactregistry.writer roles/storage.objectViewer; do
  bind "serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" "$role"
done

log "Cloud SQL for MySQL 8 ($INSTANCE, $SQL_TIER) — first creation takes ~10 minutes"
if ! gcloud sql instances describe "$INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$INSTANCE" --database-version=MYSQL_8_0 --edition=ENTERPRISE --tier="$SQL_TIER" \
    --region="$REGION" --storage-size=10GB --storage-auto-increase --availability-type=zonal
fi
gcloud sql databases describe "$DB_NAME" --instance="$INSTANCE" >/dev/null 2>&1 || \
  gcloud sql databases create "$DB_NAME" --instance="$INSTANCE" --charset=utf8mb4 --collation=utf8mb4_0900_ai_ci
CONN="$(gcloud sql instances describe "$INSTANCE" --format='value(connectionName)')"

if ! gcloud secrets describe fundtrace-db-url >/dev/null 2>&1; then
  log "Creating database user and secrets"
  DB_PASS="$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)"
  gcloud sql users create "$DB_USER" --instance="$INSTANCE" --password="$DB_PASS" >/dev/null 2>&1 || \
    gcloud sql users set-password "$DB_USER" --instance="$INSTANCE" --password="$DB_PASS"
  printf 'mysql+pymysql://%s:%s@/%s?unix_socket=/cloudsql/%s&charset=utf8mb4' "$DB_USER" "$DB_PASS" "$DB_NAME" "$CONN" | \
    gcloud secrets create fundtrace-db-url --data-file=- --replication-policy=automatic
fi
gcloud secrets describe fundtrace-jwt-secret >/dev/null 2>&1 || \
  openssl rand -base64 48 | tr -d '\n' | gcloud secrets create fundtrace-jwt-secret --data-file=- --replication-policy=automatic

log "Evidence bucket gs://$BUCKET (private, uniform access)"
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA_EMAIL" \
  --role=roles/storage.objectAdmin >/dev/null

log "Building and deploying to Cloud Run ($SERVICE in $REGION)"
gcloud run deploy "$SERVICE" --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --add-cloudsql-instances "$CONN" --allow-unauthenticated --memory 1Gi --cpu 1 --timeout 300 \
  --concurrency 40 --min-instances 0 --max-instances 3 \
  --set-env-vars "^@^ENVIRONMENT=cloud@GCP_PROJECT=$PROJECT@GCP_LOCATION=$REGION@GEMINI_LOCATION=$GEMINI_LOCATION@LLM_ENABLED=true@GEMINI_FAST_MODELS=$GEMINI_FAST_MODELS@GEMINI_PRO_MODELS=$GEMINI_PRO_MODELS@STORAGE_BACKEND=gcs@GCS_BUCKET=$BUCKET@OTEL_EXPORTER=gcp@COOKIE_SECURE=true@SEED_ON_START=true@SHOW_DEMO_CREDENTIALS=true@LOG_LEVEL=INFO" \
  --set-secrets "DATABASE_URL=fundtrace-db-url:latest,JWT_SECRET=fundtrace-jwt-secret:latest"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"

log "Log-based metrics + Cloud Monitoring dashboard"
gcloud logging metrics describe fundtrace_ai_calls >/dev/null 2>&1 || gcloud logging metrics create fundtrace_ai_calls \
  --description="FundTrace Gemini calls" --log-filter='resource.type="cloud_run_revision" AND jsonPayload.event="ai_call"'
gcloud logging metrics describe fundtrace_ai_failures >/dev/null 2>&1 || gcloud logging metrics create fundtrace_ai_failures \
  --description="FundTrace Gemini calls that failed (timeout/error/invalid/budget)" \
  --log-filter='resource.type="cloud_run_revision" AND jsonPayload.event="ai_call" AND jsonPayload.status!="ok"'
gcloud monitoring dashboards create --config-from-file=infra/monitoring-dashboard.json >/dev/null 2>&1 || true

log "Smoke test"
curl -fsS "$URL/api/healthz" 2>/dev/null || curl -fsS --ssl-no-revoke "$URL/api/healthz"; echo
echo
echo "FundTrace is live: $URL"
echo "Logins (synthetic demo): inv.asha / inv.ravi / sup.meera / admin — password shown on the login page."
