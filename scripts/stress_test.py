#!/usr/bin/env python3
"""Verifie la tenue du service sous charge concurrente.

Motivation precise. Le moteur XSLT Saxon repose sur un isolat GraalVM, dont
l'usage depuis plusieurs fils demande des precautions : un mauvais rattachement se
solde par une chute de la machine virtuelle native, et non par une exception
Python rattrapable. Le service sert pourtant ses requetes depuis un reservoir de
fils. Ce script confronte donc le service a un trafic reellement concurrent et
verifie que toutes les reponses restent justes.

Il verifie egalement que le plafond de validations simultanees fait son office
plutot que de laisser les requetes s'empiler.

Usage :
    python scripts/stress_test.py --url http://127.0.0.1:8080 [--fils 16] [--tours 8]
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "backend" / "tests" / "samples"

# Un echantillon par forme de traitement, pour ne pas eprouver un seul chemin.
CAS = [
    ("01-valide-en16931.pdf", "conforme"),
    ("06-en16931-totaux-incoherents.xml", "non_conforme"),
    ("07-ubl-valide.xml", "conforme"),
    ("03-profil-minimum.pdf", "conforme_avec_avertissements"),
]


def poster(url: str, nom: str, charge: bytes) -> tuple[int, dict | None, float]:
    frontiere = f"----fxv{uuid.uuid4().hex}"
    corps = b"".join(
        [
            f"--{frontiere}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{nom}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            charge,
            f"\r\n--{frontiere}--\r\n".encode(),
        ]
    )
    requete = urllib.request.Request(
        f"{url}/api/validate",
        data=corps,
        headers={"Content-Type": f"multipart/form-data; boundary={frontiere}"},
        method="POST",
    )
    debut = time.perf_counter()
    try:
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            return (
                reponse.status,
                json.loads(reponse.read()),
                (time.perf_counter() - debut) * 1000,
            )
    except urllib.error.HTTPError as exc:
        return exc.code, None, (time.perf_counter() - debut) * 1000
    except Exception:
        return 0, None, (time.perf_counter() - debut) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--fils", type=int, default=16)
    parser.add_argument("--tours", type=int, default=8)
    args = parser.parse_args()

    charges = []
    for nom, attendu in CAS:
        chemin = SAMPLES / nom
        if not chemin.exists():
            raise SystemExit(
                f"echantillon absent : {chemin}\n"
                "Executez d'abord python scripts/build_samples.py"
            )
        charges.append((nom, chemin.read_bytes(), attendu))

    travaux = [charges[index % len(charges)] for index in range(args.fils * args.tours)]
    print(
        f"{len(travaux)} requetes, {args.fils} en parallele, vers {args.url}\n"
    )

    debut = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.fils) as reservoir:
        resultats = list(
            reservoir.map(lambda t: (t[2], *poster(args.url, t[0], t[1])), travaux)
        )
    total = time.perf_counter() - debut

    codes: collections.Counter[int] = collections.Counter()
    verdicts_justes = 0
    verdicts_faux: list[str] = []
    durees: list[float] = []

    for attendu, code, rapport, duree in resultats:
        codes[code] += 1
        durees.append(duree)
        if code != 200 or rapport is None:
            continue
        obtenu = rapport.get("verdict", {}).get("code")
        if obtenu == attendu:
            verdicts_justes += 1
        else:
            verdicts_faux.append(f"attendu {attendu}, obtenu {obtenu}")

    print("Codes de reponse :")
    for code, nombre in sorted(codes.items()):
        libelle = {
            200: "succes",
            429: "plafond de debit",
            503: "service sature",
            0: "aucune reponse, service tombe",
        }.get(code, "")
        print(f"  {code} : {nombre:>4}  {libelle}")

    aboutis = codes[200]
    print(f"\nVerdicts justes : {verdicts_justes}/{aboutis}")
    for anomalie in verdicts_faux[:5]:
        print(f"  anomalie : {anomalie}")

    if durees:
        print(
            f"\nLatence : mediane {statistics.median(durees):.0f} ms, "
            f"maximum {max(durees):.0f} ms"
        )
    print(f"Debit : {len(travaux) / total:.1f} requetes par seconde sur {total:.1f} s")

    # Le service doit avoir survecu, et chaque reponse aboutie doit etre juste.
    survivant = codes[0] == 0
    justesse = not verdicts_faux and (aboutis == 0 or verdicts_justes == aboutis)
    print()
    if survivant and justesse:
        print("RESULTAT : le service a tenu, toutes les reponses abouties sont justes.")
        return 0
    if not survivant:
        print("RESULTAT : ECHEC, des requetes n'ont recu aucune reponse.")
    if not justesse:
        print("RESULTAT : ECHEC, des verdicts sont incorrects sous concurrence.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
