#!/usr/bin/env python3
"""Mesure le temps de validation, cible : moins de 3 secondes pour un PDF de 1 Mo.

Distingue deux regimes, parce qu'ils n'ont pas le meme sens :

- a froid, la premiere validation paie la compilation des feuilles XSLT et des
  schemas. C'est ce que subit le premier utilisateur apres un demarrage de
  conteneur, d'ou le prechauffage au demarrage du service ;
- a chaud, c'est le temps reellement vu par les utilisateurs suivants.

Usage :
    python scripts/measure_performance.py
"""

from __future__ import annotations

import io
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

SAMPLES = BACKEND / "tests" / "samples"
TARGET_MS = 3000
RUNS = 12


def incompressible(length: int) -> bytes:
    """Octets pseudo-aleatoires deterministes.

    Un rembourrage de zeros serait ecrase par la compression du PDF et la taille
    visee ne serait jamais atteinte. Un generateur congruentiel suffit a produire
    des octets que Flate ne peut pas reduire, tout en restant reproductible.
    """
    state = 0x2545F491
    output = bytearray(length)
    for position in range(length):
        state = (state * 1103515245 + 12345) & 0xFFFFFFFF
        output[position] = (state >> 16) & 0xFF
    return bytes(output)


def pad_pdf(raw: bytes, target_bytes: int) -> bytes:
    """Grossit un PDF jusqu'a la taille visee en y ajoutant un flux inerte.

    On gonfle le conteneur, pas le XML : c'est le cas courant, un PDF lourd
    d'images accompagne d'une facture de taille ordinaire.
    """
    import pikepdf

    with pikepdf.open(io.BytesIO(raw)) as pdf:
        filler = max(0, target_bytes - len(raw))
        if filler:
            stream = pdf.make_stream(incompressible(filler))
            pdf.Root["/RembourrageMesure"] = pdf.make_indirect(stream)
        buffer = io.BytesIO()
        pdf.save(buffer, compress_streams=False)
    return buffer.getvalue()


def measure(label: str, payload: bytes, validate) -> None:
    durations: list[float] = []
    for _ in range(RUNS):
        start = time.perf_counter()
        report = validate(payload, "mesure.pdf")
        durations.append((time.perf_counter() - start) * 1000)

    median = statistics.median(durations)
    worst = max(durations)
    verdict = "OK" if worst < TARGET_MS else "HORS CIBLE"
    print(
        f"  {label:34} {len(payload) / 1024:>7.0f} Ko  "
        f"median {median:>7.1f} ms  p_max {worst:>7.1f} ms  [{verdict}]"
    )
    if report["summary"]["errors"]:
        print(f"      note : {report['summary']['errors']} erreur(s) sur cet echantillon")


def main() -> int:
    valid = SAMPLES / "01-valide-en16931.pdf"
    if not valid.exists():
        raise SystemExit(
            "echantillons absents. Executez d'abord python scripts/build_samples.py"
        )
    raw = valid.read_bytes()

    from app.engine.orchestrator import validate
    from app.engine.resources import RESOURCES

    print(f"Cible : moins de {TARGET_MS} ms, {RUNS} executions par cas.\n")

    print("A froid, sans prechauffage :")
    start = time.perf_counter()
    validate(raw, "froid.pdf")
    cold = (time.perf_counter() - start) * 1000
    status = "OK" if cold < TARGET_MS else "HORS CIBLE"
    print(f"  {'premiere validation':34} {len(raw) / 1024:>7.0f} Ko  {cold:>7.1f} ms  [{status}]")

    print("\nPrechauffage explicite :")
    timings = RESOURCES.warmup()
    total = sum(timings.values())
    for key, value in sorted(timings.items(), key=lambda item: -item[1])[:6]:
        print(f"  {key:34} {value:>7.1f} ms")
    print(f"  {'total':34} {total:>7.1f} ms")

    print("\nA chaud :")
    measure("PDF Factur-X reel", raw, validate)
    measure("PDF rembourre a 1 Mo", pad_pdf(raw, 1024 * 1024), validate)
    measure("PDF rembourre a 5 Mo", pad_pdf(raw, 5 * 1024 * 1024), validate)
    measure(
        "XML CII seul",
        (BACKEND / "tests" / "fixtures" / "factur-x-en16931.xml").read_bytes(),
        validate,
    )
    measure("XML UBL seul", (SAMPLES / "07-ubl-valide.xml").read_bytes(), validate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
