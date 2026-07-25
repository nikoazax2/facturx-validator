#!/usr/bin/env python3
"""Produit une cle d'API et l'entree de configuration correspondante.

La cle en clair n'est affichee qu'une fois, ici. Seule son empreinte est destinee
a la configuration du service : une fuite de la variable d'environnement ne
livrerait donc pas de cle utilisable.

Usage :
    python scripts/make_api_key.py --id acme --label "ACME Logiciels" \
        --plan integration [--expires 2027-12-31]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.apikeys import PLANS, generer_cle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="identifiant court, sans espace")
    parser.add_argument("--label", help="nom lisible du client")
    parser.add_argument(
        "--plan", default="integration", choices=sorted(PLANS), help="plan applique"
    )
    parser.add_argument("--expires", help="date d'expiration, AAAA-MM-JJ")
    parser.add_argument("--per-minute", type=int, help="surcharge du plafond par minute")
    parser.add_argument("--per-month", type=int, help="surcharge du quota mensuel")
    args = parser.parse_args()

    cle, empreinte = generer_cle()
    defauts = PLANS[args.plan]

    entree: dict[str, object] = {
        "id": args.id,
        "label": args.label or args.id,
        "plan": args.plan,
        "keyHash": empreinte,
    }
    if args.expires:
        entree["expires"] = args.expires
    if args.per_minute:
        entree["perMinute"] = args.per_minute
    if args.per_month:
        entree["perMonth"] = args.per_month

    print("Cle a transmettre au client, affichee une seule fois :")
    print()
    print(f"  {cle}")
    print()
    print(f"Plan {defauts['label']} : {defauts['perMinute']} par minute, "
          f"{defauts['perMonth']} par mois.")
    print(f"  {defauts['description']}")
    print()
    print("Entree a ajouter dans la variable d'environnement API_KEYS :")
    print()
    print(json.dumps([entree], indent=2, ensure_ascii=False))
    print()
    print("API_KEYS attend une liste : fusionnez cette entree avec les existantes.")
    print("Ne consignez jamais la cle en clair dans la configuration ni dans un depot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
