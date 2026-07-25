"""Enchainement complet de la validation.

L'ordre n'est pas arbitraire. Les attentes du conteneur PDF dependent du profil,
le profil vient du XML, et le XML vient du conteneur. On collecte donc d'abord les
faits PDF, on lit le XML, on resout le profil, puis on rend son verdict a chaque
niveau. Un niveau qui n'a pas pu etre execute est declare explicitement plutot que
compte comme reussi.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any

from .. import config
from ..report import LevelId, LevelStatus, MessageSource, ReportBuilder, Severity
from . import (
    detect,
    messages,
    pdf as pdf_module,
    profiles,
    regulatory,
    schematron,
    verapdf,
    xsd,
)
from .resources import RESOURCES

SPEC_EN16931 = "EN 16931 / CEN TC 434"
SPEC_FACTURX = "Factur-X / PDF/A-3"
SPEC_PROFIL = "Factur-X / FNFE-MPE"
SPEC_FRCTC = "Regles France CTC (flux 2)"

# Orthographes tolerees du niveau de conformite dans les metadonnees XMP.
_XMP_CONFORMANCE = {
    "MINIMUM": {"MINIMUM"},
    "BASIC_WL": {"BASIC WL", "BASICWL", "BASIC-WL"},
    "BASIC": {"BASIC"},
    "EN16931": {"EN 16931", "EN16931", "COMFORT"},
    "EXTENDED": {"EXTENDED"},
}

PDFA_STRUCTURAL_CAVEAT = (
    "Les contrôles PDF/A-3 réalisés ici portent sur les marqueurs et leur "
    "cohérence : métadonnées XMP, tableau /AF, valeur de AFRelationship, type MIME "
    "de la pièce jointe. Ils ne remplacent pas un audit de conformité PDF/A "
    "complet, qui suppose un outil dédié comme veraPDF."
)


def _nom_sain(brut: str | None) -> str | None:
    """Nettoie le nom de fichier avant de le renvoyer dans le rapport.

    Le nom vient de l'appelant. Il n'est jamais utilise pour construire un chemin,
    mais il est renvoye dans le rapport, affiche dans l'interface et repris pour
    nommer le fichier telecharge : on en retire donc les separateurs de chemin et
    les caracteres de controle, et on borne sa longueur pour qu'un nom demesure ne
    gonfle pas le rapport.
    """
    if not brut:
        return None
    sans_chemin = brut.replace("\\", "/").rsplit("/", 1)[-1]
    nettoye = "".join(c for c in sans_chemin if c.isprintable() and c not in '"<>|')
    nettoye = nettoye.strip() or "sans-nom"
    return nettoye[:180]


def validate(raw: bytes, filename: str | None = None) -> dict[str, Any]:
    """Valide un PDF Factur-X ou un XML seul et retourne le rapport en dictionnaire."""
    started = time.perf_counter()
    builder = ReportBuilder(config.MAX_FINDINGS_PER_LEVEL)

    input_info: dict[str, Any] = {
        "filename": _nom_sain(filename),
        "sizeBytes": len(raw),
        # Empreinte du contenu, utile pour rapprocher deux rapports. Le fichier
        # lui-meme n'est jamais conserve.
        "sha256": hashlib.sha256(raw).hexdigest(),
        "kind": None,
    }
    document: dict[str, Any] = {
        "syntax": None,
        "documentType": None,
        "profile": None,
        "identification": {},
        "attachment": None,
    }
    levels_run: list[str] = []

    is_pdf = raw[:5] == b"%PDF-"
    input_info["kind"] = "pdf" if is_pdf else "xml"

    inspection: pdf_module.PdfInspection | None = None
    xml_bytes: bytes | None = None

    # ---- 1. conteneur -----------------------------------------------------
    if is_pdf:
        try:
            inspection = pdf_module.inspect(raw)
        except pdf_module.PdfUnreadable as exc:
            builder.add(
                LevelId.CONTAINER,
                Severity.ERROR,
                str(exc),
                rule_id="FX-PDF-001",
                specification=SPEC_FACTURX,
                hint="Vérifiez que le fichier est bien un PDF non chiffré.",
            )
            builder.close_level(LevelId.CONTAINER)
            return _finalise_early(
                builder, input_info, document, started, levels_run, [LevelId.CONTAINER]
            )

        document["attachment"] = _attachment_block(inspection)
        if inspection.invoice_attachment is not None:
            xml_bytes = inspection.invoice_attachment.payload
    else:
        xml_bytes = raw

    # ---- 1 bis. conformite PDF/A reelle ----------------------------------
    audit_pdfa = _pdfa_level(builder, raw, is_pdf, levels_run)

    # ---- 2. XML et profil -------------------------------------------------
    parsed: detect.XmlDocument | None = None
    profile = profiles.UNKNOWN_PROFILE
    profile_recognised = False
    parse_error: str | None = None

    if xml_bytes is not None:
        try:
            parsed = detect.parse(xml_bytes)
        except detect.XmlNotWellFormed as exc:
            position = ""
            if exc.line:
                position = f" (ligne {exc.line}"
                position += f", colonne {exc.column})" if exc.column else ")"
            parse_error = (
                f"Le XML n'est pas bien formé{position} : {exc.detail} "
                "Aucune validation de schéma ni de règle métier n'est possible tant "
                "que le document n'est pas syntaxiquement correct."
            )
        else:
            document["syntax"] = parsed.syntax
            document["documentType"] = parsed.document_kind
            document["identification"] = parsed.identification
            document["guidelineId"] = parsed.guideline_id
            document["businessProcessId"] = parsed.profile_id
            profile, profile_recognised = profiles.resolve(parsed.guideline_id)
            document["profile"] = {
                "code": profile.code,
                "label": profile.label,
                "urn": parsed.guideline_id,
                "recognised": profile_recognised,
                "en16931Scope": profile.en16931_scope,
                "fiscallyComplete": profile.fiscally_complete,
                "note": profile.note,
            }

    # ---- 3. constats de conteneur ----------------------------------------
    if is_pdf and inspection is not None:
        _container_findings(builder, inspection, profile, parsed)
        builder.close_level(LevelId.CONTAINER)
        levels_run.append(str(LevelId.CONTAINER))
    else:
        builder.close_level(
            LevelId.CONTAINER,
            status=LevelStatus.NOT_APPLICABLE,
            reason=(
                "Un XML seul a été fourni : il n'y a pas de conteneur PDF/A-3 à "
                "contrôler."
            ),
        )

    # ---- 4. arret si le XML est hors d'atteinte ---------------------------
    if xml_bytes is None or parse_error is not None or parsed is None:
        if parse_error:
            builder.add(
                LevelId.XSD,
                Severity.ERROR,
                parse_error,
                rule_id="FX-XML-001",
                specification=SPEC_FACTURX,
            )
            builder.close_level(LevelId.XSD)
        else:
            builder.close_level(
                LevelId.XSD,
                status=LevelStatus.SKIPPED,
                reason="Aucun XML de facture n'a pu être extrait du PDF.",
            )
        for niveau in (LevelId.EN16931, LevelId.PROFIL):
            builder.close_level(
                niveau,
                status=LevelStatus.SKIPPED,
                reason=(
                    "Niveau non exécuté : les règles métier supposent un XML "
                    "exploitable."
                ),
            )
        _notices(builder, inspection, profile, parsed, is_pdf, audit_pdfa)
        return _build(
            builder, input_info, document, started, levels_run, evaluable=False
        )

    if parsed.syntax is None:
        detail = (
            f"La syntaxe du XML n'est pas reconnue : élément racine "
            f"« {parsed.root_localname} » dans l'espace de noms "
            f"« {parsed.root_namespace or 'aucun'} »."
        )
        if parsed.legacy:
            detail += (
                f" Il s'agit apparemment de {parsed.legacy}, format historique hors "
                "du périmètre de cet outil, qui traite le CII D16B ou D22B et "
                "l'UBL 2.1."
            )
        else:
            detail += (
                " Les syntaxes acceptées sont le CII (CrossIndustryInvoice) et "
                "l'UBL 2.1 (Invoice ou CreditNote)."
            )
        builder.add(
            LevelId.XSD,
            Severity.ERROR,
            detail,
            rule_id="FX-XML-002",
            specification=SPEC_FACTURX,
        )
        builder.close_level(LevelId.XSD)
        for niveau in (LevelId.EN16931, LevelId.PROFIL):
            builder.close_level(
                niveau,
                status=LevelStatus.SKIPPED,
                reason="Niveau non exécuté : la syntaxe du document n'est pas reconnue.",
            )
        _notices(builder, inspection, profile, parsed, is_pdf, audit_pdfa)
        return _build(
            builder, input_info, document, started, levels_run, evaluable=False
        )

    # ---- 5. validite XSD --------------------------------------------------
    flavour = _xsd_flavour(parsed, profile)
    document["xsdFlavour"] = flavour
    schema = RESOURCES.schema(flavour)
    xsd_result = xsd.validate(parsed.tree, schema, flavour)
    for error in xsd_result.errors:
        location = error.xpath
        if not location and error.line:
            location = f"ligne {error.line}"
        french, source = messages.translate_xsd(error.message)
        builder.add(
            LevelId.XSD,
            Severity.ERROR,
            french,
            rule_id="XSD",
            xpath=location,
            message_original=(
                messages.shorten_qnames(error.message)
                if source != str(MessageSource.ORIGINAL_EN)
                else None
            ),
            message_source=source,
            specification=f"Schéma {flavour}",
        )
    if not profile_recognised and parsed.guideline_id:
        builder.add(
            LevelId.XSD,
            Severity.WARNING,
            (
                f"L'identifiant de spécification « {parsed.guideline_id} » ne "
                "correspond à aucun profil Factur-X connu. La validation "
                f"structurelle a utilisé le schéma {flavour} comme sur-ensemble."
            ),
            rule_id="FX-PROFILE-002",
            xpath=_guideline_xpath(parsed),
            specification=SPEC_FACTURX,
        )
    elif not parsed.guideline_id:
        builder.add(
            LevelId.XSD,
            Severity.ERROR,
            (
                "Aucun identifiant de spécification n'a été trouvé : le profil "
                "Factur-X ne peut pas être déterminé."
            ),
            rule_id="FX-PROFILE-001",
            xpath=_guideline_xpath(parsed),
            specification=SPEC_FACTURX,
            hint=(
                "Renseignez GuidelineSpecifiedDocumentContextParameter/ID avec l'URN "
                "du profil visé."
            ),
        )
    builder.close_level(LevelId.XSD)
    levels_run.append(str(LevelId.XSD))

    # ---- 6. conformite EN 16931 ------------------------------------------
    # Empreintes des constats EN 16931, pour que le niveau du profil ne les repete
    # pas : les deux Schematron se recouvrent partiellement.
    deja_vus: set[tuple[str | None, str | None]] = set()

    if not profile.en16931_scope:
        builder.close_level(
            LevelId.EN16931,
            status=LevelStatus.NOT_APPLICABLE,
            reason=(
                f"Le profil {profile.label} ne déclare pas de conformité à EN 16931. "
                "La norme exige des données que ce profil n'autorise pas à porter : "
                "exécuter ses règles produirait des erreurs sans portée. Les règles "
                "métier applicables sont celles du profil, au niveau suivant."
            ),
        )
    else:
        _schematron_level(
            builder,
            LevelId.EN16931,
            key=parsed.syntax,
            xml_text=parsed.text,
            specification=SPEC_EN16931,
            collect_into=deja_vus,
        )
        levels_run.append(str(LevelId.EN16931))

    # ---- 7. regles propres au profil Factur-X ----------------------------
    _profile_level(builder, parsed, profile, deja_vus, levels_run)

    # ---- 8. regles France, indicatif et desactive par defaut -------------
    if config.FRCTC_ENABLED and parsed.syntax == "CII":
        _schematron_level(
            builder,
            LevelId.FRCTC,
            key="FRCTC",
            xml_text=parsed.text,
            specification=SPEC_FRCTC,
            downgrade_to_warning=True,
        )
        levels_run.append(str(LevelId.FRCTC))

    _notices(builder, inspection, profile, parsed, is_pdf, audit_pdfa)
    return _build(builder, input_info, document, started, levels_run, evaluable=True)


# --------------------------------------------------------------------------
# Conteneur
# --------------------------------------------------------------------------


def _attachment_block(inspection: pdf_module.PdfInspection) -> dict[str, Any]:
    chosen = inspection.invoice_attachment
    return {
        "count": len(inspection.attachments),
        "names": [a.name for a in inspection.attachments],
        "selected": chosen.name if chosen else None,
        "selectedSizeBytes": len(chosen.payload) if chosen and chosen.payload else None,
        "afRelationship": chosen.af_relationship if chosen else None,
        "mimeSubtype": chosen.mime_subtype if chosen else None,
        "pdfVersion": inspection.pdf_version,
        "pageCount": inspection.page_count,
        "pdfaPart": inspection.pdfa_part,
        "pdfaConformance": inspection.pdfa_conformance,
        "xmpFacturX": inspection.facturx_xmp or None,
    }


def _container_findings(
    builder: ReportBuilder,
    inspection: pdf_module.PdfInspection,
    profile: profiles.Profile,
    parsed: detect.XmlDocument | None,
) -> None:
    add = builder.add

    if inspection.encrypted:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            "Le PDF est chiffré. Un PDF/A-3 ne doit pas être chiffré.",
            rule_id="FX-PDF-002",
            specification=SPEC_FACTURX,
        )

    # -- piece jointe
    if inspection.invoice_attachment is None:
        if not inspection.attachments:
            add(
                LevelId.CONTAINER,
                Severity.ERROR,
                (
                    "Ce PDF ne contient aucune pièce jointe : il n'y a pas de XML de "
                    "facture à valider. Un PDF Factur-X est un PDF/A-3 auquel le XML "
                    "est attaché en tant que fichier incorporé, nommé "
                    "« factur-x.xml »."
                ),
                rule_id="FX-PDF-010",
                specification=SPEC_FACTURX,
                hint=(
                    "Le PDF seul, même lisible par un humain, ne vaut pas facture "
                    "électronique au sens de la réforme."
                ),
            )
        elif inspection.ambiguous_candidates:
            add(
                LevelId.CONTAINER,
                Severity.ERROR,
                (
                    "Plusieurs pièces jointes XML pourraient être la facture "
                    f"({', '.join(inspection.ambiguous_candidates)}) sans qu'aucune ne "
                    "porte un nom permettant de trancher. La spécification attend un "
                    "unique fichier nommé « factur-x.xml »."
                ),
                rule_id="FX-PDF-012",
                specification=SPEC_FACTURX,
            )
        else:
            listing = ", ".join(a.name for a in inspection.attachments) or "aucune"
            add(
                LevelId.CONTAINER,
                Severity.ERROR,
                (
                    "Aucune pièce jointe ne correspond à un XML de facture "
                    f"exploitable. Pièces jointes trouvées : {listing}. La "
                    "spécification attend « factur-x.xml », les noms historiques "
                    "« ZUGFeRD-invoice.xml » et « zugferd-invoice.xml » étant "
                    "également acceptés."
                ),
                rule_id="FX-PDF-011",
                specification=SPEC_FACTURX,
            )
        return

    attachment = inspection.invoice_attachment

    if inspection.ambiguous_candidates:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                "Plusieurs pièces jointes portent un nom de facture reconnu "
                f"({', '.join(inspection.ambiguous_candidates)}). "
                f"« {attachment.name} » a été retenue par ordre de priorité, mais un "
                "autre outil pourrait faire un choix différent."
            ),
            rule_id="FX-PDF-013",
            specification=SPEC_FACTURX,
        )

    if inspection.non_standard_name_used:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                f"La pièce jointe XML s'appelle « {attachment.name} », alors que la "
                "spécification Factur-X attend « factur-x.xml ». Le fichier a été "
                "validé, mais un logiciel destinataire strict peut ne pas le trouver."
            ),
            rule_id="FX-PDF-014",
            specification=SPEC_FACTURX,
        )
    elif attachment.name.lower() == pdf_module.EXPECTED_ATTACHMENT_NAME and not attachment.name_matches_spec_case:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                f"Le nom de la pièce jointe « {attachment.name} » ne respecte pas la "
                "casse attendue « factur-x.xml »."
            ),
            rule_id="FX-PDF-015",
            specification=SPEC_FACTURX,
        )
    elif attachment.name.lower() == "zugferd-invoice.xml":
        add(
            LevelId.CONTAINER,
            Severity.INFO,
            (
                f"La pièce jointe porte le nom historique « {attachment.name} ». Ce "
                "nom reste lisible par la plupart des logiciels, mais la "
                "spécification Factur-X courante attend « factur-x.xml »."
            ),
            rule_id="FX-PDF-016",
            specification=SPEC_FACTURX,
        )

    # -- type MIME
    subtype = (attachment.mime_subtype or "").lower()
    if not subtype:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                "La pièce jointe ne déclare pas de type MIME (/Subtype). PDF/A-3 "
                "impose de le renseigner, avec la valeur « text/xml »."
            ),
            rule_id="FX-PDF-020",
            specification=SPEC_FACTURX,
        )
    elif subtype not in {"text/xml", "application/xml"}:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                f"Le type MIME déclaré pour la pièce jointe est « {subtype} », alors "
                "que « text/xml » est attendu."
            ),
            rule_id="FX-PDF-021",
            specification=SPEC_FACTURX,
        )

    # -- AFRelationship, valeur dependante du profil
    _af_relationship_findings(builder, attachment, profile)

    # -- reference /AF au niveau document
    if not attachment.referenced_by_af:
        add(
            LevelId.CONTAINER,
            Severity.ERROR,
            (
                "La pièce jointe XML n'est pas référencée par le tableau /AF du "
                "document. PDF/A-3 exige que tout fichier incorporé soit déclaré "
                "comme fichier associé, sans quoi un lecteur conforme peut l'ignorer."
            ),
            rule_id="FX-PDF-031",
            specification=SPEC_FACTURX,
        )

    # -- PDF/A-3 et XMP
    if not inspection.has_xmp:
        add(
            LevelId.CONTAINER,
            Severity.ERROR,
            (
                "Le document ne comporte pas de métadonnées XMP. PDF/A-3 les impose, "
                "et Factur-X y place l'identification du profil."
            ),
            rule_id="FX-PDF-040",
            specification=SPEC_FACTURX,
        )
    else:
        if not inspection.xmp_valid:
            add(
                LevelId.CONTAINER,
                Severity.ERROR,
                "Les métadonnées XMP du document ne sont pas un XML bien formé.",
                rule_id="FX-PDF-041",
                specification=SPEC_FACTURX,
            )
        if inspection.pdfa_part is None:
            add(
                LevelId.CONTAINER,
                Severity.ERROR,
                (
                    "Les métadonnées XMP ne déclarent pas d'identifiant de partie "
                    "PDF/A (pdfaid:part). Rien ne permet d'affirmer que ce PDF est un "
                    "PDF/A-3."
                ),
                rule_id="FX-PDF-042",
                specification=SPEC_FACTURX,
            )
        elif inspection.pdfa_part.strip() != "3":
            add(
                LevelId.CONTAINER,
                Severity.ERROR,
                (
                    f"Les métadonnées XMP déclarent PDF/A-{inspection.pdfa_part}, "
                    "alors que Factur-X exige PDF/A-3. Seul PDF/A-3 autorise "
                    "l'incorporation de fichiers arbitraires."
                ),
                rule_id="FX-PDF-043",
                specification=SPEC_FACTURX,
            )
        conformance = (inspection.pdfa_conformance or "").strip().upper()
        if inspection.pdfa_part == "3" and conformance not in {"A", "B", "U"}:
            add(
                LevelId.CONTAINER,
                Severity.WARNING,
                (
                    "Le niveau de conformité PDF/A n'est pas déclaré ou n'est pas "
                    f"reconnu (valeur : « {inspection.pdfa_conformance or 'absente'} »). "
                    "Les valeurs attendues sont A, B ou U."
                ),
                rule_id="FX-PDF-044",
                specification=SPEC_FACTURX,
            )
        _xmp_facturx_findings(builder, inspection, attachment, profile)

    if not inspection.has_output_intent:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                "Le document ne déclare pas d'OutputIntent. PDF/A impose de décrire "
                "l'espace colorimétrique de sortie."
            ),
            rule_id="FX-PDF-050",
            specification=SPEC_FACTURX,
        )

    if inspection.page_count == 0:
        add(
            LevelId.CONTAINER,
            Severity.WARNING,
            "Le PDF ne comporte aucune page exploitable.",
            rule_id="FX-PDF-051",
            specification=SPEC_FACTURX,
        )


def _af_relationship_findings(
    builder: ReportBuilder,
    attachment: pdf_module.Attachment,
    profile: profiles.Profile,
) -> None:
    """Contrôle de /AFRelationship.

    Il n'existe pas une valeur unique attendue, contrairement a une idee repandue.
    MINIMUM et BASIC WL attendent Data, le XML n'etant qu'une donnee accompagnant
    la representation visuelle. Pour BASIC, EN 16931 et EXTENDED, la specification
    francaise admet Data, Source ou Alternative selon la facon dont le PDF a ete
    produit, alors que l'usage allemand impose Alternative. On refuse donc les
    valeurs hors liste, et on signale l'ecart avec l'usage allemand sans en faire
    une erreur.
    """
    value = attachment.af_relationship

    if value is None:
        builder.add(
            LevelId.CONTAINER,
            Severity.ERROR,
            (
                "La pièce jointe ne déclare pas de clé /AFRelationship. PDF/A-3 exige "
                "cette clé pour indiquer la nature du lien entre le PDF et le fichier "
                "incorporé."
            ),
            rule_id="FX-PDF-030",
            specification=SPEC_FACTURX,
        )
        return

    if value not in pdf_module.VALID_AF_RELATIONSHIPS:
        builder.add(
            LevelId.CONTAINER,
            Severity.ERROR,
            (
                f"La valeur de /AFRelationship « {value} » n'est pas une valeur "
                "PDF/A-3 valide. Les valeurs admises sont Source, Data, Alternative, "
                "Supplement et Unspecified."
            ),
            rule_id="FX-PDF-032",
            specification=SPEC_FACTURX,
        )
        return

    expected = profile.expected_af_relationship
    if value not in expected:
        allowed = ", ".join(expected)
        builder.add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                f"/AFRelationship vaut « {value} », alors que le profil "
                f"{profile.label} attend {allowed}."
            ),
            rule_id="FX-PDF-033",
            specification=SPEC_FACTURX,
        )
        return

    if profile.en16931_scope and value != "Alternative":
        builder.add(
            LevelId.CONTAINER,
            Severity.INFO,
            (
                f"/AFRelationship vaut « {value} », valeur admise par la "
                f"spécification Factur-X pour le profil {profile.label}. À noter "
                "toutefois que l'usage allemand (ZUGFeRD) impose « Alternative » pour "
                "ce profil : si vos factures partent aussi vers l'Allemagne, "
                "« Alternative » est le choix le plus sûr."
            ),
            rule_id="FX-PDF-034",
            specification=SPEC_FACTURX,
        )


def _xmp_facturx_findings(
    builder: ReportBuilder,
    inspection: pdf_module.PdfInspection,
    attachment: pdf_module.Attachment,
    profile: profiles.Profile,
) -> None:
    xmp = inspection.facturx_xmp
    if not xmp:
        builder.add(
            LevelId.CONTAINER,
            Severity.ERROR,
            (
                "Les métadonnées XMP ne comportent pas l'extension Factur-X. Elle "
                "porte le type de document, le nom du fichier incorporé, la version "
                "et le niveau de conformité, et permet à un destinataire de "
                "reconnaître une facture Factur-X sans ouvrir la pièce jointe."
            ),
            rule_id="FX-PDF-045",
            specification=SPEC_FACTURX,
        )
        return

    document_type = xmp.get("DocumentType")
    if document_type and document_type.strip().upper() not in {"INVOICE", "ORDER"}:
        builder.add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                f"L'extension XMP Factur-X déclare DocumentType « {document_type} », "
                "alors que « INVOICE » est attendu pour une facture."
            ),
            rule_id="FX-PDF-046",
            specification=SPEC_FACTURX,
        )

    declared_name = xmp.get("DocumentFileName")
    if declared_name and declared_name.strip() != attachment.name:
        builder.add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                f"L'extension XMP Factur-X annonce le fichier "
                f"« {declared_name} », alors que la pièce jointe trouvée s'appelle "
                f"« {attachment.name} ». Un destinataire qui se fie aux métadonnées "
                "ne trouvera pas le XML."
            ),
            rule_id="FX-PDF-047",
            specification=SPEC_FACTURX,
        )

    declared_level = (xmp.get("ConformanceLevel") or "").strip()
    tolerated = _XMP_CONFORMANCE.get(profile.code)
    if declared_level and tolerated and declared_level.upper() not in tolerated:
        builder.add(
            LevelId.CONTAINER,
            Severity.WARNING,
            (
                f"L'extension XMP Factur-X déclare le niveau de conformité "
                f"« {declared_level} », alors que le XML annonce le profil "
                f"{profile.label}. Les deux sources devraient concorder."
            ),
            rule_id="FX-PDF-048",
            specification=SPEC_FACTURX,
        )


# --------------------------------------------------------------------------
# Niveaux Schematron
# --------------------------------------------------------------------------


def _pdfa_level(
    builder: ReportBuilder,
    raw: bytes,
    is_pdf: bool,
    levels_run: list[str],
) -> verapdf.Resultat | None:
    """Niveau de conformite PDF/A reelle, par veraPDF.

    Trois issues possibles, et il importe de ne pas les confondre : le niveau peut
    etre sans objet parce que l'entree n'est pas un PDF, non execute parce que
    l'outil n'est pas disponible, ou reellement evalue. Un outil absent ne doit
    jamais se traduire par un niveau franchi.
    """
    if not is_pdf:
        builder.close_level(
            LevelId.PDFA,
            status=LevelStatus.NOT_APPLICABLE,
            reason=(
                "Un XML seul a été fourni : il n'y a pas de document PDF/A à "
                "auditer."
            ),
        )
        return None

    utilisable, motif = verapdf.configure()
    if not utilisable:
        builder.close_level(
            LevelId.PDFA,
            status=LevelStatus.SKIPPED,
            reason=(
                f"Audit non exécuté : {motif}. Les contrôles PDF/A du niveau "
                "précédent restent structurels et ne valent pas audit de "
                "conformité."
            ),
        )
        return None

    audit = verapdf.auditer(raw)
    if audit.erreur:
        builder.close_level(
            LevelId.PDFA,
            status=LevelStatus.SKIPPED,
            reason=f"Audit non abouti : {audit.erreur}.",
        )
        return audit

    for echec in audit.echecs:
        builder.add(
            LevelId.PDFA,
            Severity.ERROR,
            _message_pdfa(echec),
            rule_id=echec.code,
            xpath=echec.contexte,
            message_original=echec.description,
            message_source=MessageSource.GABARIT_FR,
            specification=(
                f"{echec.specification}, clause {echec.clause}"
                if echec.specification and echec.clause
                else echec.specification
            ),
        )

    builder.close_level(
        LevelId.PDFA,
        reason=(
            f"{audit.regles_passees} règle(s) vérifiée(s) sans écart sur "
            f"{audit.controles_passes} contrôle(s), profil « {audit.profil} », "
            f"en {audit.duree_ms:.0f} ms."
        ),
    )
    levels_run.append(str(LevelId.PDFA))
    return audit


def _message_pdfa(echec: verapdf.Echec) -> str:
    """Rend un echec PDF/A en francais, en conservant le libelle normatif.

    Les 146 regles de la norme ne sont pas traduites : leur libelle est un texte
    normatif que reformuler exposerait a le trahir. On l'encadre donc d'une phrase
    francaise qui situe la clause, et le texte d'origine reste joint au constat.
    """
    situation = _PDFA_CLAUSES.get(echec.clause or "")
    if situation:
        return f"{situation} (clause {echec.clause} de la norme ISO 19005-3)."
    return (
        f"Non-conformité PDF/A sur la clause {echec.clause or 'non précisée'} de la "
        f"norme ISO 19005-3 : {echec.description}"
    )


# Ecarts les plus courants sur des factures Factur-X, rendus en francais.
_PDFA_CLAUSES: dict[str, str] = {
    "6.6.2.1": (
        "Le document ne comporte pas de métadonnées XMP dans son catalogue, que "
        "PDF/A rend obligatoires"
    ),
    "6.6.2.3.1": (
        "Les métadonnées XMP ne déclarent pas correctement l'identifiant de "
        "conformité PDF/A"
    ),
    "6.2.11.4.1": "Une police utilisée dans le document n'est pas incorporée",
    "6.2.11.5": "Une police incorporée est incomplète",
    "6.2.2": (
        "Le document ne déclare pas d'OutputIntent, ou en déclare un invalide, "
        "alors que PDF/A impose de décrire l'espace colorimétrique de sortie"
    ),
    "6.1.3": "Le document est chiffré, ce que PDF/A interdit",
    "6.4": "Le document utilise de la transparence, que PDF/A-1 interdit",
    "6.8": (
        "Un fichier incorporé ne respecte pas les conditions posées par PDF/A-3 "
        "aux pièces jointes"
    ),
}


def _profile_level(
    builder: ReportBuilder,
    parsed: detect.XmlDocument,
    profile: profiles.Profile,
    deja_vus: set[tuple[str | None, str | None]],
    levels_run: list[str],
) -> None:
    """Niveau des regles metier propres au profil Factur-X.

    C'est le seul niveau de regles metier applicable a MINIMUM et BASIC WL, que la
    norme EN 16931 ne couvre pas. Pour les autres profils il complete le niveau
    EN 16931 avec les regles ajoutees par la FNFE.
    """
    if parsed.syntax != "CII":
        builder.close_level(
            LevelId.PROFIL,
            status=LevelStatus.NOT_APPLICABLE,
            reason=(
                "Les profils Factur-X ne concernent que la syntaxe CII. Un document "
                "UBL ne relève d'aucun profil Factur-X."
            ),
        )
        return

    if not RESOURCES.has_profile_schematron(profile.code):
        builder.close_level(
            LevelId.PROFIL,
            status=LevelStatus.NOT_APPLICABLE,
            reason=(
                f"Aucun jeu de règles de profil n'est publié pour « {profile.label} ». "
                "Les profils couverts sont MINIMUM, BASIC WL, BASIC, EN 16931 et "
                "EXTENDED."
            ),
        )
        return

    _schematron_level(
        builder,
        LevelId.PROFIL,
        key=profile.code,
        xml_text=parsed.text,
        specification=f"{SPEC_PROFIL} ({profile.label})",
        already_reported=deja_vus,
    )
    levels_run.append(str(LevelId.PROFIL))


def _schematron_level(
    builder: ReportBuilder,
    level: str,
    *,
    key: str,
    xml_text: str,
    specification: str,
    downgrade_to_warning: bool = False,
    already_reported: set[str] | None = None,
    collect_into: set[str] | None = None,
    reason_prefix: str | None = None,
) -> None:
    """Execute une feuille Schematron et verse ses constats dans un niveau.

    `already_reported` ecarte les constats dont la regle a deja ete traitee par un
    autre niveau. Le Schematron FNFE par profil reprend une grande partie des
    regles du CEN : sans ce filtre, la meme violation serait comptee deux fois.

    Le filtre porte sur le code de regle seul, sans l'emplacement : les deux
    Schematron ne designent pas toujours le meme noeud pour une meme regle, si bien
    qu'une cle incluant le chemin laisserait passer des doublons. La consequence
    assumee est qu'une regle deja signalee ne sera pas repetee ici, meme si elle
    est violee a plusieurs endroits : le niveau EN 16931 reste la reference pour
    ces regles, celui du profil n'apporte que ce qui lui est propre.
    """
    try:
        assertions = schematron.run(RESOURCES, key, xml_text)
    except schematron.SchematronFailure as exc:
        builder.close_level(
            level,
            status=LevelStatus.SKIPPED,
            reason=f"Niveau non exécuté : {exc}",
        )
        return

    duplicates = 0
    if already_reported is not None:
        retenues = []
        for assertion in assertions:
            if assertion.rule_id and assertion.rule_id in already_reported:
                duplicates += 1
                continue
            retenues.append(assertion)
        assertions = retenues

    for assertion in assertions:
        french, source = messages.translate(assertion.rule_id, assertion.text)
        severity = assertion.severity
        if downgrade_to_warning and severity == Severity.ERROR:
            severity = Severity.WARNING
        builder.add(
            level,
            severity,
            french,
            rule_id=assertion.rule_id,
            internal_rule_id=assertion.internal_id,
            xpath=assertion.location,
            message_original=(
                assertion.text if source != str(MessageSource.ORIGINAL_EN) else None
            ),
            message_source=source,
            test=assertion.test,
            specification=specification,
        )
        if collect_into is not None and assertion.rule_id:
            collect_into.add(assertion.rule_id)

    reason = reason_prefix
    if duplicates:
        complement = (
            f"{duplicates} constat(s) portant sur des règles déjà traitées au niveau "
            "EN 16931 ont été écartés, pour ne pas les compter deux fois."
        )
        reason = f"{reason} {complement}" if reason else complement
    builder.close_level(level, reason=reason)


# --------------------------------------------------------------------------
# Remarques generales
# --------------------------------------------------------------------------


def _notices(
    builder: ReportBuilder,
    inspection: pdf_module.PdfInspection | None,
    profile: profiles.Profile,
    parsed: detect.XmlDocument | None,
    is_pdf: bool,
    audit_pdfa: verapdf.Resultat | None = None,
) -> None:
    if parsed is not None and not profile.fiscally_complete and profile.note:
        builder.notice("PROFIL_INCOMPLET", Severity.WARNING, profile.note)
    elif profile.note:
        builder.notice("PROFIL", Severity.INFO, profile.note)

    if is_pdf and inspection is not None:
        # La reserve sur la portee des controles n'a plus lieu d'etre quand l'audit
        # de reference a effectivement tourne : la maintenir serait sous-vendre le
        # resultat, la retirer alors que l'audit n'a pas tourne serait le
        # sur-vendre.
        if audit_pdfa is not None and audit_pdfa.erreur is None:
            if audit_pdfa.conforme:
                builder.notice(
                    "PDFA_AUDIT",
                    Severity.INFO,
                    (
                        f"La conformité PDF/A a été auditée par veraPDF, "
                        f"l'implémentation de référence : le document satisfait les "
                        f"{audit_pdfa.regles_passees} règles du profil "
                        f"« {audit_pdfa.profil} ». Ce n'est donc pas un simple "
                        "contrôle de marqueurs."
                    ),
                )
            else:
                builder.notice(
                    "PDFA_AUDIT",
                    Severity.WARNING,
                    (
                        f"L'audit veraPDF relève {audit_pdfa.regles_en_echec} "
                        "non-conformité(s) à la norme PDF/A. Le fichier peut porter "
                        "des données de facture correctes tout en n'étant pas un "
                        "PDF/A valide, ce qui compromet son archivage à long terme."
                    ),
                )
        else:
            builder.notice("PDFA_PORTEE", Severity.INFO, PDFA_STRUCTURAL_CAVEAT)

    if parsed is not None and parsed.syntax == "UBL":
        builder.notice(
            "SYNTAXE_UBL",
            Severity.INFO,
            (
                "Le document est en UBL 2.1. Les règles EN 16931 appliquées sont "
                "celles de la liaison UBL. Factur-X, en tant que format hybride "
                "PDF plus XML, repose sur le CII : un XML UBL ne peut pas être "
                "incorporé dans un PDF Factur-X."
            ),
        )

    builder.notice(
        "PLATEFORME_AGREEE",
        Severity.INFO,
        (
            "La transmission des factures passera par une Plateforme Agréée (PA). "
            "Ce diagnostic porte sur le fichier, pas sur son acheminement."
        ),
    )
    builder.notice("AVERTISSEMENT", Severity.INFO, regulatory.DISCLAIMER)


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------


def _xsd_flavour(parsed: detect.XmlDocument, profile: profiles.Profile) -> str:
    if parsed.syntax == "UBL":
        return (
            "ubl-2.1:creditnote"
            if parsed.document_kind == "CREDIT_NOTE"
            else "ubl-2.1:invoice"
        )
    return profile.xsd_flavour or "facturx-extended"


def _guideline_xpath(parsed: detect.XmlDocument) -> str:
    if parsed.syntax == "UBL":
        return "/ubl:Invoice/cbc:CustomizationID"
    return (
        "/rsm:CrossIndustryInvoice/rsm:ExchangedDocumentContext"
        "/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"
    )


def _engine_block(started: float, levels_run: list[str]) -> dict[str, Any]:
    return {
        "name": config.APP_NAME,
        "version": config.APP_VERSION,
        "durationMs": round((time.perf_counter() - started) * 1000, 1),
        "levelsRun": levels_run,
        "artifacts": RESOURCES.artifact_summary(),
        "messageCatalogue": messages.coverage(),
    }


def _build(
    builder: ReportBuilder,
    input_info: dict[str, Any],
    document: dict[str, Any],
    started: float,
    levels_run: list[str],
    *,
    evaluable: bool,
) -> dict[str, Any]:
    report = builder.build(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        schema_version=config.REPORT_SCHEMA_VERSION,
        evaluable=evaluable,
        input_info=input_info,
        document=document,
        regulatory=regulatory.block(),
        engine=_engine_block(started, levels_run),
    )
    return report.to_dict()


def _finalise_early(
    builder: ReportBuilder,
    input_info: dict[str, Any],
    document: dict[str, Any],
    started: float,
    levels_run: list[str],
    closed: list[str],
) -> dict[str, Any]:
    for level in (LevelId.PDFA, LevelId.XSD, LevelId.EN16931, LevelId.PROFIL):
        if level not in closed:
            builder.close_level(
                level,
                status=LevelStatus.SKIPPED,
                reason="Niveau non exécuté : le fichier n'a pas pu être ouvert.",
            )
    builder.notice("AVERTISSEMENT", Severity.INFO, regulatory.DISCLAIMER)
    return _build(builder, input_info, document, started, levels_run, evaluable=False)
