"""Audit de conformite PDF/A par veraPDF.

Les controles PDF/A menes par `engine/pdf.py` portent sur les marqueurs et leur
coherence. Ils ne disent pas si le fichier est reellement conforme a
ISO 19005-3 : cela demande un validateur dedie, et veraPDF est l'implementation
de reference.

Deux points de conception meritent d'etre explicites.

Le PDF est transmis par l'entree standard, jamais par un fichier temporaire.
veraPDF accepte ce mode, ce qui permet de tenir la promesse de ne rien ecrire sur
disque. Le rapport designe alors la source par « STDIN » et annonce une taille de
-1 : c'est normal et sans consequence sur la validation.

Le cout est reel et c'est pourquoi ce niveau est desactive par defaut. Un appel
demande environ une seconde et demie, presque entierement du demarrage de machine
virtuelle Java, contre quelques dizaines de millisecondes pour tout le reste de la
validation. Pour un service qui aurait besoin de cet audit en permanence, la bonne
reponse n'est pas d'appeler un processus a chaque requete mais de maintenir un
service veraPDF chaud a cote, ce que permet son interface REST.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .. import config

logger = logging.getLogger("facturx.verapdf")

# Reglages de demarrage de la machine virtuelle. Sur une execution unique et
# courte, la compilation optimisante ne sert a rien : la limiter au premier
# niveau fait gagner environ un tiers du temps total, mesure sur ce cas d'usage.
_OPTIONS_JVM = (
    "-XX:TieredStopAtLevel=1",
    "-XX:+UseSerialGC",
    "-Xshare:auto",
)


@dataclass
class Echec:
    specification: str | None
    clause: str | None
    test: str | None
    description: str
    contexte: str | None
    controles_en_echec: int = 0

    @property
    def code(self) -> str:
        """Code lisible, du type PDFA-6.6.2.1-1."""
        morceaux = [element for element in ("PDFA", self.clause, self.test) if element]
        return "-".join(morceaux)


@dataclass
class Resultat:
    disponible: bool
    conforme: bool | None = None
    profil: str | None = None
    regles_passees: int = 0
    regles_en_echec: int = 0
    controles_passes: int = 0
    controles_en_echec: int = 0
    echecs: list[Echec] = field(default_factory=list)
    duree_ms: float = 0.0
    # Renseigne quand l'audit n'a pas pu aboutir : le rapport doit alors declarer
    # le niveau comme non execute, jamais comme reussi.
    erreur: str | None = None


def configure() -> tuple[bool, str | None]:
    """Indique si l'audit est utilisable, et sinon pourquoi."""
    if not config.VERAPDF_ENABLED:
        return False, "audit PDF/A désactivé (VERAPDF_ENABLED)"
    if not config.VERAPDF_JAR:
        return False, "VERAPDF_JAR n'est pas renseigné"
    if not Path(config.VERAPDF_JAR).is_file():
        return False, f"jar veraPDF introuvable : {config.VERAPDF_JAR}"
    return True, None


def auditer(raw: bytes) -> Resultat:
    """Soumet le PDF a veraPDF et retourne son verdict."""
    utilisable, motif = configure()
    if not utilisable:
        return Resultat(disponible=False, erreur=motif)

    commande = [
        config.JAVA_BIN,
        *_OPTIONS_JVM,
        "-jar",
        config.VERAPDF_JAR,
        "--format",
        "xml",
        # Sans argument de fichier, veraPDF lit l'entree standard.
        "--defaultflavour",
        config.VERAPDF_DEFAULT_FLAVOUR,
    ]

    debut = time.perf_counter()
    try:
        acheve = subprocess.run(
            commande,
            input=raw,
            capture_output=True,
            timeout=config.VERAPDF_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return Resultat(
            disponible=False,
            erreur=f"exécutable Java introuvable : {config.JAVA_BIN}",
        )
    except subprocess.TimeoutExpired:
        return Resultat(
            disponible=True,
            erreur=(
                f"veraPDF n'a pas répondu en moins de "
                f"{config.VERAPDF_TIMEOUT_SECONDS} secondes"
            ),
            duree_ms=round((time.perf_counter() - debut) * 1000, 1),
        )

    duree = round((time.perf_counter() - debut) * 1000, 1)
    sortie = _extraire_xml(acheve.stdout)
    if sortie is None:
        detail = (acheve.stderr or b"").decode("utf-8", errors="replace").strip()
        logger.warning("sortie veraPDF inexploitable : %s", detail[:300])
        return Resultat(
            disponible=True,
            erreur="la sortie de veraPDF n'a pas pu être analysée",
            duree_ms=duree,
        )

    try:
        return _lire_rapport(sortie, duree)
    except etree.XMLSyntaxError as exc:
        return Resultat(
            disponible=True,
            erreur=f"rapport veraPDF illisible : {exc}",
            duree_ms=duree,
        )


def _extraire_xml(sortie: bytes) -> bytes | None:
    """Isole le document XML au sein de la sortie.

    veraPDF fait parfois preceder son rapport d'un message d'aide lorsqu'il lit
    l'entree standard. On repart donc de la premiere balise, au lieu de supposer
    que la sortie commence par du XML.
    """
    if not sortie:
        return None
    for marqueur in (b"<?xml", b"<report"):
        position = sortie.find(marqueur)
        if position != -1:
            return sortie[position:]
    return None


def _lire_rapport(sortie: bytes, duree_ms: float) -> Resultat:
    racine = etree.fromstring(
        sortie,
        parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False),
    )

    rapport = racine.find(".//validationReport")
    if rapport is None:
        # Un PDF que veraPDF n'arrive pas a analyser du tout ne produit pas de
        # rapport de validation : c'est une information, pas une conformite.
        resume = racine.find(".//batchSummary")
        illisibles = int((resume.get("failedToParse") if resume is not None else 0) or 0)
        return Resultat(
            disponible=True,
            erreur=(
                "veraPDF n'a pas pu analyser le document"
                if illisibles
                else "veraPDF n'a produit aucun rapport de validation"
            ),
            duree_ms=duree_ms,
        )

    resultat = Resultat(
        disponible=True,
        conforme=(rapport.get("isCompliant") or "").lower() == "true",
        profil=rapport.get("profileName"),
        duree_ms=duree_ms,
    )

    details = rapport.find("details")
    if details is not None:
        resultat.regles_passees = int(details.get("passedRules") or 0)
        resultat.regles_en_echec = int(details.get("failedRules") or 0)
        resultat.controles_passes = int(details.get("passedChecks") or 0)
        resultat.controles_en_echec = int(details.get("failedChecks") or 0)

    for regle in rapport.iter("rule"):
        if (regle.get("status") or "").lower() != "failed":
            continue
        controle = regle.find("check")
        contexte = None
        if controle is not None:
            contexte = (controle.findtext("context") or "").strip() or None
        description = " ".join((regle.findtext("description") or "").split())
        resultat.echecs.append(
            Echec(
                specification=regle.get("specification"),
                clause=regle.get("clause"),
                test=regle.get("testNumber"),
                description=description,
                contexte=contexte,
                controles_en_echec=int(regle.get("failedChecks") or 0),
            )
        )

    return resultat
