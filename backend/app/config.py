"""Configuration du service. Tout est surchargeable par variable d'environnement."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Validateur Factur-X"
APP_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = "1.0"

BASE_DIR = Path(__file__).resolve().parent.parent
RESOURCES_DIR = Path(os.getenv("RESOURCES_DIR", BASE_DIR / "resources"))
STATIC_DIR = Path(os.getenv("STATIC_DIR", BASE_DIR / "static"))

# Taille maximale acceptee, en octets. Le fichier reste en memoire, jamais sur disque.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))

# Les regles France (CTC flux 2) sont chargees mais neutralisees par defaut :
# elles ciblent les echanges entre Plateformes Agreees et produiraient du bruit
# sur une facture examinee hors de ce contexte.
FRCTC_ENABLED = os.getenv("FRCTC_ENABLED", "0") == "1"

# Nombre maximum de constats remontes par niveau, pour eviter un rapport illisible
# sur un fichier tres degrade. La troncature est signalee explicitement.
MAX_FINDINGS_PER_LEVEL = int(os.getenv("MAX_FINDINGS_PER_LEVEL", 300))

# Precompilation des feuilles XSLT au demarrage. A laisser actif en production
# pour tenir la cible de moins de 3 secondes sur la premiere requete.
WARMUP_ON_STARTUP = os.getenv("WARMUP_ON_STARTUP", "1") == "1"

CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "").split(",") if o]

# --------------------------------------------------------------------------
# Limitation de debit
#
# Le service est gratuit et anonyme : rien n'identifie un appelant abusif, et
# chaque validation consomme du temps processeur Saxon serialise. Sans plafond,
# une seule source peut saturer une instance.
# --------------------------------------------------------------------------

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") == "1"
# Validations autorisees par minute et par appelant anonyme.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 20))
# Rafale toleree, pour ne pas penaliser un envoi de quelques fichiers d'affilee.
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", 8))
# Nombre d'appelants suivis simultanement. Plafonne pour borner la memoire : au
# dela, les entrees les plus anciennes sont oubliees.
RATE_LIMIT_MAX_TRACKED = int(os.getenv("RATE_LIMIT_MAX_TRACKED", 20000))

# Requetes de validation admises simultanement, en cours de traitement comme en
# attente. Les validations s'executent sur un fil unique, voir EXECUTEUR dans
# main.py : ce plafond borne donc la profondeur de la file. Au-dela, le service
# refuse tout de suite plutot que de laisser un appelant attendre jusqu'a
# expiration. A 30 millisecondes par validation, douze requetes admises
# representent au pire un peu plus d'un tiers de seconde d'attente.
MAX_CONCURRENT_VALIDATIONS = int(os.getenv("MAX_CONCURRENT_VALIDATIONS", 12))

# A activer derriere Cloud Run ou tout autre proxy de confiance, pour lire
# l'adresse de l'appelant dans X-Forwarded-For. Desactive, l'adresse du proxy
# serait prise pour celle du client et tous les appelants partageraient un
# meme plafond.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "0") == "1"

# --------------------------------------------------------------------------
# Metriques
#
# Volume, repartition des verdicts et des profils : ce sont des donnees
# commerciales. L'acces est donc ferme par defaut et n'est ouvert que si un jeton
# est configure.
# --------------------------------------------------------------------------

METRICS_TOKEN = os.getenv("METRICS_TOKEN", "")

# --------------------------------------------------------------------------
# Contact
#
# Sert a proposer l'acces par cle a un editeur qui en aurait besoin. Vide, aucune
# adresse n'est affichee : mieux vaut ne rien proposer que renvoyer vers une
# adresse qui n'existe pas.
# --------------------------------------------------------------------------

CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
CONTACT_URL = os.getenv("CONTACT_URL", "")

# --------------------------------------------------------------------------
# Manifestations d'interet
#
# Le visiteur peut demander a etre contacte. Le service ne stocke rien lui-meme :
# la demande est transmise a la destination configuree. Sans destination, la
# fonction est inactive et l'interface ne la propose pas, plutot que de recueillir
# une adresse sans savoir ou elle va.
#
# Duree de conservation annoncee au visiteur, en mois. Elle engage : la purge est a
# assurer dans le systeme de destination, pas ici.
# --------------------------------------------------------------------------

LEADS_WEBHOOK_URL = os.getenv("LEADS_WEBHOOK_URL", "")
LEADS_WEBHOOK_TOKEN = os.getenv("LEADS_WEBHOOK_TOKEN", "")
LEADS_VIA_REDIS = os.getenv("LEADS_VIA_REDIS", "0") == "1"
LEADS_TIMEOUT_SECONDS = float(os.getenv("LEADS_TIMEOUT_SECONDS", 5))
LEADS_RETENTION_MONTHS = int(os.getenv("LEADS_RETENTION_MONTHS", 24))
# Responsable du traitement, a annoncer au visiteur. Sans lui, la fonction reste
# inactive : on ne recueille pas de donnee personnelle sans dire qui la traite.
LEADS_CONTROLLER = os.getenv("LEADS_CONTROLLER", "")

# --------------------------------------------------------------------------
# Compteurs partages
#
# Sans compteur partage, les quotas repartent de zero a chaque redemarrage et les
# plafonds de debit sont locaux a l'instance. Renseigner REDIS_URL rend les deux
# communs a toutes les instances, ce qui est la condition pour facturer a l'usage.
# --------------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_TIMEOUT_SECONDS = float(os.getenv("REDIS_TIMEOUT_SECONDS", 1.5))

# --------------------------------------------------------------------------
# Audit PDF/A par veraPDF
#
# Desactive par defaut, et pour une raison mesuree : un appel coute environ
# 1,5 seconde, presque entierement du demarrage de JVM, contre 33 millisecondes
# pour tout le reste de la validation. Activer ce niveau multiplie donc le temps
# de reponse par cinquante. C'est un choix a faire en connaissance de cause.
#
# Le PDF est transmis par l'entree standard, jamais par un fichier : la promesse
# de ne rien ecrire sur disque est preservee.
# --------------------------------------------------------------------------

VERAPDF_ENABLED = os.getenv("VERAPDF_ENABLED", "0") == "1"
# Chemin du jar cli-<version>.jar de veraPDF.
VERAPDF_JAR = os.getenv("VERAPDF_JAR", "")
JAVA_BIN = os.getenv("JAVA_BIN", "java")
VERAPDF_TIMEOUT_SECONDS = int(os.getenv("VERAPDF_TIMEOUT_SECONDS", 25))
# Niveau applique quand la detection automatique par les metadonnees echoue.
VERAPDF_DEFAULT_FLAVOUR = os.getenv("VERAPDF_DEFAULT_FLAVOUR", "3b")
