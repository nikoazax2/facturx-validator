"""Limitation de debit et garde-fou de concurrence.

Trois protections distinctes, qui ne repondent pas au meme risque.

Le seau a jetons local empeche une source unique de monopoliser une instance. Le
plafond de debit partage fait respecter la meme limite a l'echelle du service, ce
que le seau local ne peut pas savoir faire. Le garde-fou de concurrence borne
enfin la file d'attente : les validations s'executant sur un fil unique, accepter
sans limite ne ferait qu'allonger des attentes vouees a expirer.

Note sur la confidentialite. Aucune adresse IP n'est conservee. L'adresse sert a
calculer une empreinte tronquee, avec un sel aleatoire tire au demarrage du
processus : l'empreinte ne permet pas de remonter a l'adresse, et le sel disparait
avec le processus. C'est suffisant pour compter, insuffisant pour tracer.

Note sur Cloud Run. Sans compteur partage, la limitation reste locale a
l'instance et le plafond effectif est multiplie par leur nombre. Renseigner
REDIS_URL suffit a rendre le plafond global.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from . import config

# Sel tire une fois par processus, jamais journalise ni expose.
_SALT = os.urandom(16)


def client_fingerprint(remote_addr: str | None, forwarded_for: str | None) -> str:
    """Empreinte courte et non reversible de l'appelant."""
    adresse = remote_addr or "inconnue"
    if config.TRUST_PROXY_HEADERS and forwarded_for:
        # X-Forwarded-For liste les adresses de la plus proche du client a la plus
        # proche du serveur. Cloud Run place l'adresse du client en tete.
        premiere = forwarded_for.split(",")[0].strip()
        if premiere:
            adresse = premiere
    digest = hashlib.blake2b(_SALT + adresse.encode("utf-8"), digest_size=8)
    return digest.hexdigest()


@dataclass
class _Seau:
    jetons: float
    dernier: float


class RateLimiter:
    """Seau a jetons par appelant, avec eviction des entrees les plus anciennes."""

    def __init__(
        self,
        *,
        per_minute: int,
        burst: int,
        max_tracked: int,
    ) -> None:
        self._par_minute = per_minute
        self._debit = per_minute / 60.0
        self._capacite = float(max(burst, 1))
        self._max_tracked = max(max_tracked, 1)
        self._seaux: OrderedDict[str, _Seau] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def debit_par_minute(self) -> int:
        """Plafond configure, pour detecter un changement de plan a chaud."""
        return self._par_minute

    def autorise(self, cle: str, *, maintenant: float | None = None) -> tuple[bool, float]:
        """Retourne (autorise, secondes a attendre si refuse)."""
        instant = maintenant if maintenant is not None else time.monotonic()
        with self._lock:
            seau = self._seaux.get(cle)
            if seau is None:
                seau = _Seau(jetons=self._capacite, dernier=instant)
                self._seaux[cle] = seau
            else:
                self._seaux.move_to_end(cle)
                ecoule = max(0.0, instant - seau.dernier)
                seau.jetons = min(self._capacite, seau.jetons + ecoule * self._debit)
                seau.dernier = instant

            if seau.jetons >= 1.0:
                seau.jetons -= 1.0
                autorise = True
                attente = 0.0
            else:
                autorise = False
                manque = 1.0 - seau.jetons
                attente = manque / self._debit if self._debit > 0 else 60.0

            while len(self._seaux) > self._max_tracked:
                self._seaux.popitem(last=False)

            return autorise, attente

    @property
    def suivis(self) -> int:
        with self._lock:
            return len(self._seaux)

    def reinitialiser(self) -> None:
        with self._lock:
            self._seaux.clear()


class ConcurrencyGuard:
    """Plafond de requetes de validation admises, en traitement comme en attente.

    Les validations s'executent sur un fil unique : ce plafond borne donc la
    profondeur de la file. Un refus immediat vaut mieux qu'une attente longue :
    l'appelant sait a quoi s'en tenir et peut reessayer, au lieu de voir sa
    requete expirer sans explication.
    """

    def __init__(self, maximum: int) -> None:
        self._maximum = max(maximum, 1)
        self._en_cours = 0
        self._sommet = 0
        self._lock = threading.Lock()

    def __enter__(self) -> "ConcurrencyGuard":
        with self._lock:
            if self._en_cours >= self._maximum:
                raise Saturated(self._maximum)
            self._en_cours += 1
            self._sommet = max(self._sommet, self._en_cours)
        return self

    def __exit__(self, *_exc: object) -> None:
        with self._lock:
            self._en_cours -= 1

    @property
    def etat(self) -> dict[str, int]:
        with self._lock:
            return {
                "enCours": self._en_cours,
                "maximum": self._maximum,
                "sommetObserve": self._sommet,
            }


class Saturated(RuntimeError):
    """Le plafond de requetes admises est atteint."""

    def __init__(self, maximum: int) -> None:
        super().__init__(f"{maximum} requetes de validation admises au maximum")
        self.maximum = maximum


def debit_partage_depasse(portee: str, plafond_par_minute: int) -> bool:
    """Plafond de debit commun a toutes les instances.

    Complete le seau a jetons local, qui protege une instance mais ne sait rien
    des autres. La fenetre est fixe, a la minute : moins souple qu'un seau a
    jetons, mais realisable en un seul aller-retour et suffisant pour un plafond
    global.

    Retourne False quand le compteur est indisponible : le seau local reste en
    place, et une panne de compteur ne doit pas fermer le service.
    """
    from . import store

    if not store.COMPTEUR.partage:
        return False
    valeur = store.COMPTEUR.incrementer(
        store.cle_debit(portee, store.fenetre_minute()),
        store.TTL_DEBIT_SECONDES,
    )
    return valeur is not None and valeur > plafond_par_minute


LIMITEUR = RateLimiter(
    per_minute=config.RATE_LIMIT_PER_MINUTE,
    burst=config.RATE_LIMIT_BURST,
    max_tracked=config.RATE_LIMIT_MAX_TRACKED,
)
CONCURRENCE = ConcurrencyGuard(config.MAX_CONCURRENT_VALIDATIONS)
