# Notices des composants de tiers

Document a livrer avec le produit. Il recense les composants de tiers, leur
licence, et **ce que chaque licence exige concretement** en cas de
commercialisation. Verifie le 25 juillet 2026.

Aucun composant retenu n'impose de placer le produit sous licence libre. Aucun
n'est sous copyleft fort de type GPL ou AGPL.

## Obligations a respecter

Trois seulement, toutes simples.

1. **Livrer ce fichier** avec le produit, ou son equivalent dans la
   documentation.
2. **Joindre le texte de la licence MPL-2.0**, pour SaxonC-HE et pikepdf. Le
   texte officiel est disponible sur <https://mozilla.org/MPL/2.0/>.
3. **Joindre le texte de l'EUPL-1.2** avec les artefacts Schematron EN 16931,
   ainsi que la mention de leur origine.

Si l'une de ces bibliotheques venait a etre **modifiee**, la MPL-2.0 imposerait
de mettre a disposition les sources modifiees du seul fichier concerne. En
l'etat, aucune ne l'est : elles sont utilisees telles que publiees.

## Moteur de validation

| Composant | Version | Licence | Usage commercial | Remarque |
|---|---|---|---|---|
| SaxonC-HE (`saxonche`) | 13.0.0 | MPL-2.0 | Autorise | Executeur XSLT 2.0 et 3.0. Le paquet ne declare pas sa licence dans ses metadonnees, elle est celle de Saxon-HE. Contient des composants Unicode ICU, couverts par la licence Unicode, permissive. Marque incompatible avec les licences secondaires, donc non combinable avec du code GPL. |
| lxml | 6.0.2 | BSD-3-Clause | Autorise | Analyse XML et validation XSD. |
| pikepdf | 10.1.0 | MPL-2.0 | Autorise | Lecture du modele objet PDF, adosse a QPDF (Apache-2.0). |
| Pillow | 12.x | MIT-CMU | Autorise | Dependance de pikepdf. |

## Service web

| Composant | Licence | Usage commercial |
|---|---|---|
| FastAPI | MIT | Autorise |
| Starlette | BSD-3-Clause | Autorise |
| uvicorn | BSD-3-Clause | Autorise |
| python-multipart | Apache-2.0 | Autorise |

## Interface

| Composant | Licence | Usage commercial |
|---|---|---|
| Vue 3 | MIT | Autorise |
| Vite | MIT | Autorise |

## Artefacts de validation

Ce sont des donnees, pas du code lie au produit. Ils sont recuperes a la
construction de l'image et redistribues sans modification.

| Artefact | Origine | Licence | Ce qu'il faut faire |
|---|---|---|---|
| Schematron EN 16931, liaisons CII et UBL, version 1.3.16 | CEN/TC 434, via ConnectingEurope/eInvoicing-EN16931 | EUPL-1.2 | Joindre le texte de l'EUPL-1.2 et citer l'origine. L'EUPL couvre l'artefact, pas le logiciel qui l'execute sans le modifier. |
| Schemas XSD Factur-X par profil, version 1.09 | FNFE-MPE, via le paquet `factur-x` | BSD-3-Clause pour le paquet, schemas UN/CEFACT librement redistribuables | Conserver la mention de copyright. |
| Schematron Factur-X par profil, version 1.09 | FNFE-MPE, via le paquet `factur-x` | Idem | Idem. |
| Schemas UBL 2.1 | OASIS | Libre redistribution | Conserver la mention. |
| Schematron France CTC, flux 2 | Via le paquet `factur-x` | BSD-3-Clause | Charge mais desactive par defaut. |

## Fichiers d'exemple

Les fixtures de test proviennent du paquet `factur-x` (BSD-3-Clause) et des
artefacts EN 16931 (EUPL-1.2). Elles servent aux tests et **n'ont pas a etre
livrees** avec le produit. Voir `backend/tests/fixtures/PROVENANCE.md`.

## Points a trancher avant commercialisation

- **Marque Factur-X.** Factur-X est un nom porte par la FNFE-MPE. Verifier
  aupres d'elle les conditions d'usage du nom dans une denomination commerciale
  ou un nom de domaine. Decrire une fonction (« validation de factures au format
  Factur-X ») est different de s'approprier le nom comme marque de produit.
- **Mention de conformite.** Ne pas laisser entendre que l'outil delivre une
  certification. Le rapport porte deja cette reserve, la communication
  commerciale doit s'y tenir.
- **Responsabilite.** Un editeur qui integre l'API et se fie a son verdict peut
  invoquer un prejudice en cas de faux negatif. Prevoir une clause de limitation
  de responsabilite dans les conditions de service.
