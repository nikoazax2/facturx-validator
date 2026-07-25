"""API du validateur Factur-X.

Service sans etat : le fichier recu est traite en memoire et n'est jamais ecrit
sur disque ni conserve apres la reponse. Aucun compte, aucun journal de contenu.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from hmac import compare_digest
from typing import Any

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import apikeys, config, leads, store, throttle
from .engine import messages, profiles, regulatory
from .engine.orchestrator import validate
from .engine.resources import RESOURCES, ArtifactsMissing
from .metrics import METRIQUES

logger = logging.getLogger("facturx")

ACCEPTED_SUFFIXES = (".pdf", ".xml")

# Fil unique dedie a la validation.
#
# Deux raisons, qui vont dans le meme sens.
#
# La validation est un calcul bloquant de plusieurs dizaines de millisecondes. La
# laisser s'executer sur la boucle d'evenements y bloquerait tout le reste, y
# compris les sondes de sante et les reponses d'erreur, qui attendraient derriere
# le calcul en cours.
#
# Le moteur XSLT Saxon repose par ailleurs sur un isolat GraalVM dont le
# rattachement aux fils demande des precautions. Un fil unique et permanent rend
# cette contrainte structurellement satisfaite, au lieu de reposer sur un verrou
# dont on esperait qu'il suffise. La serialisation qui en decoule n'est pas une
# perte : les appels Schematron etaient de toute facon serialises.
EXECUTEUR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="validation")
_READY: dict[str, Any] = {
    "artifacts": False,
    "warmup": None,
    "error": None,
    "keysError": None,
    "storeError": None,
}

# Limiteurs par cle, distincts de celui des appelants anonymes : un client sous
# contrat ne doit pas etre freine par le trafic public.
_LIMITEURS_CLES: dict[str, throttle.RateLimiter] = {}


def _limiteur_de_cle(cle: apikeys.CleApi) -> throttle.RateLimiter:
    limiteur = _LIMITEURS_CLES.get(cle.identifiant)
    if limiteur is None or limiteur.debit_par_minute != cle.par_minute:
        limiteur = throttle.RateLimiter(
            per_minute=cle.par_minute,
            # Une rafale d'un dixieme du plafond minute absorbe les envois groupes
            # d'une integration, sans permettre de vider le quota d'un coup.
            burst=max(10, cle.par_minute // 10),
            max_tracked=8,
        )
        _LIMITEURS_CLES[cle.identifiant] = limiteur
    return limiteur


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Precompile les artefacts avant la premiere requete.

    Sans ce prechauffage, la premiere validation paierait la compilation des
    feuilles XSLT et des schemas, ce qui ferait sortir de la cible de trois
    secondes le premier utilisateur apres chaque demarrage a froid.
    """
    try:
        RESOURCES.verify()
        _READY["artifacts"] = True
        # Cree l'isolat Saxon et precompile les artefacts dans le fil dedie a la
        # validation, celui-la meme qui les utilisera. Voir EXECUTEUR et
        # Resources.ensure_processor.
        EXECUTEUR.submit(RESOURCES.ensure_processor).result()
        if config.WARMUP_ON_STARTUP:
            timings = EXECUTEUR.submit(RESOURCES.warmup).result()
            _READY["warmup"] = timings
            logger.info("artefacts precompiles : %s", timings)
    except ArtifactsMissing as exc:
        # Le detail contient des chemins serveur, et l'etat de sante est public :
        # la trace complete va dans les journaux, la reponse reste generique.
        _READY["error"] = "artefacts de validation indisponibles"
        logger.error("artefacts indisponibles : %s", exc)

    # Un compteur partage injoignable ne doit pas empecher le demarrage : on
    # retombe sur la memoire, et l'etat de sante l'annonce.
    _READY["storeError"] = store.initialiser()

    # Une declaration de cles erronee ne doit pas empecher le service public de
    # fonctionner : elle est signalee, et l'acces par cle reste simplement inactif.
    _READY["keysError"] = apikeys.charger_depuis_environnement()
    yield


DESCRIPTION_API = """
Validation de factures électroniques au format Factur-X, sur quatre niveaux
indépendants : conteneur PDF/A-3, validité XSD, conformité EN 16931, et règles
propres au profil Factur-X détecté.

Aucune règle métier n'est réimplémentée. Le service exécute les artefacts publiés
par le CEN/TC 434 et la FNFE-MPE, et cite pour chaque constat son code de règle,
son chemin XPath et le test évalué.

### Confidentialité

Le fichier est traité en mémoire et libéré avec la réponse. Il n'est ni écrit sur
disque, ni conservé, ni transmis à un tiers. Aucune adresse IP n'est conservée.

### Accès

L'accès anonyme est gratuit et plafonné, pour un usage manuel ou occasionnel.
Un usage automatisé ou intensif relève d'un accès par clé, présentée dans
l'en-tête `X-API-Key`. Voir `GET /api/about` pour les plans, et `GET /api/key`
pour l'état de votre clé.

### Interprétation d'une réponse

Un fichier non conforme rend `200` avec le rapport : une non-conformité est un
résultat d'analyse, pas une erreur de requête. Les codes `4xx` signalent un
problème de requête, les `5xx` un incident de service.
"""

TAGS_OPENAPI = [
    {
        "name": "Validation",
        "description": "Analyse d'une facture et production du rapport.",
    },
    {
        "name": "Intégration",
        "description": (
            "Suivi d'une clé d'API : plan, plafonds et consommation du mois."
        ),
    },
    {
        "name": "Service",
        "description": "État du service, artefacts utilisés, repères réglementaires.",
    },
]

app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    summary=(
        "Validation de factures Factur-X : conteneur PDF/A-3, schéma XSD, "
        "EN 16931 et règles de profil."
    ),
    description=DESCRIPTION_API,
    openapi_tags=TAGS_OPENAPI,
    license_info={"name": "Propriétaire, tous droits réservés"},
    lifespan=lifespan,
)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )


def _error(
    status: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    METRIQUES.enregistrer_refus(code)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, **extra}},
        headers=headers,
    )


@app.get("/api/health", tags=["Service"], summary="État du service")
def health() -> dict[str, Any]:
    healthy = _READY["artifacts"] and _READY["error"] is None
    return {
        "status": "ok" if healthy else "degraded",
        "version": config.APP_VERSION,
        "artifactsLoaded": _READY["artifacts"],
        "warmup": _READY["warmup"],
        "error": _READY["error"],
        "concurrency": throttle.CONCURRENCE.etat,
        "counters": store.COMPTEUR.sante(),
        "countersError": _READY["storeError"],
        "apiKeysError": _READY["keysError"],
    }


def _cle_presentee(request: Request) -> str | None:
    """Lit la cle dans X-API-Key, ou dans un en-tete Authorization Bearer."""
    directe = request.headers.get("x-api-key")
    if directe:
        return directe.strip()
    autorisation = request.headers.get("authorization") or ""
    if autorisation.lower().startswith("bearer "):
        return autorisation[7:].strip()
    return None


@app.get("/api/key", tags=["Intégration"], summary="État de la clé et consommation")
def etat_cle(request: Request) -> Any:
    """Plan, plafonds et consommation du mois en cours.

    Destine aux integrateurs : permet de verifier qu'une cle est active et de
    suivre le solde sans attendre un refus.
    """
    presentee = _cle_presentee(request)
    if not presentee:
        return _error(
            401,
            "CLE_ABSENTE",
            "Présentez votre clé dans l'en-tête X-API-Key.",
        )
    cle = apikeys.REGISTRE.resoudre(presentee)
    if cle is None:
        return _error(401, "CLE_INVALIDE", "Clé inconnue ou révoquée.")
    etat = apikeys.REGISTRE.etat_public(cle)
    etat["expired"] = cle.expiree()
    return etat


@app.post(
    "/api/lead",
    tags=["Intégration"],
    summary="Demander à être recontacté",
)
async def manifester_interet(request: Request) -> Any:
    """Enregistre une demande de contact, sur initiative du visiteur.

    Ne touche jamais au fichier depose, qui n'est de toute facon plus en memoire a
    ce stade. Les seuls faits de validation transmis sont ceux que l'appelant
    renvoie lui-meme, filtres par liste blanche.
    """
    if not leads.active():
        return _error(
            404,
            "CONTACT_INDISPONIBLE",
            "La demande de contact n'est pas ouverte sur cette instance.",
        )

    # Meme plafond que la validation : ce point d'entree ne doit pas devenir un
    # moyen d'inonder la destination configuree.
    if config.RATE_LIMIT_ENABLED:
        empreinte = throttle.client_fingerprint(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
        )
        autorise, _ = throttle.LIMITEUR.autorise(f"lead:{empreinte}")
        if not autorise:
            return _error(
                429,
                "TROP_DE_REQUETES",
                "Trop de demandes en peu de temps. Réessayez dans un instant.",
                headers={"Retry-After": "60"},
            )

    try:
        charge = await request.json()
    except Exception:
        return _error(400, "CORPS_INVALIDE", "Le corps de la requête n'est pas du JSON.")
    if not isinstance(charge, dict):
        return _error(400, "CORPS_INVALIDE", "Un objet JSON est attendu.")

    try:
        interet = leads.construire(charge, charge.get("report"))
        await asyncio.get_running_loop().run_in_executor(
            None, leads.transmettre, interet
        )
    except leads.Refus as refus:
        statut = 502 if refus.code == "DESTINATION_EN_ECHEC" else 400
        return _error(statut, refus.code, refus.message)

    METRIQUES.enregistrer_interet()
    return {
        "received": True,
        "message": (
            "Demande enregistrée. Vous pouvez demander son effacement à tout moment."
        ),
    }


@app.get("/api/metrics", tags=["Service"], summary="Compteurs agrégés, accès restreint")
def metrics(request: Request) -> Any:
    """Compteurs agreges. Ferme par defaut.

    Le volume traite et la repartition des profils sont des donnees commerciales :
    les exposer publiquement renseignerait un concurrent. L'acces n'est donc ouvert
    que si un jeton est configure, et il doit etre presente.
    """
    if not config.METRICS_TOKEN:
        return _error(
            404,
            "METRIQUES_DESACTIVEES",
            (
                "Les métriques ne sont pas exposées. Définissez METRICS_TOKEN pour "
                "activer cet accès."
            ),
        )

    presente = request.headers.get("x-metrics-token") or ""
    if not compare_digest(presente, config.METRICS_TOKEN):
        return _error(401, "JETON_INVALIDE", "Jeton de métriques absent ou invalide.")

    instantane = METRIQUES.instantane()
    instantane["throttle"] = {
        "enabled": config.RATE_LIMIT_ENABLED,
        "limitPerMinute": config.RATE_LIMIT_PER_MINUTE,
        "burst": config.RATE_LIMIT_BURST,
        "trackedClients": throttle.LIMITEUR.suivis,
        "concurrency": throttle.CONCURRENCE.etat,
    }
    return instantane


@app.get("/api/about", tags=["Service"], summary="Artefacts, plans et repères réglementaires")
def about() -> dict[str, Any]:
    """Ce sur quoi le service s'appuie, pour que le rapport soit verifiable."""
    payload: dict[str, Any] = {
        "name": config.APP_NAME,
        "version": config.APP_VERSION,
        "reportSchemaVersion": config.REPORT_SCHEMA_VERSION,
        "maxUploadBytes": config.MAX_UPLOAD_BYTES,
        "acceptedInputs": [
            "PDF Factur-X (PDF/A-3 avec XML incorpore)",
            "XML CII (CrossIndustryInvoice D16B ou D22B)",
            "XML UBL 2.1 (Invoice ou CreditNote)",
        ],
        "profiles": [
            {
                "code": profile.code,
                "label": profile.label,
                "urn": profile.urns[0] if profile.urns else None,
                "en16931Scope": profile.en16931_scope,
                "fiscallyComplete": profile.fiscally_complete,
            }
            for profile in profiles.PROFILES
        ],
        "messageCatalogue": messages.coverage(),
        "regulatory": regulatory.block(),
        "privacy": {
            "storage": "aucun",
            "retention": "le fichier est traite en memoire et libere avec la reponse",
            "accounts": "aucun compte requis",
            "addresses": (
                "aucune adresse IP conservee : la limitation de debit repose sur une "
                "empreinte tronquee, salee aleatoirement au demarrage du processus"
            ),
        },
        "limits": {
            "rateLimitEnabled": config.RATE_LIMIT_ENABLED,
            "perMinute": config.RATE_LIMIT_PER_MINUTE,
            "burst": config.RATE_LIMIT_BURST,
            "maxConcurrent": config.MAX_CONCURRENT_VALIDATIONS,
            "sharedCounters": store.COMPTEUR.partage,
            "note": (
                "Plafonds appliques a l'echelle du service quand les compteurs sont "
                "partages, par instance sinon. Un usage automatise ou intensif "
                "releve d'un acces par cle."
            ),
        },
        "leadCapture": leads.mentions(),
        "apiAccess": {
            "enabled": apikeys.REGISTRE.actif,
            "header": "X-API-Key",
            "alternativeHeader": "Authorization: Bearer <cle>",
            "statusEndpoint": "/api/key",
            "documentationUrl": "/docs",
            # Vides tant qu'aucun contact n'est configure : l'interface s'abstient
            # alors de proposer une demarche, plutot que d'annoncer une adresse
            # inexistante.
            "contactEmail": config.CONTACT_EMAIL or None,
            "contactUrl": config.CONTACT_URL or None,
            "plans": [
                {
                    "id": identifiant,
                    "label": plan["label"],
                    "perMinute": plan["perMinute"],
                    "perMonth": plan["perMonth"],
                    "description": plan["description"],
                }
                for identifiant, plan in apikeys.PLANS.items()
            ],
        },
    }
    try:
        payload["artifacts"] = RESOURCES.artifact_summary()
    except ArtifactsMissing as exc:
        payload["artifacts"] = {"error": str(exc)}
    return payload


@app.post(
    "/api/validate",
    tags=["Validation"],
    summary="Valider un PDF Factur-X ou un XML seul",
)
async def validate_endpoint(request: Request, file: UploadFile = File(...)) -> Any:
    if _READY["error"]:
        return _error(
            503,
            "ARTEFACTS_INDISPONIBLES",
            "Le service n'est pas en état de valider. Réessayez plus tard.",
        )

    # ---- identification de l'appelant ------------------------------------
    presentee = _cle_presentee(request)
    cle = apikeys.REGISTRE.resoudre(presentee)
    entetes: dict[str, str] = {}

    if presentee and cle is None:
        return _error(
            401,
            "CLE_INVALIDE",
            "La clé d'API présentée est inconnue ou révoquée.",
        )
    if cle is not None and cle.expiree():
        return _error(
            403,
            "CLE_EXPIREE",
            (
                f"La clé « {cle.libelle} » a expiré le "
                f"{cle.expire_le.isoformat() if cle.expire_le else 'inconnu'}."
            ),
        )

    if cle is not None:
        limiteur = _limiteur_de_cle(cle)
        autorise, attente = limiteur.autorise(cle.identifiant)
        # Deux plafonds successifs : le seau local protege l'instance, le compteur
        # partage fait respecter le plafond du plan a l'echelle du service.
        if autorise and throttle.debit_partage_depasse(
            f"cle:{cle.identifiant}", cle.par_minute
        ):
            autorise, attente = False, 60.0
        if not autorise:
            secondes = max(1, int(attente) + 1)
            return _error(
                429,
                "TROP_DE_REQUETES",
                (
                    f"Plafond du plan atteint : {cle.par_minute} validations par "
                    f"minute. Réessayez dans {secondes} seconde(s)."
                ),
                headers={"Retry-After": str(secondes)},
                retryAfterSeconds=secondes,
                limitPerMinute=cle.par_minute,
            )

    elif config.RATE_LIMIT_ENABLED:
        empreinte = throttle.client_fingerprint(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
        )
        autorise, attente = throttle.LIMITEUR.autorise(empreinte)
        if autorise and throttle.debit_partage_depasse(
            f"anon:{empreinte}", config.RATE_LIMIT_PER_MINUTE
        ):
            autorise, attente = False, 60.0
        if not autorise:
            secondes = max(1, int(attente) + 1)
            return _error(
                429,
                "TROP_DE_REQUETES",
                (
                    "Trop de validations en peu de temps. Réessayez dans "
                    f"{secondes} seconde(s). Pour un usage intensif ou automatisé, "
                    "un accès par clé est disponible."
                ),
                headers={"Retry-After": str(secondes)},
                retryAfterSeconds=secondes,
                limitPerMinute=config.RATE_LIMIT_PER_MINUTE,
            )
        entetes = {"X-RateLimit-Limit": str(config.RATE_LIMIT_PER_MINUTE)}

    filename = file.filename or "sans-nom"
    if not filename.lower().endswith(ACCEPTED_SUFFIXES):
        return _error(
            415,
            "EXTENSION_NON_SUPPORTEE",
            (
                f"L'extension du fichier « {filename} » n'est pas prise en charge. "
                "Déposez un fichier .pdf ou .xml."
            ),
        )

    # Lecture bornee : on s'arrete des le depassement, sans charger le surplus.
    limit = config.MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return _error(
                413,
                "FICHIER_TROP_VOLUMINEUX",
                (
                    f"Le fichier dépasse la taille maximale de "
                    f"{limit // (1024 * 1024)} Mo."
                ),
                maxUploadBytes=limit,
            )
        chunks.append(chunk)

    raw = b"".join(chunks)
    chunks.clear()

    if not raw:
        return _error(400, "FICHIER_VIDE", "Le fichier reçu est vide.")

    # ---- quota, decompte seulement pour une requete recevable -------------
    # Deliberement place apres les controles d'entree : une requete refusee pour
    # son extension, sa taille ou sa vacuite n'a rien coute au service, elle ne
    # doit donc pas amputer le quota du client.
    if cle is not None:
        dans_le_quota, solde = apikeys.REGISTRE.consommer(cle)
        if not dans_le_quota:
            return _error(
                402,
                "QUOTA_EPUISE",
                (
                    f"Le quota mensuel du plan est épuisé : {cle.par_mois} "
                    "validations. Il est réinitialisé au début du mois suivant."
                ),
                quotaPerMonth=cle.par_mois,
            )
        entetes = {
            "X-RateLimit-Limit": str(cle.par_minute),
            "X-Quota-Limit": str(cle.par_mois),
            "X-Quota-Remaining": str(solde),
            "X-Plan": cle.plan,
        }

    try:
        with throttle.CONCURRENCE:
            boucle = asyncio.get_running_loop()
            report = await boucle.run_in_executor(
                EXECUTEUR, partial(validate, raw, filename=filename)
            )
    except throttle.Saturated as exc:
        return _error(
            503,
            "SERVICE_SATURE",
            (
                "Le service traite déjà le maximum de validations simultanées. "
                "Réessayez dans quelques secondes."
            ),
            headers={"Retry-After": "5"},
            maxConcurrent=exc.maximum,
        )
    except ArtifactsMissing as exc:
        logger.error("artefacts indisponibles pendant la validation : %s", exc)
        return _error(
            503,
            "ARTEFACTS_INDISPONIBLES",
            "Le service n'est pas en état de valider. Réessayez plus tard.",
        )
    except Exception:
        # Rien du contenu n'est journalise : seule la trace technique l'est.
        logger.exception("echec inattendu de la validation")
        METRIQUES.enregistrer_echec_interne()
        return _error(
            500,
            "ERREUR_INTERNE",
            (
                "Une erreur interne est survenue pendant l'analyse. Le fichier n'a pas "
                "été conservé."
            ),
        )
    finally:
        del raw

    METRIQUES.enregistrer_validation(
        report, plan=cle.plan if cle else apikeys.PLAN_ANONYME
    )
    return JSONResponse(content=report, headers=entetes)


# --------------------------------------------------------------------------
# Interface statique. Montee en dernier pour ne pas masquer /api.
# --------------------------------------------------------------------------

if config.STATIC_DIR.is_dir():
    # Monte a la racine, mais apres les routes /api, qui sont donc prioritaires.
    # html=True sert index.html pour la racine et pour les chemins inconnus.
    app.mount(
        "/",
        StaticFiles(directory=config.STATIC_DIR, html=True),
        name="interface",
    )
else:

    @app.get("/")
    def interface_absente() -> Any:
        return _error(
            503,
            "INTERFACE_ABSENTE",
            (
                "L'interface n'a pas ete construite. Executez npm run build dans "
                "frontend/, ou utilisez directement /api/validate."
            ),
        )
