"""Chargement et mise en cache des artefacts de validation.

Deux couts a maitriser pour tenir la cible de moins de 3 secondes :

- la compilation des feuilles XSLT Schematron (environ 700 a 900 Ko chacune) ;
- la compilation des schemas XSD, dont EXTENDED et UBL 2.1 qui sont volumineux.

Les deux sont faits une fois puis reutilises. Le processeur Saxon n'est pas sur
pour un usage concurrent : tous les appels passent par un verrou unique. Chaque
validation Schematron coute quelques dizaines de millisecondes, la serialisation
n'est donc pas un probleme a l'echelle visee.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from lxml import etree

from .. import config


class ArtifactsMissing(RuntimeError):
    """Les artefacts officiels n'ont pas ete recuperes avant le demarrage."""


_SCHEMATRON_FILES = {
    "CII": "schematron/EN16931-CII-validation.xslt",
    "UBL": "schematron/EN16931-UBL-validation.xslt",
}
_FRCTC_FILE = "fr-ctc/BR-FR-Flux2-Schematron-CII.xslt"

# Schematron FNFE par profil. Seuls ces cinq profils en ont un : les
# specialisations etrangeres et les profils non reconnus n'en beneficient pas.
_PROFILE_SCHEMATRON = {
    "MINIMUM": "schematron-profil/MINIMUM.xsl",
    "BASIC_WL": "schematron-profil/BASIC_WL.xsl",
    "BASIC": "schematron-profil/BASIC.xsl",
    "EN16931": "schematron-profil/EN16931.xsl",
    "EXTENDED": "schematron-profil/EXTENDED.xsl",
}

# Point d'entree XSD par saveur.
_XSD_ENTRYPOINTS = {
    "facturx-minimum": "Factur-X_MINIMUM.xsd",
    "facturx-basicwl": "Factur-X_BASICWL.xsd",
    "facturx-basic": "Factur-X_BASIC.xsd",
    "facturx-en16931": "Factur-X_EN16931.xsd",
    "facturx-extended": "Factur-X_EXTENDED.xsd",
    "ubl-2.1:invoice": "maindoc/UBL-Invoice-2.1.xsd",
    "ubl-2.1:creditnote": "maindoc/UBL-CreditNote-2.1.xsd",
}


class Resources:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.RLock()
        self._saxon: Any = None
        self._xslt_processor: Any = None
        self._executables: dict[str, Any] = {}
        self._schemas: dict[str, etree.XMLSchema] = {}
        self._manifest: dict[str, Any] | None = None

    # -- inventaire ---------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    def manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            path = self._root / "manifest.json"
            if not path.exists():
                raise ArtifactsMissing(
                    f"manifest.json absent de {self._root}. Executez "
                    "python scripts/fetch_artifacts.py avant de demarrer le service."
                )
            self._manifest = json.loads(path.read_text(encoding="utf-8"))
        return self._manifest

    def artifact_summary(self) -> dict[str, Any]:
        manifest = self.manifest()
        return {
            "en16931SchematronVersion": manifest.get("en16931Version"),
            "facturxSchemaPackageVersion": manifest.get("facturxPackageVersion"),
            "sources": [
                {
                    "role": item["role"],
                    "version": item.get("version"),
                    "licence": item.get("licence"),
                    "publisher": item.get("publisher"),
                    "sha256": item.get("sha256"),
                }
                for item in manifest.get("artifacts", [])
            ],
        }

    def has_profile_schematron(self, profile_code: str) -> bool:
        relative = _PROFILE_SCHEMATRON.get(profile_code)
        return bool(relative) and (self._root / relative).exists()

    def verify(self) -> None:
        """Echoue tot si un artefact attendu manque."""
        self.manifest()
        missing: list[str] = []
        for relative in list(_SCHEMATRON_FILES.values()) + list(_PROFILE_SCHEMATRON.values()):
            if not (self._root / relative).exists():
                missing.append(relative)
        for flavour, entrypoint in _XSD_ENTRYPOINTS.items():
            directory = flavour.split(":", 1)[0]
            if not (self._root / "xsd" / directory / entrypoint).exists():
                missing.append(f"xsd/{directory}/{entrypoint}")
        if config.FRCTC_ENABLED and not (self._root / _FRCTC_FILE).exists():
            missing.append(_FRCTC_FILE)
        if missing:
            raise ArtifactsMissing(
                "artefacts manquants : " + ", ".join(missing) + ". Executez "
                "python scripts/fetch_artifacts.py."
            )

    # -- Saxon -------------------------------------------------------------

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def _ensure_saxon(self) -> tuple[Any, Any]:
        if self._saxon is None:
            from saxonche import PySaxonProcessor

            self._saxon = PySaxonProcessor(license=False)
            self._xslt_processor = self._saxon.new_xslt30_processor()
        return self._saxon, self._xslt_processor

    def saxon_processor(self) -> Any:
        with self._lock:
            return self._ensure_saxon()[0]

    def ensure_processor(self) -> None:
        """Cree l'isolat Saxon depuis le fil appelant.

        A appeler au demarrage, depuis le fil principal. L'isolat GraalVM qui
        porte Saxon est rattache au fil qui le cree ; si sa creation est declenchee
        par un fil du reservoir de travail et sa destruction par le fil principal a
        l'extinction du processus, la machine virtuelle native s'arrete sur un
        StackOverflowError trompeur, apres avoir pourtant rendu des resultats
        justes. Aligner creation et destruction sur le meme fil evite ce bruit dans
        les journaux d'arret.

        Aucune liberation explicite n'est prevue en regard : le processeur vit le
        temps du processus, et le detruire en cours de route viderait le cache des
        feuilles compilees, qui represente l'essentiel du cout de demarrage.
        """
        with self._lock:
            self._ensure_saxon()

    def schematron(self, key: str) -> Any:
        """Retourne la feuille XSLT compilee, en la compilant au premier appel."""
        with self._lock:
            if key in self._executables:
                return self._executables[key]
            if key == "FRCTC":
                relative = _FRCTC_FILE
            elif key in _PROFILE_SCHEMATRON:
                relative = _PROFILE_SCHEMATRON[key]
            else:
                relative = _SCHEMATRON_FILES[key]
            path = self._root / relative
            if not path.exists():
                raise ArtifactsMissing(f"feuille Schematron absente : {path}")
            _, processor = self._ensure_saxon()
            executable = processor.compile_stylesheet(stylesheet_file=str(path))
            self._executables[key] = executable
            return executable

    # -- XSD ---------------------------------------------------------------

    def schema(self, flavour: str) -> etree.XMLSchema:
        with self._lock:
            if flavour in self._schemas:
                return self._schemas[flavour]
            entrypoint = _XSD_ENTRYPOINTS[flavour]
            directory = flavour.split(":", 1)[0]
            path = self._root / "xsd" / directory / entrypoint
            if not path.exists():
                raise ArtifactsMissing(f"schema XSD absent : {path}")
            document = etree.parse(str(path))
            schema = etree.XMLSchema(document)
            self._schemas[flavour] = schema
            return schema

    # -- prechauffage ------------------------------------------------------

    def warmup(self, *, schemas: bool = True) -> dict[str, float]:
        """Compile a l'avance ce qui sera necessaire, et renvoie les durees."""
        import time

        timings: dict[str, float] = {}
        for key in _SCHEMATRON_FILES:
            start = time.perf_counter()
            self.schematron(key)
            timings[f"schematron:{key}"] = round((time.perf_counter() - start) * 1000, 1)
        for key in _PROFILE_SCHEMATRON:
            if not self.has_profile_schematron(key):
                continue
            start = time.perf_counter()
            self.schematron(key)
            timings[f"profil:{key}"] = round((time.perf_counter() - start) * 1000, 1)
        if config.FRCTC_ENABLED:
            start = time.perf_counter()
            self.schematron("FRCTC")
            timings["schematron:FRCTC"] = round((time.perf_counter() - start) * 1000, 1)
        if schemas:
            for flavour in _XSD_ENTRYPOINTS:
                start = time.perf_counter()
                self.schema(flavour)
                timings[f"xsd:{flavour}"] = round((time.perf_counter() - start) * 1000, 1)
        return timings


RESOURCES = Resources(config.RESOURCES_DIR)
