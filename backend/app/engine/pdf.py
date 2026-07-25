"""Inspection du conteneur PDF/A-3 et extraction de la piece jointe XML.

Ce module ne produit aucun constat : il retourne des faits. La transformation en
erreurs et avertissements se fait dans l'orchestrateur, parce que certaines
attentes dependent du profil, lequel n'est connu qu'apres lecture du XML.

Ce que l'on verifie tient de la conformite structurelle PDF/A-3, pas d'un audit
complet au sens de veraPDF : presence et coherence des marqueurs, pas verification
exhaustive de la specification PDF/A. Le rapport le dit explicitement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lxml import etree

# Noms de piece jointe reconnus, par ordre de priorite. Le premier est celui
# attendu par la specification Factur-X courante, les suivants sont historiques.
KNOWN_INVOICE_NAMES: tuple[tuple[str, str, bool], ...] = (
    ("factur-x.xml", "Factur-X", True),
    ("zugferd-invoice.xml", "ZUGFeRD (historique)", False),
    ("xrechnung.xml", "XRechnung", False),
    ("factur-x_extended.xml", "Factur-X (variante non standard)", False),
)
EXPECTED_ATTACHMENT_NAME = "factur-x.xml"

# Nom reconnu mais qui ne designe pas une facture.
NON_INVOICE_NAMES = {"order-x.xml"}

VALID_AF_RELATIONSHIPS = {"Data", "Source", "Alternative", "Supplement", "Unspecified"}

NS_PDFAID = "http://www.aiim.org/pdfa/ns/id/"
XMP_FX_NAMESPACE_MARKER = "CrossIndustryDocument"


class PdfUnreadable(ValueError):
    """Le flux fourni n'est pas un PDF exploitable."""


@dataclass
class Attachment:
    name: str
    payload: bytes | None
    af_relationship: str | None = None
    mime_subtype: str | None = None
    declared_size: int | None = None
    referenced_by_af: bool = False
    name_matches_spec_case: bool = True
    known_as: str | None = None
    read_error: str | None = None

    @property
    def is_xml_like(self) -> bool:
        return self.name.lower().endswith(".xml")


@dataclass
class PdfInspection:
    pdf_version: str | None = None
    page_count: int = 0
    encrypted: bool = False
    attachments: list[Attachment] = field(default_factory=list)
    invoice_attachment: Attachment | None = None
    ambiguous_candidates: list[str] = field(default_factory=list)
    non_standard_name_used: bool = False
    has_document_af: bool = False
    has_output_intent: bool = False
    has_xmp: bool = False
    xmp_valid: bool = True
    pdfa_part: str | None = None
    pdfa_conformance: str | None = None
    facturx_xmp: dict[str, str] = field(default_factory=dict)
    facturx_xmp_namespace: str | None = None


def inspect(raw: bytes) -> PdfInspection:
    """Ouvre le PDF en memoire et releve tout ce qui interesse la validation."""
    import pikepdf

    result = PdfInspection()
    try:
        pdf = pikepdf.open(_BytesSource(raw))
    except pikepdf.PasswordError as exc:
        raise PdfUnreadable(
            "Le PDF est protege par un mot de passe et ne peut pas etre analyse."
        ) from exc
    except Exception as exc:  # pikepdf.PdfError et derives
        raise PdfUnreadable(f"Le fichier n'a pas pu etre ouvert comme un PDF : {exc}") from exc

    with pdf:
        result.pdf_version = pdf.pdf_version
        result.encrypted = pdf.is_encrypted
        try:
            result.page_count = len(pdf.pages)
        except Exception:
            result.page_count = 0

        af_targets = _collect_document_af(pdf)
        result.has_document_af = bool(af_targets)
        result.has_output_intent = _has_output_intent(pdf)

        result.attachments = _collect_attachments(pdf, af_targets)
        _select_invoice_attachment(result)
        _read_xmp(pdf, result)

    return result


class _BytesSource:
    """Adaptateur minimal pour ouvrir un PDF depuis des octets en memoire."""

    def __init__(self, raw: bytes) -> None:
        import io

        self._buffer = io.BytesIO(raw)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._buffer, item)

    def read(self, *args: Any) -> bytes:
        return self._buffer.read(*args)

    def seek(self, *args: Any) -> int:
        return self._buffer.seek(*args)

    def tell(self) -> int:
        return self._buffer.tell()


def _name_to_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[1:] if text.startswith("/") else text


def _string_of(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _collect_document_af(pdf: Any) -> set[int]:
    """Identifiants objet des specifications de fichier citees par /AF.

    /AF peut figurer au niveau du catalogue et au niveau des pages. On collecte
    les deux, la specification Factur-X attendant la reference au niveau document.
    """
    targets: set[int] = set()

    def harvest(container: Any) -> None:
        try:
            entries = container.get("/AF")
        except Exception:
            return
        if entries is None:
            return
        try:
            iterable = list(entries)
        except Exception:
            iterable = [entries]
        for entry in iterable:
            try:
                targets.add(entry.objgen[0])
            except Exception:
                continue

    try:
        harvest(pdf.Root)
    except Exception:
        pass
    try:
        for page in pdf.pages:
            harvest(page.obj)
    except Exception:
        pass
    return targets


def _has_output_intent(pdf: Any) -> bool:
    try:
        intents = pdf.Root.get("/OutputIntents")
        return bool(intents) and len(list(intents)) > 0
    except Exception:
        return False


def _walk_name_tree(node: Any, collected: list[Any], depth: int = 0) -> None:
    """Parcourt un arbre de noms PDF, y compris ses /Kids.

    Les generateurs anciens produisent parfois un arbre a plusieurs niveaux au
    lieu d'une feuille unique : ignorer /Kids ferait manquer la piece jointe.
    """
    if depth > 32:
        return
    try:
        names = node.get("/Names")
    except Exception:
        names = None
    if names is not None:
        try:
            items = list(names)
        except Exception:
            items = []
        for position in range(0, len(items) - 1, 2):
            collected.append((items[position], items[position + 1]))
    try:
        kids = node.get("/Kids")
    except Exception:
        kids = None
    if kids is not None:
        try:
            for kid in kids:
                _walk_name_tree(kid, collected, depth + 1)
        except Exception:
            pass


def _collect_attachments(pdf: Any, af_targets: set[int]) -> list[Attachment]:
    entries: list[Any] = []
    try:
        tree = pdf.Root.get("/Names", {}).get("/EmbeddedFiles")
    except Exception:
        tree = None
    if tree is not None:
        _walk_name_tree(tree, entries)

    attachments: list[Attachment] = []
    seen: set[int] = set()

    for key, filespec in entries:
        attachment = _read_filespec(filespec, fallback_name=_string_of(key))
        if attachment is None:
            continue
        try:
            objid = filespec.objgen[0]
            seen.add(objid)
            attachment.referenced_by_af = objid in af_targets
        except Exception:
            pass
        attachments.append(attachment)

    # Une piece jointe citee par /AF mais absente de l'arbre EmbeddedFiles reste
    # une piece jointe : certains generateurs omettent l'arbre de noms.
    for objid in af_targets:
        if objid in seen:
            continue
        filespec = _resolve_object(pdf, objid)
        if filespec is None:
            continue
        attachment = _read_filespec(filespec, fallback_name=None)
        if attachment is None:
            continue
        attachment.referenced_by_af = True
        attachments.append(attachment)

    return attachments


def _resolve_object(pdf: Any, objid: int) -> Any:
    try:
        for entry in pdf.Root.get("/AF") or []:
            if entry.objgen[0] == objid:
                return entry
    except Exception:
        return None
    return None


def _read_filespec(filespec: Any, *, fallback_name: str | None) -> Attachment | None:
    try:
        name = _string_of(filespec.get("/UF")) or _string_of(filespec.get("/F")) or fallback_name
    except Exception:
        name = fallback_name
    if not name:
        return None

    attachment = Attachment(name=name, payload=None)
    try:
        attachment.af_relationship = _name_to_str(filespec.get("/AFRelationship"))
    except Exception:
        pass

    stream = None
    try:
        embedded = filespec.get("/EF")
        if embedded is not None:
            stream = embedded.get("/F") or embedded.get("/UF")
    except Exception:
        stream = None

    if stream is None:
        attachment.read_error = "flux de la piece jointe absent (/EF manquant)"
        return attachment

    try:
        attachment.mime_subtype = _name_to_str(stream.get("/Subtype"))
    except Exception:
        pass
    try:
        params = stream.get("/Params")
        if params is not None:
            size = params.get("/Size")
            attachment.declared_size = int(size) if size is not None else None
    except Exception:
        pass
    try:
        attachment.payload = stream.read_bytes()
    except Exception as exc:
        attachment.read_error = f"flux illisible : {exc}"
    return attachment


def _select_invoice_attachment(result: PdfInspection) -> None:
    """Choisit la piece jointe a valider parmi celles presentes."""
    by_lower: dict[str, Attachment] = {}
    for attachment in result.attachments:
        by_lower.setdefault(attachment.name.lower(), attachment)

    for candidate, label, is_spec in KNOWN_INVOICE_NAMES:
        attachment = by_lower.get(candidate)
        if attachment is None or attachment.payload is None:
            continue
        attachment.known_as = label
        attachment.name_matches_spec_case = (
            attachment.name == EXPECTED_ATTACHMENT_NAME if is_spec else True
        )
        result.invoice_attachment = attachment
        break

    if result.invoice_attachment is None:
        # Aucun nom connu : on se rabat sur un XML unique, en le signalant.
        xml_candidates = [
            attachment
            for attachment in result.attachments
            if attachment.is_xml_like
            and attachment.payload is not None
            and attachment.name.lower() not in NON_INVOICE_NAMES
        ]
        if len(xml_candidates) == 1:
            result.invoice_attachment = xml_candidates[0]
            result.non_standard_name_used = True
        elif len(xml_candidates) > 1:
            result.ambiguous_candidates = [a.name for a in xml_candidates]

    known_present = [
        attachment.name
        for attachment in result.attachments
        if attachment.name.lower() in {name for name, _, _ in KNOWN_INVOICE_NAMES}
    ]
    if len(known_present) > 1:
        result.ambiguous_candidates = known_present


def _read_xmp(pdf: Any, result: PdfInspection) -> None:
    try:
        metadata = pdf.Root.get("/Metadata")
        if metadata is None:
            return
        payload = metadata.read_bytes()
    except Exception:
        return

    result.has_xmp = True
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        root = etree.fromstring(payload, parser=parser)
    except etree.XMLSyntaxError:
        result.xmp_valid = False
        return

    values: dict[tuple[str, str], str] = {}
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        qname = etree.QName(element)
        text = (element.text or "").strip()
        if text:
            values[(qname.namespace or "", qname.localname)] = text
        for attr_name, attr_value in element.attrib.items():
            if not attr_name.startswith("{"):
                continue
            attr_qname = etree.QName(attr_name)
            cleaned = (attr_value or "").strip()
            if cleaned:
                values[(attr_qname.namespace or "", attr_qname.localname)] = cleaned

    result.pdfa_part = values.get((NS_PDFAID, "part"))
    result.pdfa_conformance = values.get((NS_PDFAID, "conformance"))

    for (namespace, localname), value in values.items():
        if XMP_FX_NAMESPACE_MARKER in namespace:
            result.facturx_xmp_namespace = namespace
            result.facturx_xmp[localname] = value
