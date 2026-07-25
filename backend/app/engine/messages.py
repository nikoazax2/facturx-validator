"""Messages francais des regles de validation.

Le Schematron officiel emet ses messages en anglais. Les rendre en francais est le
principal apport de cet outil pour un editeur francais, mais cela ne doit jamais
se faire au prix de la tracabilite : chaque constat conserve son code de regle et
son message d'origine, et indique la provenance de sa traduction.

Trois provenances possibles, exposees dans le champ `messageSource` du rapport :

- `catalogue_fr` : traduction redigee, verifiee terme a terme sur la norme ;
- `gabarit_fr` : traduction produite par gabarit, pour les regles de liaison
  syntaxique dont la formulation est mecanique et repetee des centaines de fois ;
- `original_en` : aucune traduction disponible, le texte anglais est conserve tel
  quel plutot que devine.
"""

from __future__ import annotations

import re

from ..report import MessageSource

# --------------------------------------------------------------------------
# Termes metier EN 16931. Sert aux messages produits par gabarit et a
# l'affichage des identifiants BT dans l'interface.
# --------------------------------------------------------------------------

BT_LABELS: dict[str, str] = {
    "BT-1": "numéro de facture",
    "BT-2": "date d'émission de la facture",
    "BT-3": "code de type de facture",
    "BT-5": "code devise de la facture",
    "BT-6": "code devise de comptabilisation de la TVA",
    "BT-7": "date d'exigibilité de la TVA",
    "BT-8": "code de date d'exigibilité de la TVA",
    "BT-9": "date d'échéance de paiement",
    "BT-10": "référence acheteur",
    "BT-11": "référence de projet",
    "BT-12": "référence du contrat",
    "BT-13": "référence de la commande",
    "BT-14": "référence de l'accusé de commande",
    "BT-24": "identifiant de spécification",
    "BT-25": "référence de la facture précédente",
    "BT-27": "nom du vendeur",
    "BT-29": "identifiant du vendeur",
    "BT-30": "identifiant légal du vendeur",
    "BT-31": "numéro de TVA du vendeur",
    "BT-32": "identifiant fiscal du vendeur",
    "BT-34": "adresse électronique du vendeur",
    "BT-40": "code pays du vendeur",
    "BT-44": "nom de l'acheteur",
    "BT-47": "identifiant légal de l'acheteur",
    "BT-48": "numéro de TVA de l'acheteur",
    "BT-49": "adresse électronique de l'acheteur",
    "BT-55": "code pays de l'acheteur",
    "BT-59": "nom du bénéficiaire du paiement",
    "BT-62": "nom du représentant fiscal du vendeur",
    "BT-63": "numéro de TVA du représentant fiscal du vendeur",
    "BT-69": "code pays du représentant fiscal",
    "BT-72": "date de livraison effective",
    "BT-73": "date de début de la période de facturation",
    "BT-74": "date de fin de la période de facturation",
    "BT-80": "code pays du lieu de livraison",
    "BT-81": "code du mode de paiement",
    "BT-84": "identifiant du compte de paiement",
    "BT-92": "montant de la remise au niveau du document",
    "BT-93": "montant de base de la remise au niveau du document",
    "BT-95": "code de catégorie de TVA de la remise au niveau du document",
    "BT-96": "taux de TVA de la remise au niveau du document",
    "BT-97": "motif de la remise au niveau du document",
    "BT-98": "code du motif de la remise au niveau du document",
    "BT-99": "montant du frais au niveau du document",
    "BT-100": "montant de base du frais au niveau du document",
    "BT-102": "code de catégorie de TVA du frais au niveau du document",
    "BT-103": "taux de TVA du frais au niveau du document",
    "BT-104": "motif du frais au niveau du document",
    "BT-105": "code du motif du frais au niveau du document",
    "BT-106": "somme des montants nets des lignes de facture",
    "BT-107": "somme des remises au niveau du document",
    "BT-108": "somme des frais au niveau du document",
    "BT-109": "montant total hors TVA",
    "BT-110": "montant total de TVA",
    "BT-111": "montant total de TVA en devise de comptabilisation",
    "BT-112": "montant total toutes taxes comprises",
    "BT-113": "montant déjà payé",
    "BT-114": "montant d'arrondi",
    "BT-115": "montant net à payer",
    "BT-116": "base d'imposition de la catégorie de TVA",
    "BT-117": "montant de TVA de la catégorie",
    "BT-118": "code de catégorie de TVA",
    "BT-119": "taux de la catégorie de TVA",
    "BT-120": "motif d'exonération de TVA",
    "BT-121": "code du motif d'exonération de TVA",
    "BT-122": "référence du document justificatif",
    "BT-126": "identifiant de la ligne de facture",
    "BT-129": "quantité facturée",
    "BT-130": "code unité de mesure de la quantité facturée",
    "BT-131": "montant net de la ligne de facture",
    "BT-134": "date de début de période de la ligne de facture",
    "BT-135": "date de fin de période de la ligne de facture",
    "BT-136": "montant de la remise de ligne",
    "BT-137": "montant de base de la remise de ligne",
    "BT-139": "motif de la remise de ligne",
    "BT-140": "code du motif de la remise de ligne",
    "BT-141": "montant du frais de ligne",
    "BT-142": "montant de base du frais de ligne",
    "BT-144": "motif du frais de ligne",
    "BT-145": "code du motif du frais de ligne",
    "BT-146": "prix net unitaire de l'article",
    "BT-148": "prix brut unitaire de l'article",
    "BT-151": "code de catégorie de TVA de l'article facturé",
    "BT-152": "taux de TVA de l'article facturé",
    "BT-153": "nom de l'article",
    "BT-157": "identifiant normalisé de l'article",
    "BT-158": "identifiant de classification de l'article",
    "BT-160": "nom de l'attribut de l'article",
    "BT-161": "valeur de l'attribut de l'article",
}

BG_LABELS: dict[str, str] = {
    "BG-3": "référence à une facture précédente",
    "BG-4": "vendeur",
    "BG-5": "adresse postale du vendeur",
    "BG-8": "adresse postale de l'acheteur",
    "BG-10": "bénéficiaire du paiement",
    "BG-11": "représentant fiscal du vendeur",
    "BG-12": "adresse postale du représentant fiscal du vendeur",
    "BG-14": "période de facturation",
    "BG-15": "adresse de livraison",
    "BG-16": "instructions de paiement",
    "BG-20": "remise au niveau du document",
    "BG-21": "frais au niveau du document",
    "BG-22": "totaux du document",
    "BG-23": "ventilation de la TVA",
    "BG-24": "document justificatif complémentaire",
    "BG-25": "ligne de facture",
    "BG-26": "période de la ligne de facture",
    "BG-27": "remise de ligne de facture",
    "BG-28": "frais de ligne de facture",
    "BG-32": "attribut de l'article",
}


def term(code: str) -> str:
    """Libelle francais d'un identifiant BT ou BG, ou le code brut si inconnu."""
    return BT_LABELS.get(code) or BG_LABELS.get(code) or code


# --------------------------------------------------------------------------
# Regles de contenu et de coherence EN 16931
# --------------------------------------------------------------------------

_CORE: dict[str, str] = {
    "BR-01": "La facture doit porter un identifiant de spécification (BT-24).",
    "BR-02": "La facture doit porter un numéro de facture (BT-1).",
    "BR-03": "La facture doit porter une date d'émission (BT-2).",
    "BR-04": "La facture doit porter un code de type de facture (BT-3).",
    "BR-05": "La facture doit porter un code devise (BT-5).",
    "BR-06": "La facture doit indiquer le nom du vendeur (BT-27).",
    "BR-07": "La facture doit indiquer le nom de l'acheteur (BT-44).",
    "BR-08": "La facture doit comporter l'adresse postale du vendeur (BG-5).",
    "BR-09": "L'adresse postale du vendeur (BG-5) doit comporter un code pays (BT-40).",
    "BR-10": "La facture doit comporter l'adresse postale de l'acheteur (BG-8).",
    "BR-11": "L'adresse postale de l'acheteur doit comporter un code pays (BT-55).",
    "BR-12": "La facture doit porter la somme des montants nets des lignes (BT-106).",
    "BR-13": "La facture doit porter le montant total hors TVA (BT-109).",
    "BR-14": "La facture doit porter le montant total toutes taxes comprises (BT-112).",
    "BR-15": "La facture doit porter le montant net à payer (BT-115).",
    "BR-16": "La facture doit comporter au moins une ligne de facture (BG-25).",
    "BR-17": (
        "Le nom du bénéficiaire du paiement (BT-59) est obligatoire dès lors que le "
        "bénéficiaire (BG-10) diffère du vendeur (BG-4)."
    ),
    "BR-18": (
        "Le nom du représentant fiscal du vendeur (BT-62) est obligatoire dès lors "
        "que la facture désigne un représentant fiscal (BG-11)."
    ),
    "BR-19": (
        "L'adresse postale du représentant fiscal du vendeur (BG-12) est obligatoire "
        "dès lors que la facture désigne un représentant fiscal (BG-11)."
    ),
    "BR-20": (
        "L'adresse postale du représentant fiscal du vendeur (BG-12) doit comporter "
        "un code pays (BT-69) dès lors que la facture désigne un représentant fiscal "
        "(BG-11)."
    ),
    "BR-21": "Chaque ligne de facture (BG-25) doit porter un identifiant de ligne (BT-126).",
    "BR-22": "Chaque ligne de facture (BG-25) doit porter une quantité facturée (BT-129).",
    "BR-23": (
        "Chaque ligne de facture (BG-25) doit porter un code d'unité de mesure de la "
        "quantité facturée (BT-130)."
    ),
    "BR-24": "Chaque ligne de facture (BG-25) doit porter un montant net de ligne (BT-131).",
    "BR-25": "Chaque ligne de facture (BG-25) doit indiquer le nom de l'article (BT-153).",
    "BR-26": (
        "Chaque ligne de facture (BG-25) doit indiquer le prix net unitaire de "
        "l'article (BT-146)."
    ),
    "BR-27": "Le prix net unitaire de l'article (BT-146) ne peut pas être négatif.",
    "BR-28": "Le prix brut unitaire de l'article (BT-148) ne peut pas être négatif.",
    "BR-29": (
        "Lorsque la date de début (BT-73) et la date de fin (BT-74) de la période de "
        "facturation sont toutes deux renseignées, la date de fin doit être "
        "postérieure ou égale à la date de début."
    ),
    "BR-30": (
        "Lorsque la date de début (BT-134) et la date de fin (BT-135) de la période "
        "d'une ligne sont toutes deux renseignées, la date de fin doit être "
        "postérieure ou égale à la date de début."
    ),
    "BR-31": (
        "Chaque remise au niveau du document (BG-20) doit porter un montant de remise "
        "(BT-92)."
    ),
    "BR-32": (
        "Chaque remise au niveau du document (BG-20) doit porter un code de catégorie "
        "de TVA (BT-95)."
    ),
    "BR-33": (
        "Chaque remise au niveau du document (BG-20) doit porter un motif (BT-97) ou "
        "un code de motif (BT-98)."
    ),
    "BR-36": (
        "Chaque frais au niveau du document (BG-21) doit porter un montant de frais "
        "(BT-99)."
    ),
    "BR-37": (
        "Chaque frais au niveau du document (BG-21) doit porter un code de catégorie "
        "de TVA (BT-102)."
    ),
    "BR-38": (
        "Chaque frais au niveau du document (BG-21) doit porter un motif (BT-104) ou "
        "un code de motif (BT-105)."
    ),
    "BR-41": "Chaque remise de ligne (BG-27) doit porter un montant de remise (BT-136).",
    "BR-42": (
        "Chaque remise de ligne (BG-27) doit porter un motif (BT-139) ou un code de "
        "motif (BT-140)."
    ),
    "BR-43": "Chaque frais de ligne (BG-28) doit porter un montant de frais (BT-141).",
    "BR-44": (
        "Chaque frais de ligne (BG-28) doit porter un motif (BT-144) ou un code de "
        "motif (BT-145)."
    ),
    "BR-45": (
        "Chaque ventilation de TVA (BG-23) doit porter une base d'imposition (BT-116)."
    ),
    "BR-46": (
        "Chaque ventilation de TVA (BG-23) doit porter un montant de TVA (BT-117)."
    ),
    "BR-47": (
        "Chaque ventilation de TVA (BG-23) doit être définie par un code de catégorie "
        "de TVA (BT-118)."
    ),
    "BR-48": (
        "Chaque ventilation de TVA (BG-23) doit porter un taux de TVA (BT-119), sauf "
        "si la facture n'est pas soumise à la TVA."
    ),
    "BR-49": (
        "Les instructions de paiement (BG-16) doivent préciser le code du mode de "
        "paiement (BT-81)."
    ),
    "BR-50": (
        "L'identifiant du compte de paiement (BT-84) est obligatoire dès lors que la "
        "facture comporte des informations de virement (BG-16)."
    ),
    "BR-51": (
        "Une facture ne doit jamais contenir un numéro de carte de paiement complet. "
        "Les règles de sécurité PCI limitent l'affichage aux six premiers et quatre "
        "derniers chiffres."
    ),
    "BR-52": (
        "Chaque document justificatif complémentaire (BG-24) doit porter une référence "
        "(BT-122)."
    ),
    "BR-53": (
        "Lorsque le code devise de comptabilisation de la TVA (BT-6) est présent, le "
        "montant total de TVA dans cette devise (BT-111) doit être renseigné."
    ),
    "BR-54": (
        "Chaque attribut d'article (BG-32) doit porter un nom (BT-160) et une valeur "
        "(BT-161)."
    ),
    "BR-55": (
        "Chaque référence à une facture précédente (BG-3) doit porter le numéro de "
        "cette facture (BT-25)."
    ),
    "BR-56": (
        "Chaque représentant fiscal du vendeur (BG-11) doit porter un numéro de TVA "
        "(BT-63)."
    ),
    "BR-57": "Chaque adresse de livraison (BG-15) doit porter un code pays (BT-80).",
    "BR-61": (
        "Lorsque le mode de paiement (BT-81) désigne un virement SEPA, un virement "
        "national ou un virement international hors SEPA, l'identifiant du compte de "
        "paiement (BT-84) est obligatoire."
    ),
    "BR-62": (
        "L'adresse électronique du vendeur (BT-34) doit porter un identifiant de "
        "schéma."
    ),
    "BR-63": (
        "L'adresse électronique de l'acheteur (BT-49) doit porter un identifiant de "
        "schéma."
    ),
    "BR-64": (
        "L'identifiant normalisé de l'article (BT-157) doit porter un identifiant de "
        "schéma."
    ),
    "BR-65": (
        "L'identifiant de classification de l'article (BT-158) doit porter un "
        "identifiant de schéma."
    ),
    "BR-CO-03": (
        "La date d'exigibilité de la TVA (BT-7) et le code de date d'exigibilité "
        "(BT-8) sont mutuellement exclusifs."
    ),
    "BR-CO-04": (
        "Chaque ligne de facture (BG-25) doit être rattachée à un code de catégorie "
        "de TVA (BT-151)."
    ),
    "BR-CO-05": (
        "Le code du motif de remise (BT-98) et le motif de remise (BT-97) doivent "
        "désigner le même type de remise."
    ),
    "BR-CO-06": (
        "Le code du motif de frais (BT-105) et le motif de frais (BT-104) doivent "
        "désigner le même type de frais."
    ),
    "BR-CO-07": (
        "Le code du motif de remise de ligne (BT-140) et le motif de remise de ligne "
        "(BT-139) doivent désigner le même type de remise."
    ),
    "BR-CO-08": (
        "Le code du motif de frais de ligne (BT-145) et le motif de frais de ligne "
        "(BT-144) doivent désigner le même type de frais."
    ),
    "BR-CO-09": (
        "Les numéros de TVA du vendeur (BT-31), de son représentant fiscal (BT-63) et "
        "de l'acheteur (BT-48) doivent être préfixés par le code pays ISO 3166-1 "
        "alpha-2 correspondant. La Grèce peut utiliser le préfixe EL."
    ),
    "BR-CO-10": (
        "Somme des montants nets des lignes (BT-106) = somme des montants nets de "
        "chaque ligne (BT-131)."
    ),
    "BR-CO-11": (
        "Somme des remises au niveau du document (BT-107) = somme des montants de "
        "remise (BT-92)."
    ),
    "BR-CO-12": (
        "Somme des frais au niveau du document (BT-108) = somme des montants de frais "
        "(BT-99)."
    ),
    "BR-CO-13": (
        "Montant total hors TVA (BT-109) = somme des montants nets des lignes (BT-131) "
        "moins somme des remises (BT-107) plus somme des frais (BT-108)."
    ),
    "BR-CO-14": (
        "Montant total de TVA (BT-110) = somme des montants de TVA par catégorie "
        "(BT-117)."
    ),
    "BR-CO-15": (
        "Montant total toutes taxes comprises (BT-112) = montant total hors TVA "
        "(BT-109) plus montant total de TVA (BT-110)."
    ),
    "BR-CO-16": (
        "Montant net à payer (BT-115) = montant total toutes taxes comprises (BT-112) "
        "moins montant déjà payé (BT-113) plus montant d'arrondi (BT-114)."
    ),
    "BR-CO-17": (
        "Montant de TVA de la catégorie (BT-117) = base d'imposition (BT-116) x taux "
        "de TVA (BT-119) / 100, arrondi à deux décimales."
    ),
    "BR-CO-18": (
        "La facture doit comporter au moins une ventilation de la TVA (BG-23)."
    ),
    "BR-CO-19": (
        "Lorsque la période de facturation (BG-14) est utilisée, la date de début "
        "(BT-73) ou la date de fin (BT-74) doit être renseignée, ou les deux."
    ),
    "BR-CO-20": (
        "Lorsque la période d'une ligne (BG-26) est utilisée, la date de début "
        "(BT-134) ou la date de fin (BT-135) doit être renseignée, ou les deux."
    ),
    "BR-CO-21": (
        "Chaque remise au niveau du document (BG-20) doit porter un motif (BT-97) ou "
        "un code de motif (BT-98), ou les deux."
    ),
    "BR-CO-22": (
        "Chaque frais au niveau du document (BG-21) doit porter un motif (BT-104) ou "
        "un code de motif (BT-105), ou les deux."
    ),
    "BR-CO-23": (
        "Chaque remise de ligne (BG-27) doit porter un motif (BT-139) ou un code de "
        "motif (BT-140), ou les deux."
    ),
    "BR-CO-24": (
        "Chaque frais de ligne (BG-28) doit porter un motif (BT-144) ou un code de "
        "motif (BT-145), ou les deux."
    ),
    "BR-CO-26": (
        "Pour que l'acheteur puisse identifier automatiquement le fournisseur, "
        "l'identifiant du vendeur (BT-29), son identifiant légal (BT-30) ou son "
        "numéro de TVA (BT-31) doit être présent."
    ),
    "BR-CL-01": (
        "Le code de type de document doit appartenir aux listes de codes UNTDID 1001 "
        "relatives aux factures et aux avoirs."
    ),
    "BR-CL-03": "L'attribut currencyID doit utiliser un code ISO 4217 alpha-3.",
    "BR-CL-04": "Le code devise de la facture doit utiliser un code ISO 4217 alpha-3.",
    "BR-CL-05": "Le code devise de la TVA doit utiliser un code ISO 4217 alpha-3.",
    "BR-CL-06": (
        "Le code de date d'exigibilité de la TVA doit utiliser une restriction de "
        "UNTDID 2475."
    ),
    "BR-CL-07": (
        "L'identifiant de schéma de l'identifiant d'objet doit utiliser une "
        "restriction de UNTDID 1153."
    ),
    "BR-CL-08": (
        "Le code de sujet doit utiliser une restriction de la liste UNTDID 4451."
    ),
    "BR-CL-10": (
        "Tout identifiant de schéma d'identifiant doit appartenir à la liste ISO 6523 "
        "ICD."
    ),
    "BR-CL-11": (
        "Tout identifiant de schéma d'identifiant d'enregistrement doit appartenir à "
        "la liste ISO 6523 ICD."
    ),
    "BR-CL-13": (
        "L'identifiant de schéma de la classification de l'article doit appartenir à "
        "la liste UNTDID 7143."
    ),
    "BR-CL-14": "Les codes pays de la facture doivent utiliser la liste ISO 3166-1.",
    "BR-CL-15": "Les codes pays de la facture doivent utiliser la liste ISO 3166-1.",
    "BR-CL-16": (
        "Les modes de paiement de la facture doivent utiliser la liste UNTDID 4461."
    ),
    "BR-CL-17": (
        "Les catégories de TVA de la facture doivent utiliser la liste UNCL 5305."
    ),
    "BR-CL-18": (
        "Les catégories de TVA de la facture doivent utiliser la liste UNCL 5305."
    ),
    "BR-CL-19": (
        "Les motifs de remise codés doivent appartenir à la liste UNCL 5189."
    ),
    "BR-CL-20": "Les motifs de frais codés doivent appartenir à la liste UNCL 7161.",
    "BR-CL-21": (
        "L'identifiant de schéma de l'identifiant normalisé de l'article doit "
        "appartenir à la liste ISO 6523 ICD."
    ),
    "BR-CL-22": (
        "L'identifiant de schéma du code de motif d'exonération doit appartenir à la "
        "liste VATEX de la Commission européenne."
    ),
    "BR-CL-23": (
        "Le code unité doit suivre la recommandation UN/ECE 20 avec l'extension "
        "recommandation 21."
    ),
    "BR-CL-24": "Le code MIME doit utiliser la liste MIMEMediaType.",
    "BR-CL-25": (
        "L'identifiant de schéma de l'adresse électronique doit appartenir à la liste "
        "EAS de la Commission européenne."
    ),
    "BR-CL-26": (
        "L'identifiant de schéma du lieu de livraison doit appartenir à la liste "
        "ISO 6523 ICD."
    ),
    "BR-B-01": (
        "Une facture dont le code de catégorie de TVA (BT-151, BT-95 ou BT-102) est "
        "« paiement scindé » doit être une facture domestique italienne."
    ),
    "BR-B-02": (
        "Une facture qui utilise la catégorie de TVA « paiement scindé » ne peut pas "
        "comporter par ailleurs des éléments au taux normal."
    ),
    "BR-IC-11": (
        "Lorsque la ventilation de la TVA (BG-23) porte le code « livraison "
        "intracommunautaire », la date de livraison effective (BT-72) ou la période de "
        "facturation (BG-14) doit être renseignée."
    ),
    "BR-IC-12": (
        "Lorsque la ventilation de la TVA (BG-23) porte le code « livraison "
        "intracommunautaire », le code pays du lieu de livraison (BT-80) doit être "
        "renseigné."
    ),
    "BR-O-11": (
        "Une facture comportant une ventilation de TVA (BG-23) « hors champ de la "
        "TVA » ne peut pas comporter d'autre ventilation de TVA."
    ),
    "BR-O-12": (
        "Une facture comportant une ventilation de TVA (BG-23) « hors champ de la "
        "TVA » ne peut pas comporter de ligne (BG-25) rattachée à une autre catégorie."
    ),
    "BR-O-13": (
        "Une facture comportant une ventilation de TVA (BG-23) « hors champ de la "
        "TVA » ne peut pas comporter de remise au niveau du document (BG-20) "
        "rattachée à une autre catégorie."
    ),
    "BR-O-14": (
        "Une facture comportant une ventilation de TVA (BG-23) « hors champ de la "
        "TVA » ne peut pas comporter de frais au niveau du document (BG-21) rattaché "
        "à une autre catégorie."
    ),
}


# --------------------------------------------------------------------------
# Familles de categories de TVA.
#
# Les dix premieres regles de chaque famille suivent une trame commune, avec des
# variantes explicitement parametrees plutot que devinees : cardinalite de la
# ventilation, contrainte de taux, identifiants exiges, mode de calcul de la base
# et traitement du motif d'exoneration.
# --------------------------------------------------------------------------

_VAT_FAMILIES: dict[str, dict[str, str]] = {
    "S": {
        "label": "taux normal",
        "cardinality": "at_least_one",
        "rate": "positive",
        "parties": "seller_any",
        "base": "per_rate",
        "tax": "computed",
        "exemption": "forbidden",
    },
    "Z": {
        "label": "taux zéro",
        "cardinality": "exactly_one",
        "rate": "zero",
        "parties": "seller_any",
        "base": "global",
        "tax": "zero",
        "exemption": "forbidden",
    },
    "E": {
        "label": "exonéré de TVA",
        "cardinality": "exactly_one",
        "rate": "zero",
        "parties": "seller_any",
        "base": "global",
        "tax": "zero",
        "exemption": "required_free",
    },
    "AE": {
        "label": "autoliquidation de la TVA",
        "cardinality": "exactly_one",
        "rate": "zero",
        "parties": "seller_and_buyer",
        "base": "global",
        "tax": "zero",
        "exemption": "required_named",
    },
    "G": {
        "label": "export hors Union européenne",
        "cardinality": "exactly_one",
        "rate": "zero",
        "parties": "seller_or_representative",
        "base": "global",
        "tax": "zero",
        "exemption": "required_named",
    },
    "IC": {
        "label": "livraison intracommunautaire",
        "cardinality": "exactly_one",
        "rate": "zero",
        "parties": "seller_or_representative_and_buyer",
        "base": "global",
        "tax": "zero",
        "exemption": "required_named",
    },
    "O": {
        "label": "hors champ de la TVA",
        "cardinality": "exactly_one",
        "rate": "absent",
        "parties": "no_vat_identifier",
        "base": "global",
        "tax": "zero",
        "exemption": "required_named",
    },
    "AF": {
        "label": "IGIC (îles Canaries)",
        "cardinality": "at_least_one",
        "rate": "positive_line_only",
        "parties": "seller_any",
        "base": "per_rate",
        "tax": "computed",
        "exemption": "forbidden",
    },
    "AG": {
        "label": "IPSI (Ceuta et Melilla)",
        "cardinality": "at_least_one",
        "rate": "zero_or_positive",
        "parties": "seller_any",
        "base": "per_rate",
        "tax": "computed",
        "exemption": "forbidden",
    },
}

_PARTY_CLAUSES = {
    "seller_any": (
        "le numéro de TVA du vendeur (BT-31), son identifiant fiscal (BT-32) ou le "
        "numéro de TVA de son représentant fiscal (BT-63)"
    ),
    "seller_or_representative": (
        "le numéro de TVA du vendeur (BT-31) ou celui de son représentant fiscal "
        "(BT-63)"
    ),
    "seller_and_buyer": (
        "le numéro de TVA du vendeur (BT-31), son identifiant fiscal (BT-32) ou le "
        "numéro de TVA de son représentant fiscal (BT-63), ainsi que le numéro de TVA "
        "de l'acheteur (BT-48) ou son identifiant légal (BT-47)"
    ),
    "seller_or_representative_and_buyer": (
        "le numéro de TVA du vendeur (BT-31) ou celui de son représentant fiscal "
        "(BT-63), ainsi que le numéro de TVA de l'acheteur (BT-48)"
    ),
}

_RATE_CONSTRAINTS = {
    "zero": "doit être égal à zéro",
    "positive": "doit être strictement supérieur à zéro",
    "positive_line_only": "doit être strictement supérieur à zéro",
    "zero_or_positive": "doit être égal ou supérieur à zéro",
}

_CONTEXTS = {
    5: ("une ligne de facture (BG-25)", "BT-151", "le taux de TVA de l'article facturé (BT-152)"),
    6: (
        "une remise au niveau du document (BG-20)",
        "BT-95",
        "le taux de TVA de la remise (BT-96)",
    ),
    7: (
        "un frais au niveau du document (BG-21)",
        "BT-102",
        "le taux de TVA du frais (BT-103)",
    ),
}


def _vat_family_messages(family: str, spec: dict[str, str]) -> dict[str, str]:
    label = spec["label"]
    messages: dict[str, str] = {}

    quantifier = (
        "exactement une" if spec["cardinality"] == "exactly_one" else "au moins une"
    )
    messages[f"BR-{family}-01"] = (
        f"Une facture dont une ligne (BG-25), une remise (BG-20) ou un frais (BG-21) "
        f"porte le code de catégorie de TVA « {label} » doit comporter "
        f"{quantifier} ventilation de la TVA (BG-23) avec ce même code (BT-118)."
    )

    if spec["parties"] == "no_vat_identifier":
        for index, (context, code, _) in _CONTEXTS.items():
            slot = {5: "02", 6: "03", 7: "04"}[index]
            messages[f"BR-{family}-{slot}"] = (
                f"Une facture dont {context} porte le code de catégorie de TVA "
                f"« {label} » ({code}) ne doit comporter ni numéro de TVA du vendeur "
                f"(BT-31), ni numéro de TVA de son représentant fiscal (BT-63), ni "
                f"numéro de TVA de l'acheteur (BT-48)."
            )
    else:
        clause = _PARTY_CLAUSES[spec["parties"]]
        for index, (context, code, _) in _CONTEXTS.items():
            slot = {5: "02", 6: "03", 7: "04"}[index]
            messages[f"BR-{family}-{slot}"] = (
                f"Une facture dont {context} porte le code de catégorie de TVA "
                f"« {label} » ({code}) doit comporter {clause}."
            )

    for index, (context, code, rate_term) in _CONTEXTS.items():
        slot = {5: "05", 6: "06", 7: "07"}[index]
        if spec["rate"] == "absent":
            messages[f"BR-{family}-{slot}"] = (
                f"Dans {context} portant le code de catégorie de TVA « {label} » "
                f"({code}), {rate_term} ne doit pas être renseigné."
            )
            continue
        constraint = spec["rate"]
        if constraint == "positive_line_only" and index != 5:
            constraint = "zero_or_positive"
        messages[f"BR-{family}-{slot}"] = (
            f"Dans {context} portant le code de catégorie de TVA « {label} » "
            f"({code}), {rate_term} {_RATE_CONSTRAINTS[constraint]}."
        )

    if spec["base"] == "per_rate":
        messages[f"BR-{family}-08"] = (
            f"Pour chaque taux de TVA distinct (BT-119) associé au code de catégorie "
            f"« {label} », la base d'imposition (BT-116) doit être égale à la somme "
            f"des montants nets de lignes (BT-131), plus les frais au niveau du "
            f"document (BT-99), moins les remises au niveau du document (BT-92), "
            f"limitée aux éléments portant ce code et ce taux."
        )
    else:
        messages[f"BR-{family}-08"] = (
            f"Dans la ventilation de la TVA (BG-23) portant le code « {label} », la "
            f"base d'imposition (BT-116) doit être égale à la somme des montants nets "
            f"de lignes (BT-131), moins les remises au niveau du document (BT-92), "
            f"plus les frais au niveau du document (BT-99), limitée aux éléments "
            f"portant ce code."
        )

    if spec["tax"] == "zero":
        messages[f"BR-{family}-09"] = (
            f"Dans la ventilation de la TVA (BG-23) portant le code « {label} », le "
            f"montant de TVA (BT-117) doit être égal à zéro."
        )
    else:
        messages[f"BR-{family}-09"] = (
            f"Dans la ventilation de la TVA (BG-23) portant le code « {label} », le "
            f"montant de TVA (BT-117) doit être égal à la base d'imposition (BT-116) "
            f"multipliée par le taux de TVA (BT-119)."
        )

    if spec["exemption"] == "forbidden":
        messages[f"BR-{family}-10"] = (
            f"Une ventilation de la TVA (BG-23) portant le code « {label} » ne doit "
            f"comporter ni code de motif d'exonération (BT-121) ni motif "
            f"d'exonération (BT-120)."
        )
    elif spec["exemption"] == "required_free":
        messages[f"BR-{family}-10"] = (
            f"Une ventilation de la TVA (BG-23) portant le code « {label} » doit "
            f"comporter un code de motif d'exonération (BT-121) ou un motif "
            f"d'exonération (BT-120)."
        )
    else:
        messages[f"BR-{family}-10"] = (
            f"Une ventilation de la TVA (BG-23) portant le code « {label} » doit "
            f"comporter un code de motif d'exonération (BT-121) désignant "
            f"« {label} », ou le motif d'exonération correspondant en texte (BT-120)."
        )

    return messages


RULES_FR: dict[str, str] = dict(_CORE)
for _family, _spec in _VAT_FAMILIES.items():
    for _rule_id, _message in _vat_family_messages(_family, _spec).items():
        # Les messages explicites du catalogue restent prioritaires sur le gabarit.
        RULES_FR.setdefault(_rule_id, _message)


# --------------------------------------------------------------------------
# Regles de liaison syntaxique (CII-SR, CII-DT, UBL-CR, UBL-SR, UBL-DT).
#
# Environ 1300 regles dont la formulation est mecanique. Elles sont traduites par
# gabarit et signalees comme telles dans le rapport.
# --------------------------------------------------------------------------

_ELEMENT = r"([@A-Za-z0-9_:.\-/ ]+?)"

_CARDINALITES = {
    "once": "plus d'une fois",
    "twice": "plus de deux fois",
    "three times": "plus de trois fois",
}


def _decimales(groups: tuple[str, ...]) -> str:
    """Regles BR-DEC : nombre de decimales maximal d'un montant."""
    libelle, code, maximum = groups[0], groups[1], groups[2]
    connu = BT_LABELS.get(code)
    nom = f"{connu} ({code})" if connu else f"{libelle} ({code})"
    return (
        f"Le nombre de décimales du champ {nom} ne doit pas dépasser {maximum}."
    )


def _cardinalite(groups: tuple[str, ...]) -> str:
    element, quantite = groups[0], groups[1].lower()
    return (
        f"L'élément {element} ne doit pas apparaître "
        f"{_CARDINALITES.get(quantite, f'plus de {quantite}')}."
    )


def _cardinalite_dans(groups: tuple[str, ...]) -> str:
    element, contenant = groups[0], groups[1]
    return (
        f"L'élément {element} ne doit pas apparaître plus d'une fois dans {contenant}."
    )


# Chaque entree associe un motif a une chaine de format ou a une fonction, quand
# la traduction demande une recherche de libelle.
_TEMPLATES: tuple[tuple[re.Pattern[str], object], ...] = (
    # -- liaison UBL : « A UBL invoice should not include the X »
    (
        re.compile(
            r"^A UBL (?:invoice|credit note) should not include "
            r"(?:the )?(.+?) or it should be (.+?)\.?$",
            re.I,
        ),
        # Le fragment capture est un nom nu, parfois au pluriel : la formulation
        # avec deux points reste correcte dans tous les cas, contrairement a un
        # article que l'on devrait accorder.
        "Une facture UBL ne devrait pas comporter : {0}. Si elle le fait, la valeur "
        "attendue est {1}.",
    ),
    (
        re.compile(
            r"^A UBL (?:invoice|credit note) should not include (?:the )?(.+?)\.?$",
            re.I,
        ),
        "Une facture UBL ne devrait pas comporter : {0}.",
    ),
    # -- nombre de decimales
    (
        re.compile(
            r"^The allowed maximum number of decimals for the (.+?) "
            r"\((BT-\d+)\) is (\d+)\.?$",
            re.I,
        ),
        _decimales,
    ),
    # -- presence interdite
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+attribute should not be present\.?$", re.I),
        "L'attribut {0} ne devrait pas être présent dans ce profil.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+should not be present\.?$", re.I),
        "L'élément {0} ne devrait pas être présent dans ce profil.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+(?:must|shall)?\s*not be present\.?$", re.I),
        "L'élément {0} ne doit pas être présent dans ce profil.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+(?:shall|must|should) not be used\.?$", re.I),
        "L'élément {0} ne doit pas être utilisé dans ce profil.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+is not allowed\.?$", re.I),
        "L'élément {0} n'est pas autorisé dans ce profil.",
    ),
    # -- cardinalites
    (
        re.compile(
            rf"^-?\s*{_ELEMENT}\s+shall occur at most once in\s+(.+?)\.?$", re.I
        ),
        _cardinalite_dans,
    ),
    (
        re.compile(
            rf"^-?\s*{_ELEMENT}\s+(?:shall|should|must) occur maximum\s+(.+?)\.?$",
            re.I,
        ),
        _cardinalite,
    ),
    (
        re.compile(
            rf"^-?\s*{_ELEMENT}\s+(?:shall|should|must) not occur more than\s+(.+?)\.?$",
            re.I,
        ),
        _cardinalite,
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+(?:must|shall) exist exactly once\.?$", re.I),
        "L'élément {0} doit être présent exactement une fois.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+should exist exactly once\.?$", re.I),
        "L'élément {0} devrait être présent exactement une fois.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+should exist maximum once\.?$", re.I),
        "L'élément {0} ne devrait pas être présent plus d'une fois.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+(?:must|shall) exist maximum once\.?$", re.I),
        "L'élément {0} ne doit pas être présent plus d'une fois.",
    ),
    (
        re.compile(
            rf"^-?\s*{_ELEMENT}\s+of\s+(.+?)\s+shall exist maximum once\.?$", re.I
        ),
        _cardinalite_dans,
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+should exist at least once\.?$", re.I),
        "L'élément {0} devrait être présent au moins une fois.",
    ),
    (
        re.compile(rf"^-?\s*{_ELEMENT}\s+(?:must|shall) exist at least once\.?$", re.I),
        "L'élément {0} doit être présent au moins une fois.",
    ),
    (
        re.compile(rf"^-?\s*only one {_ELEMENT}\s+(?:shall|should) be present\.?$", re.I),
        "Un seul élément {0} peut être présent.",
    ),
    # -- cardinalites exactes, formulation du Schematron FNFE par profil
    (
        re.compile(
            r"^Element '([^']+)' must occur exactly (\d+) times?\.?$",
            re.I,
        ),
        "L'élément {0} doit être présent exactement {1} fois dans ce profil.",
    ),
    (
        re.compile(
            r"^Element '([^']+)' must occur at (?:most|maximum) (\d+) times?\.?$",
            re.I,
        ),
        "L'élément {0} ne doit pas être présent plus de {1} fois dans ce profil.",
    ),
    (
        re.compile(
            r"^Element '([^']+)' must occur at least (\d+) times?\.?$",
            re.I,
        ),
        "L'élément {0} doit être présent au moins {1} fois dans ce profil.",
    ),
    (
        re.compile(r"^Element '([^']+)' must not occur\.?$", re.I),
        "L'élément {0} ne doit pas être présent dans ce profil.",
    ),
    # -- types de donnees UBL
    (
        re.compile(
            r"^Binary object elements shall contain the (.+?) attribute\.?$", re.I
        ),
        "Les éléments de type objet binaire doivent porter l'attribut {0}.",
    ),
    (
        re.compile(
            r"^Amounts shall be decimal up to (\w+) fraction digits\.?$", re.I
        ),
        "Les montants doivent être des décimaux comportant au plus deux chiffres "
        "après la virgule.",
    ),
)


def _apply_templates(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", text).strip()
    for pattern, replacement in _TEMPLATES:
        matched = pattern.match(cleaned)
        if not matched:
            continue
        groups = tuple((group or "").strip() for group in matched.groups())
        if callable(replacement):
            return replacement(groups)
        return replacement.format(*groups)
    return None


# --------------------------------------------------------------------------
# Messages du validateur de schema.
#
# lxml formule ses erreurs XSD en anglais et sous forme libre : il n'y a pas de
# code de regle a traduire, seulement un petit nombre de tournures recurrentes.
# On les rend en francais et on conserve le texte d'origine dans le rapport.
# --------------------------------------------------------------------------

_XSD_NAMESPACES = {
    "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100": "rsm",
    "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100": "ram",
    "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100": "udt",
    "urn:un:unece:uncefact:data:standard:QualifiedDataType:100": "qdt",
    "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2": "ubl",
    "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2": "ubl",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2": "cbc",
    "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2": "cac",
}


def shorten_qnames(text: str) -> str:
    """Remplace les URI d'espaces de noms par leurs prefixes usuels."""
    result = text
    for namespace, prefix in _XSD_NAMESPACES.items():
        result = result.replace(f"{{{namespace}}}", f"{prefix}:")
    return result


_XSD_TEMPLATES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^Element '([^']+)': This element is not expected\.\s*Expected is "
            r"(?:one of )?\(\s*(.+?)\s*\)\.?$",
            re.S,
        ),
        "L'élément {0} n'est pas attendu à cet endroit. Attendu ici : {1}.",
    ),
    (
        re.compile(r"^Element '([^']+)': This element is not expected\.?$", re.S),
        "L'élément {0} n'est pas attendu à cet endroit dans ce profil.",
    ),
    (
        re.compile(
            r"^Element '([^']+)': Missing child element\(s\)\.\s*Expected is "
            r"(?:one of )?\(\s*(.+?)\s*\)\.?$",
            re.S,
        ),
        "Il manque un élément obligatoire sous {0}. Attendu : {1}.",
    ),
    (
        re.compile(
            r"^Element '([^']+)': \[facet '([^']+)'\] The value '(.*?)' is not "
            r"(?:accepted by|allowed by) the (?:pattern|facet) '(.*?)'\.?$",
            re.S,
        ),
        "La valeur « {2} » de {0} ne respecte pas la contrainte {1} « {3} ».",
    ),
    (
        re.compile(
            r"^Element '([^']+)': '(.*?)' is not a valid value of the (?:atomic |local )?"
            r"type '(.*?)'\.?$",
            re.S,
        ),
        "La valeur « {1} » de {0} n'est pas valide pour le type {2}.",
    ),
    (
        re.compile(
            r"^Element '([^']+)', attribute '([^']+)': '(.*?)' is not a valid value of "
            r"the (?:atomic |local )?type '(.*?)'\.?$",
            re.S,
        ),
        "La valeur « {2} » de l'attribut {1} sur {0} n'est pas valide pour le type {3}.",
    ),
    (
        re.compile(
            r"^Element '([^']+)': The attribute '([^']+)' is required but missing\.?$",
            re.S,
        ),
        "L'attribut obligatoire {1} est absent de l'élément {0}.",
    ),
    (
        re.compile(
            r"^Element '([^']+)', attribute '([^']+)': The attribute '[^']+' is not "
            r"allowed\.?$",
            re.S,
        ),
        "L'attribut {1} n'est pas autorisé sur l'élément {0}.",
    ),
    (
        re.compile(
            r"^Element '([^']+)': Character content other than whitespace is not "
            r"allowed because the content type is '([^']+)'\.?$",
            re.S,
        ),
        "L'élément {0} ne doit contenir que des sous-éléments, pas du texte.",
    ),
    (
        re.compile(r"^Element '([^']+)': No matching global declaration available.*$", re.S),
        (
            "L'élément racine {0} ne correspond à aucune déclaration du schéma : le "
            "document ne relève pas de ce schéma."
        ),
    ),
)


def translate_xsd(original: str) -> tuple[str, str]:
    """Retourne (message francais, provenance) pour une erreur de schema."""
    cleaned = re.sub(r"\s+", " ", shorten_qnames(original)).strip()
    for pattern, replacement in _XSD_TEMPLATES:
        matched = pattern.match(cleaned)
        if matched:
            groups = [group.strip() if group else "" for group in matched.groups()]
            return replacement.format(*groups), str(MessageSource.GABARIT_FR)
    return cleaned, str(MessageSource.ORIGINAL_EN)


def translate(rule_id: str | None, original: str) -> tuple[str, str]:
    """Retourne (message francais, provenance) pour une assertion Schematron."""
    if rule_id and rule_id in RULES_FR:
        return RULES_FR[rule_id], str(MessageSource.CATALOGUE_FR)
    templated = _apply_templates(original)
    if templated:
        return templated, str(MessageSource.GABARIT_FR)
    return original, str(MessageSource.ORIGINAL_EN)


def coverage() -> dict[str, int]:
    """Taille du catalogue, exposee par l'API pour rendre la couverture verifiable.

    Les gabarits couvrent les regles de liaison syntaxique, bien plus nombreuses
    que les regles redigees mais de formulation mecanique.
    """
    return {
        "cataloguedRules": len(RULES_FR),
        "templates": len(_TEMPLATES),
        "xsdTemplates": len(_XSD_TEMPLATES),
    }
