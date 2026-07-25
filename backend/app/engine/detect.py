"""Detection de la syntaxe et lecture des identifiants du document.

Le XML recu peut etre du CII ou de l'UBL. Rien ne doit supposer du CII : la
syntaxe est deduite du nom qualifie de la racine, et tout le reste du pipeline
s'aligne sur cette decision.

L'analyse XML est volontairement verrouillee : entites externes desactivees,
acces reseau interdit, DTD non chargee. Le service accepte des fichiers
arbitraires depuis Internet, une XXE ou une expansion d'entites serait sinon
triviale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lxml import etree

NS_CII = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
NS_RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
NS_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
NS_UBL_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS_UBL_CREDITNOTE = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_ZUGFERD_1 = "urn:ferd:CrossIndustryDocument:invoice:1p0"

CII_NS = {"rsm": NS_CII, "ram": NS_RAM, "udt": NS_UDT}
UBL_NS = {"cbc": NS_CBC, "cac": NS_CAC}

# Codes de type de document EN 16931 les plus courants (UNTDID 1001).
TYPE_CODES = {
    "71": "Facture d'acompte",
    "80": "Facture de debit",
    "82": "Facture commerciale metrique",
    "84": "Facture de credit",
    "102": "Facture fiscale",
    "218": "Facture finale",
    "219": "Facture de retenue",
    "261": "Avoir autofacture",
    "262": "Avoir differe",
    "295": "Facture proforma",
    "326": "Facture partielle",
    "380": "Facture commerciale",
    "381": "Avoir",
    "383": "Facture de debit",
    "384": "Facture rectificative",
    "385": "Facture consolidee",
    "386": "Facture d'acompte",
    "387": "Facture de location",
    "388": "Facture fiscale",
    "389": "Autofacturation",
    "390": "Facture de dedouanement",
    "393": "Facture d'affacturage",
    "395": "Facture de consignation",
    "575": "Facture de l'assureur",
    "623": "Facture du transitaire",
    "780": "Facture de fret",
}


class XmlNotWellFormed(ValueError):
    def __init__(self, detail: str, line: int | None = None, column: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.line = line
        self.column = column


@dataclass
class XmlDocument:
    raw: bytes
    tree: Any
    root_namespace: str
    root_localname: str
    syntax: str | None  # "CII", "UBL" ou None si non reconnue
    document_kind: str | None  # "INVOICE" ou "CREDIT_NOTE"
    legacy: str | None = None  # syntaxe historique reconnue mais hors perimetre
    guideline_id: str | None = None
    profile_id: str | None = None
    identification: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Texte XML pret pour Saxon.

        Deux nettoyages, tous deux necessaires en pratique :

        - la marque d'ordre des octets, tres repandue dans les XML produits sous
          Windows, survit au decodage sous la forme du caractere U+FEFF et fait
          echouer l'analyse avec un « content is not allowed in prolog » ;
        - la declaration `encoding="..."` contredirait le fait que Saxon recoit
          une chaine deja decodee.
        """
        decoded = self.raw.decode(self._encoding(), errors="replace")
        decoded = decoded.lstrip("﻿").lstrip()
        if decoded.startswith("<?xml"):
            end = decoded.find("?>")
            if end != -1:
                decoded = decoded[end + 2:].lstrip()
        return decoded

    def _encoding(self) -> str:
        declared = self.tree.docinfo.encoding if self.tree is not None else None
        return declared or "utf-8"


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        recover=False,
    )


def _first(node: Any, xpath: str, namespaces: dict[str, str]) -> str | None:
    found = node.xpath(xpath, namespaces=namespaces)
    if not found:
        return None
    value = found[0]
    text = value if isinstance(value, str) else (value.text or "")
    text = text.strip()
    return text or None


def parse(raw: bytes) -> XmlDocument:
    """Analyse le XML et identifie sa syntaxe. Leve XmlNotWellFormed si mal forme."""
    try:
        tree = etree.fromstring(raw, parser=_parser()).getroottree()
    except etree.XMLSyntaxError as exc:
        line = getattr(exc, "lineno", None)
        column = getattr(exc, "offset", None)
        raise XmlNotWellFormed(str(exc), line=line, column=column) from exc

    root = tree.getroot()
    qname = etree.QName(root)
    namespace = qname.namespace or ""
    localname = qname.localname

    document = XmlDocument(
        raw=raw,
        tree=tree,
        root_namespace=namespace,
        root_localname=localname,
        syntax=None,
        document_kind=None,
    )

    if namespace == NS_CII and localname == "CrossIndustryInvoice":
        document.syntax = "CII"
        _read_cii(document, root)
    elif namespace == NS_UBL_INVOICE and localname == "Invoice":
        document.syntax = "UBL"
        document.document_kind = "INVOICE"
        _read_ubl(document, root)
    elif namespace == NS_UBL_CREDITNOTE and localname == "CreditNote":
        document.syntax = "UBL"
        document.document_kind = "CREDIT_NOTE"
        _read_ubl(document, root)
    elif namespace == NS_ZUGFERD_1:
        document.legacy = "ZUGFeRD 1.0"
    return document


def _read_cii(document: XmlDocument, root: Any) -> None:
    document.guideline_id = _first(
        root,
        "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID",
        CII_NS,
    )
    document.profile_id = _first(
        root,
        "rsm:ExchangedDocumentContext/ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID",
        CII_NS,
    )
    type_code = _first(root, "rsm:ExchangedDocument/ram:TypeCode", CII_NS)
    settlement = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement"
    agreement = "rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeAgreement"
    document.identification = {
        "invoiceNumber": _first(root, "rsm:ExchangedDocument/ram:ID", CII_NS),
        "typeCode": type_code,
        "typeLabel": TYPE_CODES.get(type_code or ""),
        "issueDate": _normalise_cii_date(
            _first(
                root,
                "rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString",
                CII_NS,
            )
        ),
        "currency": _first(root, f"{settlement}/ram:InvoiceCurrencyCode", CII_NS),
        "sellerName": _first(root, f"{agreement}/ram:SellerTradeParty/ram:Name", CII_NS),
        "buyerName": _first(root, f"{agreement}/ram:BuyerTradeParty/ram:Name", CII_NS),
        "grandTotalAmount": _first(
            root,
            f"{settlement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"
            "/ram:GrandTotalAmount",
            CII_NS,
        ),
        "lineCount": len(
            root.xpath(
                "rsm:SupplyChainTradeTransaction/ram:IncludedSupplyChainTradeLineItem",
                namespaces=CII_NS,
            )
        ),
    }
    if type_code == "381":
        document.document_kind = "CREDIT_NOTE"
    else:
        document.document_kind = "INVOICE"


def _read_ubl(document: XmlDocument, root: Any) -> None:
    document.guideline_id = _first(root, "cbc:CustomizationID", UBL_NS)
    document.profile_id = _first(root, "cbc:ProfileID", UBL_NS)
    type_code = _first(root, "cbc:InvoiceTypeCode", UBL_NS) or _first(
        root, "cbc:CreditNoteTypeCode", UBL_NS
    )
    document.identification = {
        "invoiceNumber": _first(root, "cbc:ID", UBL_NS),
        "typeCode": type_code,
        "typeLabel": TYPE_CODES.get(type_code or ""),
        "issueDate": _first(root, "cbc:IssueDate", UBL_NS),
        "currency": _first(root, "cbc:DocumentCurrencyCode", UBL_NS),
        "sellerName": _first(
            root,
            "cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity"
            "/cbc:RegistrationName",
            UBL_NS,
        )
        or _first(
            root, "cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name", UBL_NS
        ),
        "buyerName": _first(
            root,
            "cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity"
            "/cbc:RegistrationName",
            UBL_NS,
        )
        or _first(
            root, "cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name", UBL_NS
        ),
        "grandTotalAmount": _first(
            root, "cac:LegalMonetaryTotal/cbc:PayableAmount", UBL_NS
        ),
        "lineCount": len(
            root.xpath("cac:InvoiceLine | cac:CreditNoteLine", namespaces=UBL_NS)
        ),
    }


def _normalise_cii_date(value: str | None) -> str | None:
    """Convertit le format 102 du CII (AAAAMMJJ) en date ISO lisible."""
    if not value:
        return None
    digits = value.strip()
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    return digits
