#!/usr/bin/env bash
#
# Deploiement sur Google Cloud Run.
#
# Le script ne deploie rien sans confirmation : il affiche d'abord ce qu'il va
# faire, y compris les reglages qui ont un cout ou une consequence de securite,
# puis attend un accord explicite.
#
# Usage :
#   PROJET=mon-projet ./scripts/deploy_cloud_run.sh [--verapdf] [--oui]
#
# Variables reconnues :
#   PROJET          projet Google Cloud, obligatoire
#   REGION          region, europe-west1 par defaut
#   SERVICE         nom du service, facturx-validator par defaut
#   REDIS_URL       compteurs partages, fortement conseille pour facturer
#   METRICS_TOKEN   ouvre /api/metrics
#   API_KEYS        declaration des cles d'API
#   CONTACT_EMAIL   contact propose dans l'interface

set -euo pipefail

REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-facturx-validator}"
CIBLE_IMAGE="service"
MEMOIRE="1Gi"
CONFIRME="non"

for argument in "$@"; do
  case "$argument" in
    --verapdf) CIBLE_IMAGE="service-verapdf"; MEMOIRE="2Gi" ;;
    --oui) CONFIRME="oui" ;;
    *) echo "argument inconnu : $argument" >&2; exit 2 ;;
  esac
done

if [[ -z "${PROJET:-}" ]]; then
  echo "PROJET n'est pas defini. Exemple : PROJET=mon-projet $0" >&2
  exit 2
fi

# Les variables d'environnement sont passees par fichier plutot qu'en ligne de
# commande : une ligne de commande est visible dans la liste des processus et dans
# l'historique du shell, ce qui n'est pas un endroit pour des cles.
FICHIER_ENV="$(mktemp)"
trap 'rm -f "$FICHIER_ENV"' EXIT
{
  echo "TRUST_PROXY_HEADERS: '1'"
  echo "WARMUP_ON_STARTUP: '1'"
  [[ -n "${REDIS_URL:-}" ]] && echo "REDIS_URL: '${REDIS_URL}'"
  [[ -n "${METRICS_TOKEN:-}" ]] && echo "METRICS_TOKEN: '${METRICS_TOKEN}'"
  [[ -n "${API_KEYS:-}" ]] && echo "API_KEYS: '${API_KEYS}'"
  [[ -n "${CONTACT_EMAIL:-}" ]] && echo "CONTACT_EMAIL: '${CONTACT_EMAIL}'"
} > "$FICHIER_ENV"

echo "Deploiement envisage"
echo "  projet          : ${PROJET}"
echo "  region          : ${REGION}"
echo "  service         : ${SERVICE}"
echo "  image           : cible ${CIBLE_IMAGE}"
echo "  memoire         : ${MEMOIRE}"
echo "  acces           : public, sans authentification"
echo "  instance chaude : 1, pour eviter la compilation des artefacts a froid"
echo
echo "Reglages transmis :"
sed 's/^/  /' "$FICHIER_ENV" | sed "s/\(REDIS_URL\|METRICS_TOKEN\|API_KEYS\): .*/\1: ***/"
echo

if [[ -z "${REDIS_URL:-}" ]]; then
  echo "Attention : REDIS_URL n'est pas defini."
  echo "  Les quotas repartiront de zero a chaque redemarrage d'instance et les"
  echo "  plafonds de debit resteront locaux a chaque instance. Suffisant pour un"
  echo "  service gratuit, insuffisant pour facturer a l'usage."
  echo
fi

echo "Ce service sera accessible publiquement sur Internet et sa consommation sera"
echo "facturee par Google Cloud."
if [[ "$CONFIRME" != "oui" ]]; then
  read -r -p "Confirmer le deploiement ? (tapez oui) " reponse
  [[ "$reponse" == "oui" ]] || { echo "deploiement abandonne"; exit 1; }
fi

# --min-instances 1  : evite la compilation des artefacts a froid, environ 1,2 s.
# --concurrency 16   : les validations passent par un fil unique, ce plafond borne
#                      le nombre de requetes qu'une instance accepte de front.
# --cpu-boost        : accelere le demarrage, ou se concentre tout le cout fixe.
gcloud run deploy "$SERVICE" \
  --project "$PROJET" \
  --region "$REGION" \
  --source . \
  --allow-unauthenticated \
  --memory "$MEMOIRE" \
  --cpu 1 \
  --concurrency 16 \
  --min-instances 1 \
  --max-instances 10 \
  --timeout 60s \
  --cpu-boost \
  --env-vars-file "$FICHIER_ENV" \
  --labels "application=facturx-validator"

URL="$(gcloud run services describe "$SERVICE" \
  --project "$PROJET" --region "$REGION" --format 'value(status.url)')"

echo
echo "Deploye : ${URL}"
echo "Verification de l'etat de sante :"
curl -sf "${URL}/api/health" || {
  echo "la sonde de sante ne repond pas" >&2
  exit 1
}
echo
echo "Etapes restantes, a faire une fois :"
echo "  1. Rattacher un domaine : gcloud run domain-mappings create"
echo "  2. Regle de pare-feu si un plafond global strict est voulu, Cloud Armor"
echo "  3. Verifier /docs, la documentation d'API est visible publiquement"
