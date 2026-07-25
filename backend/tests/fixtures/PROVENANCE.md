# Provenance des fixtures

Ces fichiers ne sont pas de notre fait. Ce sont des exemplaires publies par les
organismes qui definissent les formats, repris ici pour que la suite de tests
s'execute sans acces reseau. Ils sont versionnes tels quels, sans modification.

Les echantillons de `../samples/` en sont derives par `scripts/build_samples.py`,
qui degrade volontairement un exemplaire valide pour produire chaque cas de test.

## Paquet `factur-x` (BSD-3-Clause, Alexis de Lattre)

Source : <https://pypi.org/project/factur-x/> version 6.6, repertoire
`tests/fixtures/` de la distribution source.

| Fichier | Contenu |
|---|---|
| `invoice_EN16931.pdf` | PDF Factur-X complet, profil EN 16931, deux pieces jointes dont `factur-x.xml`. Le XML incorpore porte une marque d'ordre des octets, ce qui en fait un cas de test utile. |
| `factur-x-minimum.xml` | XML CII, profil MINIMUM |
| `factur-x-basicwl.xml` | XML CII, profil BASIC WL |
| `factur-x-basic.xml` | XML CII, profil BASIC |
| `factur-x-en16931.xml` | XML CII, profil EN 16931 |
| `factur-x-extended.xml` | XML CII, profil EXTENDED |
| `ubl-21-en16931.xml` | XML UBL 2.1 conforme EN 16931 |
| `zugferd-comfort.xml` | XML ZUGFeRD 1.0, format historique hors perimetre, sert a verifier le message de refus |

## Artefacts EN 16931 (EUPL-1.2, CEN/TC 434)

Source : <https://github.com/ConnectingEurope/eInvoicing-EN16931> release
`validation-1.3.16`, repertoire `examples/` des archives CII et UBL.

| Fichier | Contenu |
|---|---|
| `CII_business_example_01.xml` | Exemple metier CII de reference |
| `CII_example1.xml` | Exemple CII de reference |
| `ubl-tc434-example1.xml` | Exemple UBL de reference du comite technique 434 |

## Remarque sur les donnees

Ces documents sont des exemples fictifs publies a des fins de test. Ils ne
contiennent aucune donnee reelle d'entreprise ou de personne.
