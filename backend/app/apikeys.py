"""Acces par cle, pour les editeurs qui integrent la validation.

L'outil public sert de vitrine : un editeur y depose un fichier a la main. Celui
qui veut valider un lot ou brancher la validation sur son integration continue a
besoin d'autre chose, et c'est ce que cette couche fournit : une cle, un plafond
propre, un quota, et de quoi suivre sa consommation.

Deux principes de securite.

Les cles ne sont jamais stockees en clair. La configuration porte l'empreinte
SHA-256 de chaque cle. Une cle en clair peut etre fournie pour un usage local,
elle est alors hachee au chargement et la valeur d'origine n'est pas conservee.
Utilisez `python scripts/make_api_key.py` pour produire un couple cle et
empreinte.

La comparaison se fait a temps constant, pour ne pas laisser deviner une cle
valide en mesurant le temps de reponse.

Le decompte des quotas est delegue au compteur configure, voir `store.py`. Sans
compteur partage, il repart de zero a chaque redemarrage d'instance : suffisant
pour brider un usage, insuffisant pour facturer. Avec REDIS_URL renseigne, le
decompte devient commun a toutes les instances et persiste, ce qui est la
condition pour facturer a l'usage. L'etat du compteur est annonce dans la reponse
de `/api/key` plutot que laisse a deviner.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from . import store

logger = logging.getLogger("facturx.cles")

PREFIXE_CLE = "fxv_"

# Plans proposes. Les valeurs sont des defauts : chaque cle peut les surcharger.
PLANS: dict[str, dict[str, int | str]] = {
    "essai": {
        "label": "Essai",
        "perMinute": 60,
        "perMonth": 500,
        "description": "Découverte et tests d'intégration.",
    },
    "integration": {
        "label": "Intégration",
        "perMinute": 120,
        "perMonth": 50_000,
        "description": "Validation en continu dans une chaîne de production.",
    },
    "volume": {
        "label": "Volume",
        "perMinute": 600,
        "perMonth": 1_000_000,
        "description": "Validation de masse, reprise de parc, plateformes.",
    },
}

PLAN_ANONYME = "anonyme"


def hacher(cle: str) -> str:
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()


def generer_cle() -> tuple[str, str]:
    """Retourne (cle en clair, empreinte). La cle n'est affichee qu'une fois."""
    cle = PREFIXE_CLE + secrets.token_urlsafe(32)
    return cle, hacher(cle)


@dataclass
class CleApi:
    identifiant: str
    libelle: str
    plan: str
    empreinte: str
    par_minute: int
    par_mois: int
    expire_le: date | None = None

    def expiree(self, *, aujourd_hui: date | None = None) -> bool:
        if self.expire_le is None:
            return False
        return (aujourd_hui or datetime.now(UTC).date()) > self.expire_le

    def publique(self) -> dict[str, object]:
        """Vue sans secret, remise a l'integrateur."""
        return {
            "keyId": self.identifiant,
            "label": self.libelle,
            "plan": self.plan,
            "planLabel": PLANS.get(self.plan, {}).get("label", self.plan),
            "perMinute": self.par_minute,
            "perMonth": self.par_mois,
            "expiresOn": self.expire_le.isoformat() if self.expire_le else None,
        }


class ConfigurationInvalide(ValueError):
    """La declaration des cles est inexploitable."""


class Registre:
    """Cles chargees en memoire, indexees par empreinte."""

    def __init__(self) -> None:
        self._par_empreinte: dict[str, CleApi] = {}
        self._lock = threading.Lock()

    # -- chargement ---------------------------------------------------------

    def charger(self, declaration: str | None) -> None:
        """Charge les cles depuis une declaration JSON.

        Format attendu, une liste d'objets :

            [{"id": "acme", "label": "ACME Logiciels", "plan": "integration",
              "keyHash": "…"}]

        `key` est accepte a la place de `keyHash` pour un usage local : la cle est
        alors hachee immediatement et la valeur en clair n'est pas conservee.
        """
        self._par_empreinte.clear()
        if not declaration or not declaration.strip():
            return

        try:
            entrees = json.loads(declaration)
        except json.JSONDecodeError as exc:
            raise ConfigurationInvalide(
                f"API_KEYS n'est pas un JSON valide : {exc}"
            ) from exc
        if not isinstance(entrees, list):
            raise ConfigurationInvalide("API_KEYS doit être une liste d'objets.")

        for position, entree in enumerate(entrees, start=1):
            if not isinstance(entree, dict):
                raise ConfigurationInvalide(f"API_KEYS, entrée {position} : objet attendu.")
            cle = self._construire(entree, position)
            if cle.empreinte in self._par_empreinte:
                raise ConfigurationInvalide(
                    f"API_KEYS, entrée {position} : empreinte déjà déclarée."
                )
            self._par_empreinte[cle.empreinte] = cle

        logger.info("%d cle(s) d'API chargee(s)", len(self._par_empreinte))

    def _construire(self, entree: dict, position: int) -> CleApi:
        identifiant = str(entree.get("id") or "").strip()
        if not identifiant:
            raise ConfigurationInvalide(f"API_KEYS, entrée {position} : « id » manquant.")

        plan = str(entree.get("plan") or "essai")
        if plan not in PLANS:
            raise ConfigurationInvalide(
                f"API_KEYS, entrée {position} : plan « {plan} » inconnu. "
                f"Plans disponibles : {', '.join(PLANS)}."
            )
        defauts = PLANS[plan]

        empreinte = str(entree.get("keyHash") or "").strip().lower()
        if not empreinte:
            en_clair = str(entree.get("key") or "").strip()
            if not en_clair:
                raise ConfigurationInvalide(
                    f"API_KEYS, entrée {position} : « keyHash » ou « key » requis."
                )
            empreinte = hacher(en_clair)
        if len(empreinte) != 64 or any(c not in "0123456789abcdef" for c in empreinte):
            raise ConfigurationInvalide(
                f"API_KEYS, entrée {position} : empreinte SHA-256 attendue, "
                "64 caractères hexadécimaux."
            )

        expire_le = None
        brut = entree.get("expires")
        if brut:
            try:
                expire_le = date.fromisoformat(str(brut))
            except ValueError as exc:
                raise ConfigurationInvalide(
                    f"API_KEYS, entrée {position} : date « {brut} » invalide, "
                    "format attendu AAAA-MM-JJ."
                ) from exc

        return CleApi(
            identifiant=identifiant,
            libelle=str(entree.get("label") or identifiant),
            plan=plan,
            empreinte=empreinte,
            par_minute=int(entree.get("perMinute") or defauts["perMinute"]),
            par_mois=int(entree.get("perMonth") or defauts["perMonth"]),
            expire_le=expire_le,
        )

    # -- authentification ---------------------------------------------------

    @property
    def actif(self) -> bool:
        return bool(self._par_empreinte)

    def resoudre(self, cle_presentee: str | None) -> CleApi | None:
        """Retourne la cle correspondante, ou None si aucune ne correspond."""
        if not cle_presentee:
            return None
        # La recherche par empreinte est deja a temps constant vis-a-vis de la cle
        # elle-meme : on ne compare jamais la valeur presentee a un secret stocke.
        return self._par_empreinte.get(hacher(cle_presentee.strip()))

    # -- quota --------------------------------------------------------------
    #
    # Le decompte est delegue au compteur configure. En memoire, il repart de zero
    # a chaque redemarrage ; partage, il fait foi pour toutes les instances.

    @staticmethod
    def _periode(maintenant: datetime | None = None) -> str:
        return store.periode_mensuelle(maintenant)

    def consommer(
        self, cle: CleApi, *, maintenant: datetime | None = None
    ) -> tuple[bool, int]:
        """Decompte une validation. Retourne (autorise, solde restant)."""
        periode = self._periode(maintenant)
        identifiant = store.cle_quota(cle.identifiant, periode)
        valeur = store.COMPTEUR.incrementer(identifiant, store.TTL_QUOTA_SECONDES)

        if valeur is None:
            # Compteur indisponible : on laisse passer plutot que de bloquer un
            # client sous contrat pour une panne qui ne lui est pas imputable.
            logger.warning(
                "quota non decompte pour %s : compteur indisponible", cle.identifiant
            )
            return True, cle.par_mois

        if valeur > cle.par_mois:
            return False, 0
        return True, cle.par_mois - valeur

    def consommation(self, cle: CleApi, *, maintenant: datetime | None = None) -> int:
        periode = self._periode(maintenant)
        valeur = store.COMPTEUR.lire(store.cle_quota(cle.identifiant, periode))
        return valeur or 0

    def etat_public(self, cle: CleApi) -> dict[str, object]:
        utilise = self.consommation(cle)
        partage = store.COMPTEUR.partage
        vue = cle.publique()
        vue["usage"] = {
            "period": self._periode(),
            "used": utilise,
            "remaining": max(0, cle.par_mois - utilise),
            "shared": partage,
            "note": (
                "Compteur partagé entre toutes les instances et persistant."
                if partage
                else (
                    "Compteur en mémoire, remis à zéro au redémarrage de l'instance. "
                    "Il ne fait pas foi pour une facturation : renseignez REDIS_URL "
                    "pour un décompte partagé."
                )
            ),
        }
        return vue

    def inventaire(self) -> list[dict[str, object]]:
        """Vue d'ensemble sans secret, pour l'exploitation."""
        with self._lock:
            cles = list(self._par_empreinte.values())
        return [self.etat_public(cle) for cle in cles]

    def reinitialiser(self) -> None:
        """Reservee aux tests."""
        store.COMPTEUR.reinitialiser()


REGISTRE = Registre()


def charger_depuis_environnement() -> str | None:
    """Charge les cles et retourne un message d'erreur en cas d'echec."""
    try:
        REGISTRE.charger(os.getenv("API_KEYS"))
    except ConfigurationInvalide as exc:
        logger.error("cles d'API non chargees : %s", exc)
        return str(exc)
    return None
