#!/usr/bin/env python3
"""Recupere les artefacts de validation officiels utilises par le validateur.

Deux sources, aucune regle metier reecrite a la main :

1. Schematron EN 16931 (CEN/TC 434) publie par ConnectingEurope/eInvoicing-EN16931.
   On prend les XSLT pre-compiles fournis dans les releases, en XSLT 2.0.
   Licence : EUPL-1.2.

2. XSD Factur-X par profil et XSD UBL 2.1, extraits de la roue PyPI du paquet
   `factur-x` (BSD, Alexis de Lattre), qui suit les publications de la FNFE-MPE.
   Les XSD eux-memes sont ceux d'UN/CEFACT et d'OASIS UBL.

Le script ecrit un manifest.json qui trace version, URL et SHA256 de chaque
fichier, afin que le rapport de validation puisse citer ses sources.

Usage :
    python scripts/fetch_artifacts.py [--dest backend/resources] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

# Versions epinglees. Mettre a jour de facon deliberee : une montee de version du
# Schematron change les codes de regles renvoyes aux utilisateurs.
EN16931_VERSION = "1.3.16"
EN16931_RELEASE = f"https://github.com/ConnectingEurope/eInvoicing-EN16931/releases/download/validation-{EN16931_VERSION}"
EN16931_ZIPS = {
    "cii": f"{EN16931_RELEASE}/en16931-cii-{EN16931_VERSION}.zip",
    "ubl": f"{EN16931_RELEASE}/en16931-ubl-{EN16931_VERSION}.zip",
}
EN16931_XSLT = {
    "cii": "xslt/EN16931-CII-validation.xslt",
    "ubl": "xslt/EN16931-UBL-validation.xslt",
}

FACTURX_PKG_VERSION = "6.6"
FACTURX_PKG_JSON = f"https://pypi.org/pypi/factur-x/{FACTURX_PKG_VERSION}/json"
FACTURX_XSD_ROOT = "facturx/xsd_and_schematron"

# Schematron par profil publie par la FNFE-MPE, livre dans le meme repertoire que
# les XSD. Il porte les regles metier propres au profil, y compris pour MINIMUM et
# BASIC WL que le Schematron EN 16931 ne couvre pas. Le nom du fichier contient la
# version de la specification, on le recherche donc par motif plutot que par nom
# exact, pour ne pas casser a la prochaine publication.
FACTURX_PROFILE_SCHEMATRON = {
    "MINIMUM": "facturx-minimum",
    "BASIC_WL": "facturx-basicwl",
    "BASIC": "facturx-basic",
    "EN16931": "facturx-en16931",
    "EXTENDED": "facturx-extended",
}
# Repertoires a extraire de la roue, et point d'entree XSD de chacun.
FACTURX_FLAVOURS = {
    "facturx-minimum": "Factur-X_MINIMUM.xsd",
    "facturx-basicwl": "Factur-X_BASICWL.xsd",
    "facturx-basic": "Factur-X_BASIC.xsd",
    "facturx-en16931": "Factur-X_EN16931.xsd",
    "facturx-extended": "Factur-X_EXTENDED.xsd",
    "ubl-2.1": "maindoc/UBL-Invoice-2.1.xsd",
}
# Schematron des regles France (CTC, flux 2). Charge mais desactive par defaut,
# voir FRCTC_ENABLED dans la configuration du backend.
FRCTC_SOURCE = f"{FACTURX_XSD_ROOT}/cii-schematron-fr-ctc/BR-FR-Flux2-Schematron-CII.xslt"

USER_AGENT = "facturx-validator-artifact-fetcher/1.0"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def resolve_wheel_url() -> str:
    meta = json.loads(fetch(FACTURX_PKG_JSON))
    for entry in meta["urls"]:
        if entry["packagetype"] == "bdist_wheel":
            return entry["url"]
    raise RuntimeError(f"aucune roue trouvee pour factur-x {FACTURX_PKG_VERSION}")


def collect_en16931(dest: Path, manifest: dict) -> None:
    for syntax, url in EN16931_ZIPS.items():
        print(f"  telechargement {url}")
        blob = fetch(url)
        archive = zipfile.ZipFile(io.BytesIO(blob))
        member = EN16931_XSLT[syntax]
        payload = archive.read(member)
        target = dest / "schematron" / Path(member).name
        write(target, payload)
        manifest["artifacts"].append(
            {
                "role": f"schematron-en16931-{syntax}",
                "path": str(target.relative_to(dest)).replace("\\", "/"),
                "version": EN16931_VERSION,
                "source": url,
                "member": member,
                "sha256": sha256(payload),
                "licence": "EUPL-1.2",
                "publisher": "CEN/TC 434 via ConnectingEurope/eInvoicing-EN16931",
            }
        )
        print(f"    -> {target.name} ({len(payload) // 1024} Ko)")


def collect_factur_x(dest: Path, manifest: dict) -> None:
    url = resolve_wheel_url()
    print(f"  telechargement {url}")
    blob = fetch(url)
    archive = zipfile.ZipFile(io.BytesIO(blob))

    for flavour, entrypoint in FACTURX_FLAVOURS.items():
        prefix = f"{FACTURX_XSD_ROOT}/{flavour}/"
        members = [n for n in archive.namelist() if n.startswith(prefix) and not n.endswith("/")]
        if not members:
            raise RuntimeError(f"repertoire absent de la roue : {prefix}")
        digest = hashlib.sha256()
        total = 0
        for name in sorted(members):
            payload = archive.read(name)
            relative = name[len(prefix):]
            write(dest / "xsd" / flavour / relative, payload)
            digest.update(relative.encode())
            digest.update(payload)
            total += len(payload)
        entry_path = dest / "xsd" / flavour / entrypoint
        if not entry_path.exists():
            raise RuntimeError(f"point d'entree XSD introuvable : {entry_path}")
        manifest["artifacts"].append(
            {
                "role": f"xsd-{flavour}",
                "path": f"xsd/{flavour}",
                "entrypoint": entrypoint,
                "version": FACTURX_PKG_VERSION,
                "source": url,
                "files": len(members),
                "sha256": digest.hexdigest(),
                "licence": "BSD-3-Clause (paquet) / UN-CEFACT et OASIS UBL (schemas)",
                "publisher": "factur-x (Alexis de Lattre), schemas FNFE-MPE / UN-CEFACT / OASIS",
            }
        )
        print(f"    -> xsd/{flavour} ({len(members)} fichiers, {total // 1024} Ko)")

    collect_profile_schematron(archive, url, dest, manifest)

    payload = archive.read(FRCTC_SOURCE)
    target = dest / "fr-ctc" / Path(FRCTC_SOURCE).name
    write(target, payload)
    manifest["artifacts"].append(
        {
            "role": "schematron-fr-ctc",
            "path": str(target.relative_to(dest)).replace("\\", "/"),
            "version": FACTURX_PKG_VERSION,
            "source": url,
            "member": FRCTC_SOURCE,
            "sha256": sha256(payload),
            "licence": "BSD-3-Clause (paquet)",
            "publisher": "regles France CTC flux 2, via factur-x",
            "note": "desactive par defaut, active par FRCTC_ENABLED",
        }
    )
    print(f"    -> {target.name} ({len(payload) // 1024} Ko)")


def collect_profile_schematron(archive, url: str, dest: Path, manifest: dict) -> None:
    """Extrait le Schematron FNFE de chaque profil sous un nom normalise.

    Les fichiers d'origine s'appellent `Factur-X_1.09_EN16931.xsl` : la version y
    figure. On les reecrit en `PROFIL.xsl` pour que le backend n'ait pas a suivre
    les changements de version, celle-ci restant tracee dans le manifeste.
    """
    for profile, directory in FACTURX_PROFILE_SCHEMATRON.items():
        prefix = f"{FACTURX_XSD_ROOT}/{directory}/"
        candidates = [
            name
            for name in archive.namelist()
            if name.startswith(prefix) and name.lower().endswith(".xsl")
        ]
        if not candidates:
            raise RuntimeError(f"Schematron de profil absent pour {profile} dans {prefix}")
        if len(candidates) > 1:
            raise RuntimeError(
                f"plusieurs Schematron candidats pour {profile} : {candidates}"
            )
        member = candidates[0]
        payload = archive.read(member)
        target = dest / "schematron-profil" / f"{profile}.xsl"
        write(target, payload)

        # La feuille charge sa base de listes de codes par chemin relatif, via
        # document('FACTUR-X_<PROFIL>_codedb.xml'). Elle doit donc etre deposee a
        # cote, sous son nom d'origine : renommer la feuille sans deplacer sa base
        # ferait echouer la transformation a l'execution.
        bases = [
            name
            for name in archive.namelist()
            if name.startswith(prefix) and name.lower().endswith("_codedb.xml")
        ]
        if not bases:
            raise RuntimeError(
                f"base de listes de codes absente pour {profile} dans {prefix}"
            )
        for base in bases:
            base_payload = archive.read(base)
            write(dest / "schematron-profil" / Path(base).name, base_payload)
        manifest["artifacts"].append(
            {
                "role": f"schematron-profil-{profile}",
                "path": str(target.relative_to(dest)).replace("\\", "/"),
                "version": FACTURX_PKG_VERSION,
                "source": url,
                "member": member,
                "sha256": sha256(payload),
                "licence": "BSD-3-Clause (paquet), regles FNFE-MPE",
                "publisher": "FNFE-MPE, via factur-x",
            }
        )
        print(f"    -> schematron-profil/{profile}.xsl ({len(payload) // 1024} Ko)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dest = Path(__file__).resolve().parent.parent / "backend" / "resources"
    parser.add_argument("--dest", type=Path, default=default_dest)
    parser.add_argument("--force", action="store_true", help="vide la destination avant extraction")
    args = parser.parse_args()

    dest: Path = args.dest.resolve()
    manifest_path = dest / "manifest.json"

    if args.force and dest.exists():
        shutil.rmtree(dest)
    if manifest_path.exists() and not args.force:
        print(f"artefacts deja presents dans {dest} (utiliser --force pour reconstruire)")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "schemaVersion": "1.0",
        "en16931Version": EN16931_VERSION,
        "facturxPackageVersion": FACTURX_PKG_VERSION,
        "artifacts": [],
    }

    print("Schematron EN 16931 :")
    collect_en16931(dest, manifest)
    print("XSD Factur-X et UBL 2.1 :")
    collect_factur_x(dest, manifest)

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nmanifest ecrit : {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
