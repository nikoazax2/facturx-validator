"""Modele de rapport.

Le JSON produit est un livrable a part entiere : il doit rester exploitable par un
script tiers. D'ou des cles stables, des enumerations fermees et une separation
explicite des niveaux de validation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class LevelStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


class Verdict(StrEnum):
    CONFORME = "conforme"
    CONFORME_AVEC_AVERTISSEMENTS = "conforme_avec_avertissements"
    NON_CONFORME = "non_conforme"
    NON_EVALUABLE = "non_evaluable"


VERDICT_LABELS: dict[str, str] = {
    Verdict.CONFORME: "Conforme",
    Verdict.CONFORME_AVEC_AVERTISSEMENTS: "Conforme, avec avertissements",
    Verdict.NON_CONFORME: "Non conforme",
    Verdict.NON_EVALUABLE: "Non évaluable",
}


class LevelId(StrEnum):
    """Les quatre niveaux, volontairement distincts.

    Un fichier peut franchir CONTAINER et XSD puis echouer sur EN16931 : le
    rapport doit rendre cette difference lisible plutot que de la fondre dans un
    verdict unique.
    """

    CONTAINER = "container"
    PDFA = "pdfa"
    XSD = "xsd"
    EN16931 = "en16931"
    PROFIL = "profil"
    FRCTC = "frctc"


LEVEL_META: dict[str, dict[str, str]] = {
    LevelId.CONTAINER: {
        "label": "Conteneur PDF/A-3",
        "description": (
            "Présence et nommage de la pièce jointe XML, valeur de AFRelationship, "
            "métadonnées XMP Factur-X, indicateurs PDF/A-3."
        ),
    },
    LevelId.PDFA: {
        "label": "Conformité PDF/A",
        "description": (
            "Conformité réelle à la norme ISO 19005-3, évaluée par veraPDF, "
            "l'implémentation de référence. Distinct du niveau précédent, qui ne "
            "contrôle que les marqueurs Factur-X et leur cohérence."
        ),
    },
    LevelId.XSD: {
        "label": "Validité XSD",
        "description": (
            "Conformité structurelle du XML au schéma du profil détecté : éléments "
            "attendus, cardinalités, types de données."
        ),
    },
    LevelId.EN16931: {
        "label": "Conformité EN 16931",
        "description": (
            "Règles métier de la norme européenne, évaluées par le Schematron "
            "officiel CEN/TC 434. Indépendant de la validité XSD."
        ),
    },
    LevelId.PROFIL: {
        "label": "Règles du profil Factur-X",
        "description": (
            "Règles métier propres au profil détecté, évaluées par le Schematron "
            "publié par la FNFE-MPE. Seul niveau de règles métier applicable aux "
            "profils MINIMUM et BASIC WL. Les constats déjà remontés au niveau "
            "EN 16931 ne sont pas répétés ici."
        ),
    },
    LevelId.FRCTC: {
        "label": "Règles France (CTC)",
        "description": (
            "Règles métier françaises du flux entre Plateformes Agréées. Niveau "
            "indicatif, désactivé par défaut."
        ),
    },
}


# Ordre de presentation des niveaux, du conteneur vers le contenu metier.
#
# Il est fixe ici et non deduit de l'ordre d'execution : l'orchestrateur ferme les
# niveaux dans l'ordre ou il peut le faire, qui depend des dependances entre eux,
# pas de l'ordre dans lequel un lecteur souhaite les parcourir.
LEVEL_ORDER: tuple[str, ...] = (
    LevelId.CONTAINER,
    LevelId.PDFA,
    LevelId.XSD,
    LevelId.EN16931,
    LevelId.PROFIL,
    LevelId.FRCTC,
)


class MessageSource(StrEnum):
    CATALOGUE_FR = "catalogue_fr"
    GABARIT_FR = "gabarit_fr"
    ORIGINAL_EN = "original_en"
    INTERNE = "interne"


@dataclass
class Finding:
    index: int = 0
    level: str = ""
    severity: str = Severity.ERROR
    ruleId: str | None = None
    # Numerotation interne du producteur du Schematron, quand elle differe du code
    # normalise porte par ruleId. Conservee pour pouvoir remonter a l'assertion.
    internalRuleId: str | None = None
    xpath: str | None = None
    message: str = ""
    messageOriginal: str | None = None
    messageSource: str = MessageSource.INTERNE
    test: str | None = None
    specification: str | None = None
    hint: str | None = None


@dataclass
class Level:
    id: str
    label: str
    description: str
    status: str
    errors: int = 0
    warnings: int = 0
    infos: int = 0
    reason: str | None = None
    truncated: bool = False


@dataclass
class Notice:
    code: str
    severity: str
    message: str


@dataclass
class Report:
    schemaVersion: str
    generatedAt: str
    verdict: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    document: dict[str, Any] = field(default_factory=dict)
    levels: list[Level] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    notices: list[Notice] = field(default_factory=list)
    regulatory: dict[str, Any] = field(default_factory=dict)
    engine: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReportBuilder:
    """Accumule les constats par niveau et calcule le verdict d'ensemble."""

    def __init__(self, max_per_level: int) -> None:
        self._max_per_level = max_per_level
        self._findings: list[Finding] = []
        self._levels: list[Level] = []
        self._notices: list[Notice] = []
        self._counts: dict[str, dict[str, int]] = {}
        self._truncated: set[str] = set()

    def add(
        self,
        level: str,
        severity: str,
        message: str,
        *,
        rule_id: str | None = None,
        internal_rule_id: str | None = None,
        xpath: str | None = None,
        message_original: str | None = None,
        message_source: str = MessageSource.INTERNE,
        test: str | None = None,
        specification: str | None = None,
        hint: str | None = None,
    ) -> None:
        counts = self._counts.setdefault(level, {"error": 0, "warning": 0, "info": 0})
        total = sum(counts.values())
        # On compte toujours, meme au-dela du plafond, pour que le total reste juste.
        counts[severity] += 1
        if total >= self._max_per_level:
            self._truncated.add(level)
            return
        self._findings.append(
            Finding(
                level=level,
                severity=severity,
                ruleId=rule_id,
                internalRuleId=internal_rule_id,
                xpath=xpath,
                message=message,
                messageOriginal=message_original,
                messageSource=message_source,
                test=test,
                specification=specification,
                hint=hint,
            )
        )

    def notice(self, code: str, severity: str, message: str) -> None:
        self._notices.append(Notice(code=code, severity=severity, message=message))

    def close_level(
        self,
        level: str,
        *,
        status: str | None = None,
        reason: str | None = None,
    ) -> None:
        counts = self._counts.setdefault(level, {"error": 0, "warning": 0, "info": 0})
        meta = LEVEL_META[level]
        if status is None:
            if counts["error"]:
                status = LevelStatus.FAILED
            elif counts["warning"]:
                status = LevelStatus.WARNING
            else:
                status = LevelStatus.PASSED
        self._levels.append(
            Level(
                id=level,
                label=meta["label"],
                description=meta["description"],
                status=status,
                errors=counts["error"],
                warnings=counts["warning"],
                infos=counts["info"],
                reason=reason,
                truncated=level in self._truncated,
            )
        )

    def counts(self, level: str) -> dict[str, int]:
        return dict(self._counts.get(level, {"error": 0, "warning": 0, "info": 0}))

    @property
    def total_errors(self) -> int:
        return sum(c["error"] for c in self._counts.values())

    @property
    def total_warnings(self) -> int:
        return sum(c["warning"] for c in self._counts.values())

    @property
    def total_infos(self) -> int:
        return sum(c["info"] for c in self._counts.values())

    def verdict(self, *, evaluable: bool) -> dict[str, Any]:
        if not evaluable:
            code = Verdict.NON_EVALUABLE
            summary = (
                "Le contenu XML de la facture n'a pas pu être atteint. Les niveaux "
                "de validation métier n'ont pas été exécutés."
            )
        elif self.total_errors:
            code = Verdict.NON_CONFORME
            summary = (
                f"{self.total_errors} erreur(s) relevée(s). Le document ne peut pas "
                "être considéré comme une facture électronique conforme en l'état."
            )
        elif self.total_warnings:
            code = Verdict.CONFORME_AVEC_AVERTISSEMENTS
            summary = (
                f"Aucune erreur. {self.total_warnings} avertissement(s) à examiner, "
                "sans effet bloquant sur la conformité."
            )
        else:
            code = Verdict.CONFORME
            summary = "Aucune erreur ni avertissement relevé sur les niveaux exécutés."
        return {"code": str(code), "label": VERDICT_LABELS[code], "summary": summary}

    def build(
        self,
        *,
        generated_at: str,
        schema_version: str,
        evaluable: bool,
        input_info: dict[str, Any],
        document: dict[str, Any],
        regulatory: dict[str, Any],
        engine: dict[str, Any],
    ) -> Report:
        rang = {niveau: position for position, niveau in enumerate(LEVEL_ORDER)}
        self._levels.sort(key=lambda niveau: rang.get(niveau.id, len(rang)))
        self._findings.sort(key=lambda constat: rang.get(constat.level, len(rang)))
        for position, finding in enumerate(self._findings, start=1):
            finding.index = position
        return Report(
            schemaVersion=schema_version,
            generatedAt=generated_at,
            verdict=self.verdict(evaluable=evaluable),
            input=input_info,
            document=document,
            levels=self._levels,
            findings=self._findings,
            summary={
                "errors": self.total_errors,
                "warnings": self.total_warnings,
                "infos": self.total_infos,
                "byLevel": {
                    level.id: {
                        "status": level.status,
                        "errors": level.errors,
                        "warnings": level.warnings,
                        "infos": level.infos,
                    }
                    for level in self._levels
                },
            },
            notices=self._notices,
            regulatory=regulatory,
            engine=engine,
        )
