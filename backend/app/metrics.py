"""Compteurs agreges du service.

Ce que ces compteurs servent a savoir : combien de factures sont analysees, quels
profils dominent dans le parc reel, quelle proportion de fichiers est non
conforme, et sur quelles regles les editeurs achoppent. Ce sont les chiffres qui
font l'argument commercial, et ils s'obtiennent sans conserver un seul fichier.

Ce qui n'est jamais compte : aucun nom de fichier, aucune empreinte de contenu,
aucune adresse, aucune donnee de facture. Uniquement des totaux par categorie
fermee.

Les compteurs vivent en memoire et repartent de zero a chaque demarrage
d'instance. Pour une serie historique, il faut les collecter periodiquement vers
un systeme de metriques.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any

# Bornes de l'histogramme de duree, en millisecondes.
_BORNES_MS = (10, 25, 50, 100, 250, 500, 1000, 3000)

# Nombre de logiciels emetteurs distincts suivis. Plafonne parce que la valeur
# vient du fichier depose : au-dela, les nouvelles valeurs sont regroupees.
_EMETTEURS_MAX = 500


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._demarre = time.time()
        self._validations = 0
        self._verdicts: Counter[str] = Counter()
        self._profils: Counter[str] = Counter()
        self._syntaxes: Counter[str] = Counter()
        self._entrees: Counter[str] = Counter()
        self._statuts_niveaux: Counter[str] = Counter()
        self._regles: Counter[str] = Counter()
        self._refus: Counter[str] = Counter()
        self._echecs_internes = 0
        self._duree_totale_ms = 0.0
        self._duree_max_ms = 0.0
        self._histogramme: Counter[str] = Counter()
        self._octets_totaux = 0
        self._plans: Counter[str] = Counter()
        # Logiciel emetteur declare par le fichier, croise avec le verdict. C'est la
        # statistique qui indique quels logiciels produisent des factures non
        # conformes : elle n'existe nulle part ailleurs.
        self._emetteurs: Counter[str] = Counter()
        self._emetteurs_non_conformes: Counter[str] = Counter()
        self._interets = 0

    # -- alimentation -------------------------------------------------------

    def enregistrer_validation(
        self, rapport: dict[str, Any], *, plan: str = "anonyme"
    ) -> None:
        """Alimente les compteurs a partir d'un rapport, sans rien en conserver.

        Le plan est compte, pas la cle : on veut connaitre la repartition entre
        usage public et usage sous contrat, pas suivre un client nommement.
        """
        verdict = str(rapport.get("verdict", {}).get("code") or "inconnu")
        document = rapport.get("document") or {}
        profil = (document.get("profile") or {}).get("code") or "aucun"
        syntaxe = document.get("syntax") or "aucune"
        entree = (rapport.get("input") or {}).get("kind") or "inconnue"
        duree = float((rapport.get("engine") or {}).get("durationMs") or 0.0)
        taille = int((rapport.get("input") or {}).get("sizeBytes") or 0)

        with self._lock:
            self._validations += 1
            self._verdicts[verdict] += 1
            self._profils[str(profil)] += 1
            self._syntaxes[str(syntaxe)] += 1
            self._entrees[str(entree)] += 1
            self._plans[str(plan)] += 1
            self._duree_totale_ms += duree
            self._compter_emetteur(document, verdict)
            self._duree_max_ms = max(self._duree_max_ms, duree)
            self._octets_totaux += taille
            self._histogramme[self._tranche(duree)] += 1

            for niveau in rapport.get("levels") or []:
                self._statuts_niveaux[f"{niveau.get('id')}:{niveau.get('status')}"] += 1

            # Les codes de regles sont des identifiants normalises, pas des donnees
            # de facture : les compter indique sur quoi les editeurs achoppent.
            for constat in rapport.get("findings") or []:
                if constat.get("severity") != "error":
                    continue
                code = constat.get("ruleId")
                if code:
                    self._regles[str(code)] += 1

    def enregistrer_refus(self, code: str) -> None:
        with self._lock:
            self._refus[code] += 1

    def enregistrer_echec_interne(self) -> None:
        with self._lock:
            self._echecs_internes += 1

    def enregistrer_interet(self) -> None:
        """Compte une demande de contact, sans rien retenir de son contenu."""
        with self._lock:
            self._interets += 1

    def _compter_emetteur(self, document: dict[str, Any], verdict: str) -> None:
        """Compte le logiciel emetteur, en bornant le nombre de valeurs suivies.

        La valeur vient du fichier depose : sans plafond, un appelant pourrait
        faire croitre ce compteur sans limite en variant la metadonnee a chaque
        envoi. Au-dela du plafond, les nouvelles valeurs sont regroupees.
        """
        emetteur = (document.get("producer") or {}).get("label")
        if not emetteur:
            return
        connu = emetteur in self._emetteurs
        if not connu and len(self._emetteurs) >= _EMETTEURS_MAX:
            emetteur = "autres"
        self._emetteurs[emetteur] += 1
        if verdict in {"non_conforme", "non_evaluable"}:
            self._emetteurs_non_conformes[emetteur] += 1

    @staticmethod
    def _tranche(duree_ms: float) -> str:
        for borne in _BORNES_MS:
            if duree_ms <= borne:
                return f"<= {borne} ms"
        return f"> {_BORNES_MS[-1]} ms"

    # -- lecture ------------------------------------------------------------

    def instantane(self, *, top_regles: int = 20) -> dict[str, Any]:
        with self._lock:
            duree_moyenne = (
                self._duree_totale_ms / self._validations if self._validations else 0.0
            )
            return {
                "startedAt": int(self._demarre),
                "uptimeSeconds": int(time.time() - self._demarre),
                "validations": {
                    "total": self._validations,
                    "byVerdict": dict(self._verdicts),
                    "byProfile": dict(self._profils),
                    "bySyntax": dict(self._syntaxes),
                    "byInputKind": dict(self._entrees),
                    "byPlan": dict(self._plans),
                },
                "levels": dict(self._statuts_niveaux),
                # La statistique commercialement decisive : quels logiciels
                # produisent des factures non conformes, et dans quelle proportion.
                "issuingSoftware": [
                    {
                        "label": libelle,
                        "total": nombre,
                        "nonConformant": self._emetteurs_non_conformes.get(libelle, 0),
                        "nonConformantRatio": round(
                            self._emetteurs_non_conformes.get(libelle, 0) / nombre, 3
                        )
                        if nombre
                        else 0.0,
                    }
                    for libelle, nombre in self._emetteurs.most_common(top_regles)
                ],
                "topFailedRules": [
                    {"ruleId": code, "count": nombre}
                    for code, nombre in self._regles.most_common(top_regles)
                ],
                "rejections": dict(self._refus),
                "internalFailures": self._echecs_internes,
                "leadRequests": self._interets,
                "duration": {
                    "meanMs": round(duree_moyenne, 1),
                    "maxMs": round(self._duree_max_ms, 1),
                    "histogram": dict(self._histogramme),
                },
                "volume": {
                    "totalBytes": self._octets_totaux,
                    "meanBytes": (
                        self._octets_totaux // self._validations
                        if self._validations
                        else 0
                    ),
                },
            }

    def reinitialiser(self) -> None:
        """Reservee aux tests."""
        with self._lock:
            self.__init__()  # type: ignore[misc]


METRIQUES = Metrics()
