"""Validation structurelle XSD.

Premier des deux niveaux metier, et volontairement distinct du second : un
document peut etre structurellement valide et violer la norme EN 16931, ou
l'inverse. Le schema retenu est celui du profil detecte, ce qui fait porter a ce
niveau les cardinalites propres au profil (champs obligatoires, elements
interdits) sans reecrire de regle a la main.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree


@dataclass
class XsdError:
    message: str
    line: int | None
    column: int | None
    xpath: str | None
    domain: str | None = None
    type_name: str | None = None


@dataclass
class XsdResult:
    valid: bool
    flavour: str
    errors: list[XsdError]


def validate(tree: etree._ElementTree, schema: etree.XMLSchema, flavour: str) -> XsdResult:
    valid = bool(schema.validate(tree))
    errors: list[XsdError] = []
    if not valid:
        for entry in schema.error_log:
            errors.append(
                XsdError(
                    message=entry.message,
                    line=entry.line or None,
                    column=getattr(entry, "column", None) or None,
                    xpath=_readable_path(getattr(entry, "path", None)),
                    domain=getattr(entry, "domain_name", None),
                    type_name=getattr(entry, "type_name", None),
                )
            )
    return XsdResult(valid=valid, flavour=flavour, errors=errors)


_PREFIXES = {
    "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100": "rsm",
    "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100": "ram",
    "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100": "udt",
    "urn:un:unece:uncefact:data:standard:QualifiedDataType:100": "qdt",
    "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2": "ubl",
    "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2": "ubl",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2": "cbc",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2": "cac",
}


def _readable_path(path: str | None) -> str | None:
    """Remplace les URI de namespace de lxml par les prefixes usuels.

    lxml produit /{urn:...:100}CrossIndustryInvoice/{urn:...}ExchangedDocument, ce
    qui est exact mais illisible dans un rapport destine a un developpeur.
    """
    if not path:
        return None
    readable = path
    for namespace, prefix in _PREFIXES.items():
        readable = readable.replace(f"{{{namespace}}}", f"{prefix}:")
    return readable
