"""Reperes reglementaires francais joints au rapport.

Ces valeurs ont ete verifiees le 24 juillet 2026. Elles sont deliberement
centralisees ici, avec leur date de verification, parce qu'un decret peut les
deplacer : le rapport doit dire quand il a ete informe, pas affirmer une date
sans origine.

Terminologie : l'organisme de transmission s'appelle Plateforme Agreee (PA).
L'ancien terme Plateforme de Dematerialisation Partenaire (PDP) n'est plus celui
en vigueur et ne doit pas apparaitre dans l'interface ni dans le rapport.
"""

from __future__ import annotations

from typing import Any

VERIFIED_ON = "2026-07-24"

LEGAL_BASIS = (
    "Article 91 de la loi de finances pour 2024, décret n° 2024-266 du 25 mars 2024."
)

MILESTONES: list[dict[str, Any]] = [
    {
        "date": "2026-09-01",
        "scope": "Toutes les entreprises assujetties à la TVA",
        "obligation": "reception",
        "label": (
            "Obligation de réception des factures électroniques, quelle que soit la "
            "taille de l'entreprise, y compris en franchise de TVA."
        ),
    },
    {
        "date": "2026-09-01",
        "scope": "Grandes entreprises et entreprises de taille intermédiaire",
        "obligation": "emission",
        "label": "Obligation d'émission des factures électroniques et d'e-reporting.",
    },
    {
        "date": "2027-09-01",
        "scope": "PME, TPE et micro-entreprises",
        "obligation": "emission",
        "label": "Obligation d'émission des factures électroniques et d'e-reporting.",
    },
]

DEFERRAL_NOTE = (
    "Un décret peut décaler le premier palier, sans pouvoir le reporter au-delà du "
    "1er décembre 2026. Vérifiez le calendrier applicable à votre situation avant "
    "toute décision de planning."
)

DISCLAIMER = (
    "Ce rapport est un diagnostic technique automatisé. Il ne constitue ni une "
    "attestation de conformité fiscale, ni un conseil juridique, et ne préjuge pas "
    "de l'acceptation du document par une Plateforme Agréée."
)


def block() -> dict[str, Any]:
    return {
        "verifiedOn": VERIFIED_ON,
        "legalBasis": LEGAL_BASIS,
        "milestones": MILESTONES,
        "deferralNote": DEFERRAL_NOTE,
        "disclaimer": DISCLAIMER,
        "terminology": {
            "transmissionOperator": "Plateforme Agréée (PA)",
            "deprecated": "Plateforme de Dématérialisation Partenaire (PDP)",
        },
    }
