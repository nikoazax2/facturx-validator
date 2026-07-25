"""Compteurs, en memoire ou partages.

Deux faiblesses documentees se resolvent au meme endroit.

Les quotas mensuels tenus en memoire repartent de zero a chaque redemarrage
d'instance : suffisant pour brider un usage, insuffisant pour facturer. Les
plafonds de debit tenus en memoire sont locaux a l'instance : avec dix instances,
le plafond effectif est multiplie par dix.

Un compteur partage regle les deux. L'interface reste minimale, incrementer et
lire, afin qu'un autre adossement, Firestore ou une table, se substitue sans
toucher au reste du code.

Choix a expliciter : en cas d'indisponibilite du compteur partage, le service
laisse passer plutot que de refuser. Bloquer un client sous contrat parce que
notre compteur est tombe serait plus dommageable qu'un bref depassement, et le
seau a jetons local continue de proteger l'instance. L'incident est journalise et
visible dans l'etat de sante.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Protocol

from . import config

logger = logging.getLogger("facturx.compteurs")

# Duree de vie des cles de quota : un peu plus qu'un mois, pour couvrir la
# consultation d'un mois qui vient de se terminer.
TTL_QUOTA_SECONDES = 40 * 24 * 3600
# Duree de vie des cles de debit : deux fenetres, le temps que la suivante prenne
# le relais.
TTL_DEBIT_SECONDES = 120


def periode_mensuelle(maintenant: datetime | None = None) -> str:
    instant = maintenant or datetime.now(UTC)
    return f"{instant.year:04d}-{instant.month:02d}"


def fenetre_minute(maintenant: datetime | None = None) -> str:
    instant = maintenant or datetime.now(UTC)
    return instant.strftime("%Y%m%d%H%M")


def cle_quota(identifiant: str, periode: str) -> str:
    return f"fxv:quota:{identifiant}:{periode}"


def cle_debit(portee: str, fenetre: str) -> str:
    return f"fxv:debit:{portee}:{fenetre}"


class Compteur(Protocol):
    """Contrat minimal attendu d'un compteur."""

    @property
    def partage(self) -> bool:
        """Vrai si le compteur est commun a toutes les instances."""

    def incrementer(self, cle: str, ttl_secondes: int) -> int | None:
        """Incremente et retourne la valeur, ou None si le compteur est indisponible."""

    def lire(self, cle: str) -> int | None:
        """Retourne la valeur, ou None si le compteur est indisponible."""

    def sante(self) -> dict[str, object]:
        """Etat, expose par l'API de sante."""

    def reinitialiser(self) -> None:
        """Reservee aux tests."""


class CompteurMemoire:
    """Compteur local au processus, avec peremption et taille bornee."""

    def __init__(self, max_cles: int = 100_000) -> None:
        self._valeurs: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._max_cles = max(max_cles, 1)
        self._lock = threading.Lock()

    @property
    def partage(self) -> bool:
        return False

    def _purger(self, maintenant: float) -> None:
        perimees = [
            cle for cle, (_, echeance) in self._valeurs.items() if echeance <= maintenant
        ]
        for cle in perimees:
            del self._valeurs[cle]
        while len(self._valeurs) > self._max_cles:
            self._valeurs.popitem(last=False)

    def incrementer(self, cle: str, ttl_secondes: int) -> int:
        maintenant = time.monotonic()
        with self._lock:
            valeur, echeance = self._valeurs.get(cle, (0, 0.0))
            if echeance <= maintenant:
                valeur, echeance = 0, maintenant + ttl_secondes
            valeur += 1
            self._valeurs[cle] = (valeur, echeance)
            self._valeurs.move_to_end(cle)
            # La purge vient apres l'insertion : la faire avant laisserait le
            # nombre de cles depasser la borne de un, a chaque appel.
            self._purger(maintenant)
            return valeur

    def lire(self, cle: str) -> int:
        maintenant = time.monotonic()
        with self._lock:
            valeur, echeance = self._valeurs.get(cle, (0, 0.0))
            return valeur if echeance > maintenant else 0

    def sante(self) -> dict[str, object]:
        with self._lock:
            return {"type": "memoire", "shared": False, "keys": len(self._valeurs)}

    def reinitialiser(self) -> None:
        with self._lock:
            self._valeurs.clear()


class CompteurRedis:
    """Compteur partage, adosse a Redis.

    L'increment et la pose de peremption sont groupes dans un pipeline : la cle ne
    peut pas rester sans peremption si le processus s'interrompt entre les deux
    ordres, ce qui la ferait vivre indefiniment.
    """

    def __init__(self, url: str) -> None:
        import redis  # importe seulement si un compteur partage est demande

        self._client = redis.Redis.from_url(
            url,
            socket_timeout=config.REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=config.REDIS_TIMEOUT_SECONDS,
            decode_responses=True,
        )
        self._url_masquee = _masquer(url)
        self._indisponible_depuis: float | None = None
        self._echecs = 0

    @property
    def partage(self) -> bool:
        return True

    def _signaler(self, exc: Exception) -> None:
        self._echecs += 1
        if self._indisponible_depuis is None:
            self._indisponible_depuis = time.time()
            logger.warning("compteur partage indisponible : %s", exc)

    def _retablir(self) -> None:
        if self._indisponible_depuis is not None:
            logger.info("compteur partage de nouveau disponible")
            self._indisponible_depuis = None

    def incrementer(self, cle: str, ttl_secondes: int) -> int | None:
        try:
            pipeline = self._client.pipeline()
            pipeline.incr(cle)
            pipeline.expire(cle, ttl_secondes, nx=True)
            valeur = pipeline.execute()[0]
        except Exception as exc:  # redis.RedisError et erreurs reseau
            self._signaler(exc)
            return None
        self._retablir()
        return int(valeur)

    def lire(self, cle: str) -> int | None:
        try:
            valeur = self._client.get(cle)
        except Exception as exc:
            self._signaler(exc)
            return None
        self._retablir()
        return int(valeur or 0)

    def verifier(self) -> str | None:
        """Teste la connexion. Retourne un message d'erreur, ou None si tout va bien."""
        try:
            self._client.ping()
        except Exception as exc:
            self._signaler(exc)
            return str(exc)
        self._retablir()
        return None

    def sante(self) -> dict[str, object]:
        return {
            "type": "redis",
            "shared": True,
            "target": self._url_masquee,
            "available": self._indisponible_depuis is None,
            "failures": self._echecs,
        }

    def reinitialiser(self) -> None:
        try:
            for cle in self._client.scan_iter(match="fxv:*", count=500):
                self._client.delete(cle)
        except Exception as exc:
            logger.warning("purge du compteur partage impossible : %s", exc)


def _masquer(url: str) -> str:
    """Retire tout secret d'une URL avant de l'exposer."""
    if "@" not in url:
        return url
    debut, _, fin = url.rpartition("@")
    schema, separateur, _identifiants = debut.partition("://")
    return f"{schema}{separateur}***@{fin}" if separateur else f"***@{fin}"


def construire(url: str | None) -> tuple[Compteur, str | None]:
    """Retourne le compteur a utiliser, et un message si le partage a echoue."""
    if not url:
        return CompteurMemoire(), None
    try:
        compteur = CompteurRedis(url)
    except ImportError:
        return (
            CompteurMemoire(),
            "le paquet redis n'est pas installé : compteurs en mémoire",
        )
    except Exception as exc:
        return CompteurMemoire(), f"compteur partagé inutilisable : {exc}"

    erreur = compteur.verifier()
    if erreur:
        # Un Redis injoignable au demarrage n'empeche pas le service de tourner :
        # on repart sur la memoire, et l'etat de sante le dit.
        return CompteurMemoire(), f"compteur partagé injoignable : {erreur}"
    return compteur, None


COMPTEUR: Compteur = CompteurMemoire()
ERREUR_COMPTEUR: str | None = None


def initialiser() -> str | None:
    """Installe le compteur configure. Retourne un message d'erreur eventuel."""
    global COMPTEUR, ERREUR_COMPTEUR
    COMPTEUR, ERREUR_COMPTEUR = construire(config.REDIS_URL)
    if ERREUR_COMPTEUR:
        logger.warning("%s", ERREUR_COMPTEUR)
    elif COMPTEUR.partage:
        logger.info("compteurs partagés actifs")
    return ERREUR_COMPTEUR
