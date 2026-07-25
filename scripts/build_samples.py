#!/usr/bin/env python3
"""Construit le jeu d'echantillons de test a partir des fixtures d'origine.

Les fixtures de `backend/tests/fixtures` proviennent de sources publiques :
le PDF Factur-X et les XML par profil viennent du paquet `factur-x` (BSD), les
exemples CII et UBL viennent des artefacts EN 16931 (EUPL-1.2). Voir
backend/tests/fixtures/PROVENANCE.md.

Les echantillons derives sont produits par ce script, de facon reproductible, en
degradant volontairement un exemplaire valide. Chaque degradation vise un constat
precis, indique dans le nom du fichier et verifie par la suite de tests.

Usage :
    python scripts/build_samples.py
"""

from __future__ import annotations

import io
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "backend" / "tests" / "fixtures"
SAMPLES = ROOT / "backend" / "tests" / "samples"

VALID_PDF = "invoice_EN16931.pdf"
VALID_CII = "factur-x-en16931.xml"
MINIMUM_CII = "factur-x-minimum.xml"
VALID_UBL = "ubl-21-en16931.xml"


def read_fixture(name: str) -> bytes:
    path = FIXTURES / name
    if not path.exists():
        raise SystemExit(
            f"fixture absente : {path}\n"
            "Consultez backend/tests/fixtures/PROVENANCE.md pour la recuperer."
        )
    return path.read_bytes()


def write_sample(name: str, payload: bytes, description: str) -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    (SAMPLES / name).write_bytes(payload)
    print(f"  {name:46} {len(payload):>8} octets  {description}")


# --------------------------------------------------------------------------
# Echantillons PDF
# --------------------------------------------------------------------------


def sample_valid_pdf() -> None:
    shutil.copyfile(FIXTURES / VALID_PDF, SAMPLES / "01-valide-en16931.pdf")
    size = (SAMPLES / "01-valide-en16931.pdf").stat().st_size
    print(f"  {'01-valide-en16931.pdf':46} {size:>8} octets  Factur-X EN 16931 valide")


def sample_pdf_without_xml() -> None:
    """Retire toute piece jointe et la table /AF, sans toucher au reste du PDF.

    On obtient ce qu'un editeur produit le plus souvent par erreur : un PDF
    parfaitement lisible, mais qui ne porte aucune donnee structuree.
    """
    import pikepdf

    with pikepdf.open(io.BytesIO(read_fixture(VALID_PDF))) as pdf:
        root = pdf.Root
        if "/Names" in root and "/EmbeddedFiles" in root.Names:
            del root.Names["/EmbeddedFiles"]
        if "/AF" in root:
            del root["/AF"]
        for page in pdf.pages:
            if "/AF" in page.obj:
                del page.obj["/AF"]
        buffer = io.BytesIO()
        pdf.save(buffer)
    write_sample(
        "02-pdf-sans-xml.pdf",
        buffer.getvalue(),
        "PDF lisible, aucune piece jointe XML",
    )


def sample_minimum_profile_pdf() -> None:
    """Remplace le XML incorpore par un profil MINIMUM, XMP mis en coherence."""
    import pikepdf

    minimum = read_fixture(MINIMUM_CII)

    with pikepdf.open(io.BytesIO(read_fixture(VALID_PDF))) as pdf:
        replaced = False
        embedded = pdf.Root.Names.EmbeddedFiles
        names = list(embedded.Names)
        for position in range(0, len(names) - 1, 2):
            key, filespec = names[position], names[position + 1]
            if "factur-x.xml" not in str(key).lower():
                continue
            stream = filespec.EF.F
            stream.write(minimum)
            if "/Params" in stream:
                stream.Params.Size = len(minimum)
            replaced = True
        if not replaced:
            raise SystemExit("piece jointe factur-x.xml introuvable dans la fixture PDF")

        # Le niveau de conformite annonce dans les metadonnees doit suivre, sinon
        # l'echantillon porterait une incoherence qui n'est pas celle que l'on
        # veut illustrer.
        metadata = pdf.Root.Metadata
        xmp = metadata.read_bytes().decode("utf-8", errors="replace")
        xmp = re.sub(
            r"(<(\w+):ConformanceLevel>)[^<]*(</\2:ConformanceLevel>)",
            r"\1MINIMUM\3",
            xmp,
        )
        metadata.write(xmp.encode("utf-8"))

        buffer = io.BytesIO()
        pdf.save(buffer)

    write_sample(
        "03-profil-minimum.pdf",
        buffer.getvalue(),
        "Factur-X profil MINIMUM, non complet fiscalement",
    )


# --------------------------------------------------------------------------
# Echantillons XML
# --------------------------------------------------------------------------


def sample_xsd_invalid() -> None:
    """Insere un element absent du schema : invalide XSD, mais conforme EN 16931.

    L'inverse du cas suivant. Les deux ensemble montrent que les deux niveaux du
    rapport sont bel et bien independants.
    """
    text = read_fixture(VALID_CII).decode("utf-8")
    marker = "<ram:TypeCode>380</ram:TypeCode>"
    if marker not in text:
        raise SystemExit("marqueur TypeCode introuvable dans la fixture CII")
    altered = text.replace(
        marker,
        f"{marker}<ram:ElementQuiNExistePas>x</ram:ElementQuiNExistePas>",
        1,
    )
    write_sample(
        "04-xsd-invalide.xml",
        altered.encode("utf-8"),
        "element hors schema, XSD en echec",
    )


def sample_missing_mandatory_field() -> None:
    """Retire le nom de l'acheteur (BT-44) : valide XSD, viole BR-07."""
    text = read_fixture(VALID_CII).decode("utf-8")
    buyer = re.search(r"<ram:BuyerTradeParty>.*?</ram:BuyerTradeParty>", text, re.S)
    if not buyer:
        raise SystemExit("bloc BuyerTradeParty introuvable dans la fixture CII")
    stripped = re.sub(r"<ram:Name>.*?</ram:Name>", "", buyer.group(0), count=1, flags=re.S)
    altered = text.replace(buyer.group(0), stripped, 1)
    write_sample(
        "05-en16931-champ-obligatoire-manquant.xml",
        altered.encode("utf-8"),
        "nom acheteur absent, viole BR-07",
    )


def sample_inconsistent_totals() -> None:
    """Fausse le total TTC : valide XSD, viole les regles de calcul BR-CO."""
    text = read_fixture(VALID_CII).decode("utf-8")
    match = re.search(r"<ram:GrandTotalAmount>([\d.]+)</ram:GrandTotalAmount>", text)
    if not match:
        raise SystemExit("GrandTotalAmount introuvable dans la fixture CII")
    altered = text.replace(
        match.group(0), "<ram:GrandTotalAmount>999.99</ram:GrandTotalAmount>", 1
    )
    write_sample(
        "06-en16931-totaux-incoherents.xml",
        altered.encode("utf-8"),
        "total TTC faux, viole BR-CO-15",
    )


def sample_valid_ubl() -> None:
    payload = read_fixture(VALID_UBL)
    write_sample("07-ubl-valide.xml", payload, "UBL 2.1 EN 16931 valide")


def sample_malformed_xml() -> None:
    """Tronque le document au milieu d'une balise."""
    text = read_fixture(VALID_CII).decode("utf-8")
    truncated = text[: int(len(text) * 0.4)] + "<ram:Inach"
    write_sample(
        "08-xml-mal-forme.xml",
        truncated.encode("utf-8"),
        "XML tronque, non bien forme",
    )


def sample_unknown_profile() -> None:
    text = read_fixture(VALID_CII).decode("utf-8")
    altered = re.sub(
        r"(<ram:GuidelineSpecifiedDocumentContextParameter>\s*<ram:ID>)[^<]*(</ram:ID>)",
        r"\1urn:exemple:profil:maison:2026\2",
        text,
        count=1,
    )
    if "urn:exemple:profil:maison:2026" not in altered:
        raise SystemExit("GuidelineSpecifiedDocumentContextParameter introuvable")
    write_sample(
        "09-profil-inconnu.xml",
        altered.encode("utf-8"),
        "URN de profil non reconnu",
    )


def main() -> int:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    print("Construction des echantillons :")
    sample_valid_pdf()
    sample_pdf_without_xml()
    sample_minimum_profile_pdf()
    sample_xsd_invalid()
    sample_missing_mandatory_field()
    sample_inconsistent_totals()
    sample_valid_ubl()
    sample_malformed_xml()
    sample_unknown_profile()
    print(f"\nEchantillons ecrits dans {SAMPLES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
