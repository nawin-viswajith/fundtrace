#!/usr/bin/env bash
# One-command deploy of FundTrace to Google Cloud (Cloud Run + Cloud SQL MySQL + Vertex AI + GCS).
# Run from the repo root in Cloud Shell or any shell with gcloud authenticated:
#   PROJECT=my-project REGION=asia-south1 ./infra/deploy.sh
# Re-running is safe: existing resources are reused, the service is redeployed.
# A second deployment at its own URL: SERVICE=fundtrace-v2 PROJECT=... ./infra/deploy.sh
#   Its database, DB user, secrets, evidence bucket and ledger topic are all named after SERVICE, so it never
#   touches another deployment's data. (Defaults for SERVICE=fundtrace match the original resource names.)
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT=<gcp project id>}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-fundtrace}"
INSTANCE="${INSTANCE:-fundtrace-sql}"
SVC_ID="${SERVICE//-/_}"                                 # fundtrace-v2 -> fundtrace_v2 (database/user names)
DB_NAME="${DB_NAME:-$SVC_ID}"
DB_USER="${DB_USER:-$SVC_ID}"
SQL_TIER="${SQL_TIER:-db-g1-small}"
BUCKET="${BUCKET:-${PROJECT}-${SERVICE}-evidence}"
SECRET_DB_URL="${SERVICE}-db-url"
SECRET_JWT="${SERVICE}-jwt-secret"
SECRET_FIELD_KEY="${SERVICE}-field-key-wrapped"
SA_NAME="${SA_NAME:-fundtrace-run}"
GEMINI_FAST_MODELS="${GEMINI_FAST_MODELS:-gemini-3.8-flash,gemini-2.5-flash}"
GEMINI_PRO_MODELS="${GEMINI_PRO_MODELS:-gemini-3.1-pro-preview,gemini-3.8-flash}"
GEMINI_LOCATION="${GEMINI_LOCATION:-global}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
KMS_KEYRING="${KMS_KEYRING:-fundtrace}"
KMS_KEY="${KMS_KEY:-field-data}"
LEDGER_TOPIC="${LEDGER_TOPIC:-${SERVICE}-ledger}"
PUSH_SA_NAME="${PUSH_SA_NAME:-${SERVICE}-ledger-push}"  # service-account ids are 6-30 characters
PUSH_SA="${PUSH_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
MFA_REQUIRED_ROLES="${MFA_REQUIRED_ROLES:-}"          # e.g. supervisor,admin (leave empty for the shared public demo)
DLP_BACKEND="${DLP_BACKEND:-gcp}"
FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID:-}"        # optional: enables the "Sign in with Google" button
FIREBASE_API_KEY="${FIREBASE_API_KEY:-}"

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

# IAM policy edits can collide ("concurrent policy changes"): retry with backoff; fail loudly at the end.
bind() {
  local n
  for n in 1 2 3 4 5; do
    if gcloud projects add-iam-policy-binding "$PROJECT" --member="$1" --role="$2" --condition=None >/dev/null 2>&1; then
      return 0
    fi
    sleep $((n * 4))
  done
  gcloud projects add-iam-policy-binding "$PROJECT" --member="$1" --role="$2" --condition=None >/dev/null
}

gcloud config set project "$PROJECT" >/dev/null

log "Enabling APIs"
gcloud services enable run.googleapis.com sqladmin.googleapis.com aiplatform.googleapis.com storage.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com cloudtrace.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com iam.googleapis.com cloudkms.googleapis.com dlp.googleapis.com \
  pubsub.googleapis.com

log "Service account ($SA_EMAIL) with least-privilege roles"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="FundTrace Cloud Run"
for role in roles/aiplatform.user roles/cloudsql.client roles/secretmanager.secretAccessor roles/cloudtrace.agent \
            roles/logging.logWriter roles/monitoring.metricWriter roles/dlp.user; do
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

if ! gcloud secrets describe "$SECRET_DB_URL" >/dev/null 2>&1; then
  log "Creating database user and secrets"
  DB_PASS="$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)"
  gcloud sql users create "$DB_USER" --instance="$INSTANCE" --password="$DB_PASS" >/dev/null 2>&1 || \
    gcloud sql users set-password "$DB_USER" --instance="$INSTANCE" --password="$DB_PASS"
  printf 'mysql+pymysql://%s:%s@/%s?unix_socket=/cloudsql/%s&charset=utf8mb4' "$DB_USER" "$DB_PASS" "$DB_NAME" "$CONN" | \
    gcloud secrets create "$SECRET_DB_URL" --data-file=- --replication-policy=automatic
fi
gcloud secrets describe "$SECRET_JWT" >/dev/null 2>&1 || \
  openssl rand -base64 48 | tr -d '\n' | gcloud secrets create "$SECRET_JWT" --data-file=- --replication-policy=automatic

log "Field-level encryption: data key wrapped by Cloud KMS ($KMS_KEYRING/$KMS_KEY)"
gcloud kms keyrings describe "$KMS_KEYRING" --location "$REGION" >/dev/null 2>&1 || \
  gcloud kms keyrings create "$KMS_KEYRING" --location "$REGION"
# The KMS key rotates every 90 days; old key versions stay enabled so the wrapped data key always unwraps.
gcloud kms keys describe "$KMS_KEY" --keyring "$KMS_KEYRING" --location "$REGION" >/dev/null 2>&1 || \
  gcloud kms keys create "$KMS_KEY" --keyring "$KMS_KEYRING" --location "$REGION" --purpose encryption \
    --rotation-period 90d \
    --next-rotation-time "$(date -u -d '+90 days' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+90d +%Y-%m-%dT%H:%M:%SZ)"
KMS_NAME="projects/$PROJECT/locations/$REGION/keyRings/$KMS_KEYRING/cryptoKeys/$KMS_KEY"
gcloud kms keys add-iam-policy-binding "$KMS_KEY" --keyring "$KMS_KEYRING" --location "$REGION" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/cloudkms.cryptoKeyDecrypter >/dev/null
# The data key is created ONCE. Never regenerate it: data encrypted with it would become unreadable.
if ! gcloud secrets describe "$SECRET_FIELD_KEY" >/dev/null 2>&1; then
  TMP_KEY="$(mktemp)"; TMP_WRAPPED="$(mktemp)"
  openssl rand 32 > "$TMP_KEY"
  gcloud kms encrypt --key "$KMS_KEY" --keyring "$KMS_KEYRING" --location "$REGION" \
    --plaintext-file "$TMP_KEY" --ciphertext-file "$TMP_WRAPPED"
  base64 < "$TMP_WRAPPED" | tr -d '\n' | \
    gcloud secrets create "$SECRET_FIELD_KEY" --data-file=- --replication-policy=automatic
  rm -f "$TMP_KEY" "$TMP_WRAPPED"
fi

log "Evidence bucket gs://$BUCKET (private, uniform access)"
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA_EMAIL" \
  --role=roles/storage.objectAdmin >/dev/null

log "Building and deploying to Cloud Run ($SERVICE in $REGION)"
gcloud run deploy "$SERVICE" --source . --region "$REGION" --service-account "$SA_EMAIL" \
  --add-cloudsql-instances "$CONN" --allow-unauthenticated --memory 1Gi --cpu 1 --timeout 900 \
  --concurrency 40 --min-instances 0 --max-instances 3 \
  --set-env-vars "^@^ENVIRONMENT=cloud@GCP_PROJECT=$PROJECT@GCP_LOCATION=$REGION@GEMINI_LOCATION=$GEMINI_LOCATION@LLM_ENABLED=true@LLM_TIMEOUT_SECONDS=60@LLM_PRO_TIMEOUT_SECONDS=150@GEMINI_FAST_MODELS=$GEMINI_FAST_MODELS@GEMINI_PRO_MODELS=$GEMINI_PRO_MODELS@STORAGE_BACKEND=gcs@GCS_BUCKET=$BUCKET@OTEL_EXPORTER=gcp@COOKIE_SECURE=true@SEED_ON_START=true@SHOW_DEMO_CREDENTIALS=true@LOG_LEVEL=INFO@FIELD_KEY_KMS_NAME=$KMS_NAME@DLP_BACKEND=$DLP_BACKEND@MFA_REQUIRED_ROLES=$MFA_REQUIRED_ROLES@FIREBASE_PROJECT_ID=$FIREBASE_PROJECT_ID@FIREBASE_API_KEY=$FIREBASE_API_KEY" \
  --set-secrets "DATABASE_URL=$SECRET_DB_URL:latest,JWT_SECRET=$SECRET_JWT:latest,FIELD_KEY_WRAPPED=$SECRET_FIELD_KEY:latest"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"

log "Ledger ingest: Pub/Sub topic $LEDGER_TOPIC -> push to $URL/api/ingest/pubsub (OIDC-signed)"
PUBSUB_AGENT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$PUSH_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$PUSH_SA_NAME" --display-name="FundTrace ledger push (Pub/Sub OIDC identity)"
gcloud iam service-accounts add-iam-policy-binding "$PUSH_SA" --member="serviceAccount:$PUBSUB_AGENT" \
  --role=roles/iam.serviceAccountTokenCreator >/dev/null
for t in "$LEDGER_TOPIC" "$LEDGER_TOPIC-dlq"; do
  gcloud pubsub topics describe "$t" >/dev/null 2>&1 || gcloud pubsub topics create "$t"
done
gcloud pubsub topics add-iam-policy-binding "$LEDGER_TOPIC-dlq" --member="serviceAccount:$PUBSUB_AGENT" \
  --role=roles/pubsub.publisher >/dev/null
PUSH_ARGS=(--push-endpoint "$URL/api/ingest/pubsub" --push-auth-service-account "$PUSH_SA"
           --push-auth-token-audience "$URL/api/ingest/pubsub" --ack-deadline 120
           --dead-letter-topic "$LEDGER_TOPIC-dlq" --max-delivery-attempts 10 --min-retry-delay 10s --max-retry-delay 600s)
if gcloud pubsub subscriptions describe "$LEDGER_TOPIC-push" >/dev/null 2>&1; then
  gcloud pubsub subscriptions update "$LEDGER_TOPIC-push" "${PUSH_ARGS[@]}" >/dev/null
else
  gcloud pubsub subscriptions create "$LEDGER_TOPIC-push" --topic "$LEDGER_TOPIC" "${PUSH_ARGS[@]}"
fi
gcloud pubsub subscriptions add-iam-policy-binding "$LEDGER_TOPIC-push" --member="serviceAccount:$PUBSUB_AGENT" \
  --role=roles/pubsub.subscriber >/dev/null
gcloud run services update "$SERVICE" --region "$REGION" \
  --update-env-vars "PUBSUB_PUSH_AUDIENCE=$URL/api/ingest/pubsub,PUBSUB_PUSH_SERVICE_ACCOUNT=$PUSH_SA" >/dev/null

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
echo "Ledger ingest: python -m scripts.publish_ledger --project $PROJECT --topic $LEDGER_TOPIC --format iso20022.camt.053 <file>"
