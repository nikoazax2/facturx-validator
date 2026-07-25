"""Execution du Schematron officiel et lecture du SVRL produit.

On n'implemente aucune regle : on execute les feuilles XSLT pre-compilees publiees
par CEN/TC 434 et on lit leur sortie SVRL. Chaque constat conserve son code de
regle, son test et son emplacement, pour rester verifiable par le lecteur du
rapport.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

SVRL = "http://purl.oclc.org/dsdl/svrl"
_SVRL_FAILED = f"{{{SVRL}}}failed-assert"
_SVRL_REPORT = f"{{{SVRL}}}successful-report"
_SVRL_TEXT = f"{{{SVRL}}}text"

_RULE_IN_TEXT = re.compile(r"^\[([A-Za-z0-9][A-Za-z0-9\-_.]*)\]\s*-?\s*(.*)$", re.S)

# Simplification des chemins renvoyes par le Schematron, du type
# /*:CrossIndustryInvoice[namespace-uri()='urn:...:100'][1]/...
_LOCATION_STEP = re.compile(r"\*:([A-Za-z0-9_.\-]+)\[namespace-uri\(\)='([^']*)'\]")

_NAMESPACE_PREFIXES = {
    "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100": "rsm",
    "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100": "ram",
    "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100": "udt",
    "urn:un:unece:uncefact:data:standard:QualifiedDataType:100": "qdt",
    "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2": "ubl",
    "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2": "ubl",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2": "cbc",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2": "cac",
}


class SchematronFailure(RuntimeError):
    """La transformation Schematron n'a pas abouti."""


@dataclass
class Assertion:
    rule_id: str | None
    severity: str  # "error" ou "warning", d'apres @flag
    text: str  # message d'origine, en anglais
    location: str | None  # chemin XPath simplifie
    location_raw: str | None
    test: str | None
    is_report: bool  # successful-report plutot que failed-assert
    # Identifiant propre au producteur du Schematron, conserve quand il differe du
    # code normalise. Le Schematron FNFE numerote ses assertions en FX-SCH-A-000121
    # tout en citant le code EN 16931 dans le message.
    internal_id: str | None = None


def run(resources, key: str, xml_text: str) -> list[Assertion]:
    """Execute la feuille identifiee par `key` sur le XML fourni.

    Saxon n'etant pas sur en usage concurrent, l'appel est serialise par le verrou
    porte par le registre d'artefacts.
    """
    executable = resources.schematron(key)
    with resources.lock:
        processor = resources.saxon_processor()
        try:
            node = processor.parse_xml(xml_text=xml_text)
        except Exception as exc:
            raise SchematronFailure(f"XML refuse par le processeur XSLT : {exc}") from exc
        try:
            svrl = executable.transform_to_string(xdm_node=node)
        except Exception as exc:
            raise SchematronFailure(f"transformation Schematron en echec : {exc}") from exc

    if not svrl:
        raise SchematronFailure("la transformation Schematron n'a produit aucune sortie")
    return parse_svrl(svrl)


def parse_svrl(svrl: str) -> list[Assertion]:
    try:
        root = etree.fromstring(
            svrl.encode("utf-8"),
            parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False),
        )
    except etree.XMLSyntaxError as exc:
        raise SchematronFailure(f"sortie SVRL illisible : {exc}") from exc

    assertions: list[Assertion] = []
    for element in root.iter(_SVRL_FAILED, _SVRL_REPORT):
        raw_text = (element.findtext(_SVRL_TEXT) or "").strip()
        raw_text = re.sub(r"\s+", " ", raw_text)
        declared_id = element.get("id")
        rule_id = declared_id
        internal_id = None
        message = raw_text
        matched = _RULE_IN_TEXT.match(raw_text)
        if matched:
            # Le code entre crochets est le code normalise, celui que connaissent
            # les lecteurs et le catalogue de traduction. Il prime sur @id, qui
            # peut n'etre qu'une numerotation interne au producteur du Schematron.
            # Cette numerotation est conservee a part, pour la tracabilite.
            rule_id = matched.group(1)
            if declared_id and declared_id != rule_id:
                internal_id = declared_id
            message = matched.group(2).strip()
        flag = (element.get("flag") or "fatal").lower()
        severity = "warning" if flag in {"warning", "info"} else "error"
        location_raw = element.get("location")
        assertions.append(
            Assertion(
                rule_id=rule_id,
                severity=severity,
                text=message,
                location=simplify_location(location_raw),
                location_raw=location_raw,
                test=element.get("test"),
                is_report=element.tag == _SVRL_REPORT,
                internal_id=internal_id,
            )
        )
    return assertions


def simplify_location(location: str | None) -> str | None:
    if not location:
        return None

    def replace(match: re.Match[str]) -> str:
        localname, namespace = match.group(1), match.group(2)
        prefix = _NAMESPACE_PREFIXES.get(namespace)
        return f"{prefix}:{localname}" if prefix else localname

    simplified = _LOCATION_STEP.sub(replace, location)
    # Les index [1] systematiques du Schematron alourdissent la lecture sans rien
    # ajouter quand l'element est unique.
    return simplified.replace("[1]", "")
