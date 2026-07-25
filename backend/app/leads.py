"""Manifestations d'interet, sur demande explicite du visiteur.

L'outil est gratuit, sans compte et sans conservation du fichier. Cette couche ne
remet aucun de ces trois points en cause : elle n'existe que si le visiteur
demande lui-meme a etre contacte, et elle ne touche jamais au fichier depose.

Ce qui est transmis, et rien d'autre :

- l'adresse de courriel saisie par le visiteur ;
- le logiciel et le secteur qu'il declare, tous deux facultatifs ;
- des faits techniques sur la validation qui vient d'avoir lieu : verdict, profil,
  syntaxe, codes de regles en echec.

Ce qui n'est jamais transmis : le fichier, le nom du fichier, et toute donnee
figurant dans la facture. Ni le nom du vendeur, ni celui de l'acheteur, ni le
numero de facture, ni les montants. Ces informations appartiennent au visiteur et
a ses clients, pas a nous.

Le service ne stocke rien lui-meme. La manifestation d'interet est transmise a la
destination configuree, un point d'entree HTTP ou une file Redis. Sans destination
configuree, la fonction est inactive et l'interface ne la propose pas : mieux vaut
ne rien demander que recueillir une adresse sans savoir ou elle va.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import config, store

logger = logging.getLogger("facturx.interets")

# Volontairement permissif : le but est d'ecarter les saisies manifestement
# erronees, pas de decider a la place des serveurs de messagerie ce qui existe.
_COURRIEL = re.compile(r"^[^@\s]{1,64}@[^@\s.]{1,63}(\.[^@\s.]{1,63})+$")

LONGUEUR_MAX = 200
CLE_FILE_REDIS = "fxv:interets"


class Refus(ValueError):
    """La demande est irrecevable, avec un motif destine au visiteur."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Interet:
    courriel: str
    consentement: bool
    logiciel: str | None = None
    secteur: str | None = None
    volume_mensuel: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)

    def charge_utile(self) -> dict[str, Any]:
        return {
            "source": "validateur-facturx",
            "recuLe": datetime.now(UTC).isoformat(timespec="seconds"),
            "courriel": self.courriel,
            "consentementContact": self.consentement,
            "logiciel": self.logiciel,
            "secteur": self.secteur,
            "volumeMensuel": self.volume_mensuel,
            "validation": self.validation,
        }


def _propre(valeur: object) -> str | None:
    if valeur is None:
        return None
    texte = " ".join(str(valeur).split())
    texte = "".join(c for c in texte if c.isprintable()).strip()
    return texte[:LONGUEUR_MAX] or None


def active() -> bool:
    """La fonction n'est proposee que si tout est en place pour le faire loyalement.

    Deux conditions, et les deux sont necessaires. Une destination, sans quoi on
    recueillerait une adresse sans savoir ou elle va. Et un responsable de
    traitement identifie, sans quoi le visiteur ne saurait pas a qui il confie son
    adresse ni a qui reclamer son effacement.
    """
    destination = bool(config.LEADS_WEBHOOK_URL) or (
        config.LEADS_VIA_REDIS and store.COMPTEUR.partage
    )
    return destination and bool(config.LEADS_CONTROLLER)


def mentions() -> dict[str, Any]:
    """Informations dues au visiteur avant qu'il saisisse son adresse."""
    return {
        "enabled": active(),
        "controller": config.LEADS_CONTROLLER or None,
        "purpose": (
            "Vous recontacter au sujet de la validation de vos factures "
            "électroniques, et de rien d'autre."
        ),
        "legalBasis": "votre consentement, que vous pouvez retirer à tout moment",
        "retentionMonths": config.LEADS_RETENTION_MONTHS,
        "collected": [
            "votre adresse de courriel",
            "le logiciel, le secteur et le volume que vous déclarez, facultatifs",
            "le verdict de la validation et les codes de règles en échec",
        ],
        "neverCollected": [
            "le fichier déposé, qui n'est ni conservé ni transmis",
            "son nom",
            "toute donnée figurant dans la facture, y compris les noms du vendeur "
            "et de l'acheteur, le numéro de facture et les montants",
        ],
        "rights": (
            "Vous pouvez demander l'accès, la rectification ou l'effacement de vos "
            "données en écrivant au responsable indiqué."
        ),
    }


def construire(charge: dict[str, Any], rapport: dict[str, Any] | None) -> Interet:
    """Valide la demande et n'en retient que ce qui est autorise."""
    courriel = _propre(charge.get("email"))
    if not courriel or not _COURRIEL.match(courriel):
        raise Refus("COURRIEL_INVALIDE", "L'adresse de courriel n'est pas exploitable.")

    if charge.get("consent") is not True:
        raise Refus(
            "CONSENTEMENT_REQUIS",
            "Votre accord explicite est nécessaire pour être contacté.",
        )

    interet = Interet(
        courriel=courriel,
        consentement=True,
        logiciel=_propre(charge.get("software")),
        secteur=_propre(charge.get("sector")),
        volume_mensuel=_propre(charge.get("monthlyVolume")),
    )

    if rapport:
        interet.validation = _faits_de_validation(rapport)
    return interet


def _faits_de_validation(rapport: dict[str, Any]) -> dict[str, Any]:
    """Extrait du rapport les seuls faits techniques autorises.

    Construit par liste blanche et non par exclusion : une future cle du rapport
    contenant une donnee de facture ne se retrouverait pas transmise par oubli.
    """
    document = rapport.get("document") or {}
    codes = [
        constat.get("ruleId")
        for constat in (rapport.get("findings") or [])
        if constat.get("severity") == "error" and constat.get("ruleId")
    ]
    return {
        "verdict": (rapport.get("verdict") or {}).get("code"),
        "profil": (document.get("profile") or {}).get("code"),
        "syntaxe": document.get("syntax"),
        "codesEnEchec": codes[:25],
        # Logiciel declare par le fichier lui-meme, metadonnee technique.
        "logicielDeclare": (document.get("producer") or {}).get("label"),
    }


def transmettre(interet: Interet) -> None:
    """Achemine la manifestation d'interet vers la destination configuree."""
    charge = interet.charge_utile()

    if config.LEADS_WEBHOOK_URL:
        _poster(config.LEADS_WEBHOOK_URL, charge)
        return

    if config.LEADS_VIA_REDIS and store.COMPTEUR.partage:
        _empiler(charge)
        return

    raise Refus(
        "DESTINATION_ABSENTE",
        "La demande de contact n'est pas ouverte sur cette instance.",
    )


def _poster(url: str, charge: dict[str, Any]) -> None:
    requete = urllib.request.Request(
        url,
        data=json.dumps(charge, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    if config.LEADS_WEBHOOK_TOKEN:
        requete.add_header("Authorization", f"Bearer {config.LEADS_WEBHOOK_TOKEN}")
    try:
        with urllib.request.urlopen(requete, timeout=config.LEADS_TIMEOUT_SECONDS) as r:
            if r.status >= 300:
                raise Refus("DESTINATION_EN_ECHEC", "La demande n'a pas pu être transmise.")
    except urllib.error.HTTPError as exc:
        # Le detail de l'erreur distante n'a pas a remonter au visiteur.
        logger.error("destination des interets en echec : %s %s", exc.code, exc.reason)
        raise Refus(
            "DESTINATION_EN_ECHEC", "La demande n'a pas pu être transmise. Réessayez."
        ) from exc
    except Exception as exc:
        logger.error("destination des interets injoignable : %s", exc)
        raise Refus(
            "DESTINATION_EN_ECHEC", "La demande n'a pas pu être transmise. Réessayez."
        ) from exc


def _empiler(charge: dict[str, Any]) -> None:
    """Depose la demande dans une file Redis, a relever par ailleurs."""
    try:
        client = store.COMPTEUR._client  # noqa: SLF001
        client.rpush(CLE_FILE_REDIS, json.dumps(charge, ensure_ascii=False))
    except Exception as exc:
        logger.error("file des interets indisponible : %s", exc)
        raise Refus(
            "DESTINATION_EN_ECHEC", "La demande n'a pas pu être transmise. Réessayez."
        ) from exc
