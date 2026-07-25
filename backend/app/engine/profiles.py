"""Profils Factur-X et portee EN 16931.

Le point delicat : MINIMUM et BASIC WL ne sont pas des profils conformes a
EN 16931. Ce sont des sous-ensembles qui ne declarent pas l'URN CEN. Executer le
Schematron EN 16931 dessus produirait des dizaines d'erreurs sans valeur, puisque
la norme exige des donnees que le profil n'autorise pas a porter. La portee est
donc decidee ici, et le rapport l'explique au lieu de la subir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EN16931_URN = "urn:cen.eu:en16931:2017"


@dataclass(frozen=True)
class Profile:
    code: str
    label: str
    urns: tuple[str, ...]
    xsd_flavour: str | None
    # Le Schematron EN 16931 s'applique-t-il de facon pertinente a ce profil ?
    en16931_scope: bool
    # Le profil suffit-il a constituer une facture complete au sens fiscal francais ?
    fiscally_complete: bool
    # Valeurs de /AFRelationship attendues pour ce profil, voir engine/pdf.py.
    expected_af_relationship: tuple[str, ...] = ("Data", "Source", "Alternative")
    note: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


PROFILES: tuple[Profile, ...] = (
    Profile(
        code="MINIMUM",
        label="MINIMUM",
        urns=("urn:factur-x.eu:1p0:minimum",),
        aliases=("urn:zugferd.de:2p0:minimum", "urn:zugferd.de:2p1:minimum"),
        xsd_flavour="facturx-minimum",
        en16931_scope=False,
        fiscally_complete=False,
        expected_af_relationship=("Data",),
        note=(
            "Le profil MINIMUM ne porte que des données de tête destinées à "
            "l'intégration comptable. Il ne constitue pas une facture complète au "
            "sens de la réglementation fiscale française et ne peut pas servir "
            "seul de facture d'origine."
        ),
    ),
    Profile(
        code="BASIC_WL",
        label="BASIC WL",
        urns=("urn:factur-x.eu:1p0:basicwl",),
        aliases=("urn:zugferd.de:2p0:basicwl", "urn:zugferd.de:2p1:basicwl"),
        xsd_flavour="facturx-basicwl",
        en16931_scope=False,
        fiscally_complete=False,
        expected_af_relationship=("Data",),
        note=(
            "Le profil BASIC WL ne comporte pas de lignes de facture. Il ne "
            "constitue pas une facture complète au sens de la réglementation "
            "fiscale française."
        ),
    ),
    Profile(
        code="BASIC",
        label="BASIC",
        urns=(f"{EN16931_URN}#compliant#urn:factur-x.eu:1p0:basic",),
        aliases=(f"{EN16931_URN}#compliant#urn:zugferd.de:2p0:basic",),
        xsd_flavour="facturx-basic",
        en16931_scope=True,
        fiscally_complete=True,
    ),
    Profile(
        code="EN16931",
        label="EN 16931 (COMFORT)",
        urns=(EN16931_URN,),
        xsd_flavour="facturx-en16931",
        en16931_scope=True,
        fiscally_complete=True,
    ),
    Profile(
        code="EXTENDED",
        label="EXTENDED",
        urns=(f"{EN16931_URN}#conformant#urn:factur-x.eu:1p0:extended",),
        aliases=(f"{EN16931_URN}#conformant#urn:zugferd.de:2p0:extended",),
        xsd_flavour="facturx-extended",
        en16931_scope=True,
        fiscally_complete=True,
    ),
)

# Profils hors jeu Factur-X mais qui declarent une conformite EN 16931. On les
# reconnait pour eviter un verdict trompeur du type "profil inconnu".
FOREIGN_CIUS: tuple[Profile, ...] = (
    Profile(
        code="XRECHNUNG",
        label="XRechnung (Allemagne)",
        urns=(),
        xsd_flavour=None,
        en16931_scope=True,
        fiscally_complete=True,
        note=(
            "Ce document déclare la spécialisation allemande XRechnung, et non un "
            "profil Factur-X. Les règles EN 16931 sont évaluées, mais les règles "
            "propres à XRechnung ne le sont pas."
        ),
    ),
    Profile(
        code="PEPPOL_BIS3",
        label="Peppol BIS Billing 3.0",
        urns=(),
        xsd_flavour=None,
        en16931_scope=True,
        fiscally_complete=True,
        note=(
            "Ce document déclare la spécialisation Peppol BIS Billing 3.0, et non "
            "un profil Factur-X. Les règles EN 16931 sont évaluées, mais les "
            "règles propres à Peppol ne le sont pas."
        ),
    ),
)

UNKNOWN_PROFILE = Profile(
    code="INCONNU",
    label="Profil non reconnu",
    urns=(),
    # Repli sur EXTENDED, sur-ensemble structurel le plus permissif : cela permet
    # au moins de dire si le XML est un CII bien forme.
    xsd_flavour="facturx-extended",
    en16931_scope=False,
    fiscally_complete=False,
)

_BY_URN: dict[str, Profile] = {}
for _p in PROFILES:
    for _u in _p.urns + _p.aliases:
        _BY_URN[_u] = _p


def resolve(urn: str | None) -> tuple[Profile, bool]:
    """Retourne (profil, reconnu) pour un URN de GuidelineID ou de CustomizationID."""
    if not urn:
        return UNKNOWN_PROFILE, False
    value = urn.strip()
    if value in _BY_URN:
        return _BY_URN[value], True

    lowered = value.lower()
    if "xrechnung" in lowered:
        return FOREIGN_CIUS[0], True
    if "peppol" in lowered:
        return FOREIGN_CIUS[1], True

    # Un URN inconnu qui declare tout de meme la conformite CEN : on evalue
    # EN 16931 plutot que de refuser d'examiner le document.
    if value.startswith(EN16931_URN):
        return (
            Profile(
                code="EN16931_DERIVE",
                label="Spécialisation EN 16931 non identifiée",
                urns=(),
                xsd_flavour="facturx-extended",
                en16931_scope=True,
                fiscally_complete=True,
                note=(
                    "L'identifiant de spécification déclare une conformité "
                    "EN 16931 sans correspondre à un profil Factur-X connu. Les "
                    "règles EN 16931 sont évaluées, la validation structurelle "
                    "utilise le schéma EXTENDED comme sur-ensemble."
                ),
            ),
            False,
        )
    return UNKNOWN_PROFILE, False


def all_known_urns() -> list[str]:
    return sorted(_BY_URN)
