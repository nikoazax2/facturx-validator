# Validateur Factur-X

Outil web public et gratuit qui valide une facture électronique au format
Factur-X. Aucun compte, aucun stockage : le fichier est traité en mémoire et
libéré avec la réponse.

Déposez un PDF Factur-X ou un XML seul, et le service rend un rapport qui
distingue jusqu'à cinq niveaux de contrôle, chaque constat portant son code de
règle, son chemin XPath, sa gravité et un message en français.

## Ce que l'outil vérifie

| Niveau | Objet | Moyen |
|---|---|---|
| Conteneur PDF/A-3 | Extraction du XML incorporé, `AFRelationship`, type MIME, tableau `/AF`, métadonnées XMP Factur-X, marqueurs PDF/A | Lecture du modèle objet PDF |
| Conformité PDF/A | Conformité réelle à ISO 19005-3 | veraPDF, l'implémentation de référence. Optionnel, voir plus bas |
| Validité XSD | Structure, cardinalités et types de données, au regard du schéma du profil détecté | XSD Factur-X par profil, XSD UBL 2.1 |
| Conformité EN 16931 | Règles métier de la norme européenne | Schematron officiel CEN/TC 434, exécuté sans réécriture |
| Règles du profil Factur-X | Règles métier propres au profil détecté | Schematron officiel FNFE-MPE, un jeu par profil |

Aucune règle métier n'est réimplémentée : ces niveaux exécutent des artefacts
publiés par les organismes qui définissent les formats.

Un dernier niveau, les règles France du flux entre Plateformes Agréées, est
chargé mais neutralisé par défaut. Voir `FRCTC_ENABLED` plus bas.

### Pourquoi un niveau de profil distinct

Le Schematron FNFE reprend une grande partie des règles du CEN et y ajoute les
contraintes propres à chaque profil. Deux conséquences.

D'abord, **MINIMUM et BASIC WL reçoivent enfin un contrôle métier**. Ces profils
ne déclarent pas de conformité EN 16931, le niveau correspondant est donc sans
objet pour eux, et ils ne bénéficiaient auparavant que du contrôle de schéma. Le
niveau de profil est leur seul niveau de règles métier.

Ensuite, **les deux jeux se recouvrent et il faut dédoublonner**. Une règle déjà
traitée au niveau EN 16931 n'est pas répétée au niveau du profil, sans quoi la
même violation serait comptée deux fois : sur l'échantillon
`06-en16931-totaux-incoherents.xml`, le total passerait de 2 à 4 erreurs. Le
nombre de constats écartés est indiqué dans le rapport, il n'est pas masqué.

Le filtre porte sur le code de règle seul, pas sur l'emplacement, les deux
Schematron ne désignant pas toujours le même nœud pour une même règle. Une règle
déjà signalée n'est donc pas répétée même si elle est violée à plusieurs endroits :
le niveau EN 16931 reste la référence pour ces règles.

### Audit PDF/A réel, optionnel

Les contrôles du premier niveau portent sur les marqueurs Factur-X et leur
cohérence. Ils ne disent pas si le fichier est réellement conforme à ISO 19005-3 :
cela demande un validateur dédié. veraPDF, l'implémentation de référence, peut
être branché pour cela.

```bash
docker build --target service-verapdf -t facturx-validator:verapdf .
docker run --rm -p 8080:8080 facturx-validator:verapdf
```

Hors conteneur, renseigner `VERAPDF_ENABLED=1` et `VERAPDF_JAR`.

Le PDF est transmis à veraPDF **par l'entrée standard**, jamais par un fichier
temporaire : la promesse de ne rien écrire sur disque est préservée, et un test le
vérifie en isolant le répertoire temporaire du processus.

**Désactivé par défaut, pour une raison mesurée.** Un appel coûte environ 1,5 s,
presque entièrement du démarrage de machine virtuelle Java, contre 33 ms pour tout
le reste de la validation. L'image gagne par ailleurs environ 300 Mo. Pour un
service qui aurait besoin de cet audit en permanence, la bonne réponse n'est pas
d'appeler un processus à chaque requête mais de maintenir un service veraPDF chaud
à côté, ce que permet son interface REST.

Ce que l'audit apporte, vérifié sur les échantillons du dépôt : l'exemplaire
Factur-X de référence est **réellement conforme PDF/A-3b**, 146 règles satisfaites
sur 31 173 contrôles. Un PDF ordinaire est correctement rejeté, avec la clause de
la norme en cause. Les 146 libellés de règles ne sont pas traduits, un texte
normatif se trahissant facilement à la reformulation : les écarts les plus courants
sur des factures reçoivent une phrase française, les autres conservent le libellé
d'origine, toujours accompagné de la clause.

Quand l'audit n'a pas pu tourner, le niveau est déclaré non exécuté avec son motif,
jamais franchi, et la réserve sur la portée des contrôles reste affichée.

### Les niveaux sont indépendants

C'est le point que le rapport rend explicite. Un fichier peut être valide au
regard de son schéma et violer la norme, ou l'inverse. Deux échantillons du dépôt
le démontrent :

- `04-xsd-invalide.xml` : XSD en échec, EN 16931 franchi ;
- `05-en16931-champ-obligatoire-manquant.xml` : XSD franchi, EN 16931 en échec.

## Démarrage rapide

Prérequis : Python 3.12 ou plus récent, Node 20 ou plus récent.

```bash
# 1. Récupérer les artefacts officiels (Schematron EN 16931, XSD)
python scripts/fetch_artifacts.py

# 2. Backend
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt   # Windows
# .venv/bin/python -m pip install -r backend/requirements.txt     # Linux et macOS

# 3. Interface
cd frontend && npm install && npm run build && cd ..

# 4. Lancer
cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --port 8080
```

L'interface est alors servie sur <http://127.0.0.1:8080/>.

Pour développer l'interface avec rechargement à chaud, lancer le backend sur le
port 8080 puis `npm run dev` dans `frontend/` : Vite relaie `/api` vers le
backend.

### Docker

```bash
docker build -t facturx-validator .
docker run --rm -p 8080:8080 facturx-validator
```

Les artefacts sont récupérés pendant la construction, jamais au démarrage : une
instance qui démarre ne dépend ni de GitHub ni de PyPI, et la version des règles
est figée dans l'image.

### Google Cloud Run

```bash
PROJET=mon-projet ./scripts/deploy_cloud_run.sh
# ou, avec l'audit PDF/A :
PROJET=mon-projet ./scripts/deploy_cloud_run.sh --verapdf
```

Le script affiche d'abord ce qu'il va faire, avertit si `REDIS_URL` manque, puis
demande une confirmation explicite avant de créer un service public et facturé.
Les secrets passent par un fichier temporaire et non par la ligne de commande,
qui est visible dans la liste des processus.

Deux réglages méritent une explication.

`--min-instances 1` évite le démarrage à froid. Sans instance chaude, la première
requête après une mise en veille paie la compilation des feuilles XSLT et des
schémas, soit environ 1,2 s de plus. Ce n'est pas dramatique, mais c'est inutile.

`--concurrency 16` tient compte du fait que les validations passent par un fil
unique, voir la section suivante. Chaque validation coûtant environ 33 ms une fois
les artefacts compilés, une concurrence de 16 laisse une marge confortable. La
montée en charge se fait par le nombre d'instances, pas par le nombre de workers.

`--memory 1Gi` couvre les schémas compilés en mémoire, dont UBL 2.1 qui pèse
5 Mo de XSD, et le fichier reçu, plafonné à 10 Mo.

### Modèle d'exécution

Les validations s'exécutent sur un **fil unique et permanent**, distinct de la
boucle d'événements. Deux raisons convergentes.

Une validation est un calcul bloquant de quelques dizaines de millisecondes. La
laisser sur la boucle d'événements y bloquerait tout le reste, sondes de santé et
réponses d'erreur comprises. C'était le cas dans une version antérieure : la sonde
de santé attendait derrière le calcul en cours.

Le moteur XSLT Saxon repose par ailleurs sur un isolat GraalVM dont le rattachement
aux fils demande des précautions : un mauvais rattachement fait tomber la machine
virtuelle native, et non lever une exception rattrapable. Un fil unique rend cette
contrainte structurellement satisfaite, au lieu de reposer sur un verrou dont on
espérait qu'il suffise.

Le plafond `MAX_CONCURRENT_VALIDATIONS` borne alors la profondeur de la file
d'attente. Au-delà, le service rend `503` immédiatement plutôt que de laisser un
appelant attendre jusqu'à expiration.

Vérifié par `python scripts/stress_test.py`, qui confronte le service à un trafic
réellement concurrent : 96 requêtes à 8 en parallèle passent toutes avec des
verdicts justes, à 37 requêtes par seconde, et la sonde de santé continue de
répondre pendant la charge. Avec une file volontairement réduite à 4, 89 requêtes
sur 96 reçoivent un refus immédiat, ce qui est le comportement attendu.

## API

### `POST /api/validate`

`multipart/form-data`, champ `file`. Accepte `.pdf` et `.xml`, 10 Mo maximum.

```bash
curl -X POST -F "file=@facture.pdf" http://127.0.0.1:8080/api/validate
```

Réponse `200` avec le rapport, y compris pour un fichier non conforme : une
non-conformité est un résultat d'analyse, pas une erreur HTTP. Les codes d'erreur
sont réservés aux problèmes de requête.

| Code | Situation |
|---|---|
| `415` `EXTENSION_NON_SUPPORTEE` | Extension autre que `.pdf` ou `.xml` |
| `413` `FICHIER_TROP_VOLUMINEUX` | Au-delà de 10 Mo |
| `400` `FICHIER_VIDE` | Fichier de taille nulle |
| `429` `TROP_DE_REQUETES` | Plafond par appelant dépassé, avec `Retry-After` |
| `503` `SERVICE_SATURE` | Plafond de validations simultanées atteint |
| `503` `ARTEFACTS_INDISPONIBLES` | Artefacts non récupérés avant le démarrage |

### Limitation de débit

Le service est gratuit et anonyme : rien n'identifie un appelant abusif, et chaque
validation consomme du temps processeur Saxon sérialisé. Deux protections
distinctes.

| Protection | Défaut | Risque couvert |
|---|---|---|
| Plafond par appelant | 20 par minute, rafale de 8 | Une source unique monopolise le service |
| Validations simultanées | 4 | Trafic soudain, même légitime, qui allonge les files |

Le dépassement du plafond rend `429 TROP_DE_REQUETES` avec un en-tête
`Retry-After`, et le message oriente vers l'accès par clé. La saturation rend
`503 SERVICE_SATURE` : un refus immédiat vaut mieux qu'une attente qui expire.

**Aucune adresse IP n'est conservée.** L'adresse sert à calculer une empreinte de
8 octets, salée par une valeur aléatoire tirée au démarrage du processus.
L'empreinte ne permet pas de remonter à l'adresse, et le sel disparaît avec le
processus. Le nombre d'appelants suivis est plafonné, les plus anciens étant
oubliés, pour borner la mémoire.

Derrière un proxy, activer `TRUST_PROXY_HEADERS=1` pour lire l'adresse dans
`X-Forwarded-For`. Sans cela, l'adresse du proxy serait prise pour celle du client
et tous les appelants partageraient un même plafond. À l'inverse, activer ce
réglage sans proxy de confiance permettrait de forger l'en-tête et de contourner
la limitation.

Sans compteur partagé, les plafonds sont **locaux à l'instance** : avec dix
instances, le plafond effectif est multiplié par dix. Renseigner `REDIS_URL` suffit
à les rendre globaux, voir la section suivante.

### Identification du logiciel émetteur

Un PDF déclare le logiciel qui l'a produit, dans `/Creator`, `/Producer` et
`xmp:CreatorTool`. Le rapport le remonte, et les métriques le croisent avec le
verdict.

C'est une métadonnée technique sur un logiciel, sans rapport avec les données de la
facture ni avec une personne : rien n'est demandé au visiteur et la promesse de
confidentialité reste intacte.

Ce que cela donne, dans `GET /api/metrics`, champ `issuingSoftware` : pour chaque
logiciel rencontré, le nombre de factures analysées, le nombre de non conformes et
le ratio. Autrement dit, quels logiciels du marché produisent du Factur-X invalide,
et dans quelle proportion. Cette donnée n'est disponible nulle part ailleurs.

Le libellé retenu privilégie l'application d'origine sur la bibliothèque qui a
écrit le PDF, cette dernière étant souvent commune à des logiciels très différents.
Le nombre de valeurs suivies est plafonné, la valeur venant du fichier déposé.

### Manifestation d'intérêt

Le visiteur peut demander à être recontacté. Sur sa seule initiative, après le
rapport, jamais avant, et avec un consentement explicite non préconché.

```bash
export LEADS_WEBHOOK_URL=https://votre-crm.example/hooks/facturx
export LEADS_CONTROLLER="Votre société, adresse, courriel de contact"
```

**La fonction reste inactive tant que ces deux valeurs manquent**, et l'interface ne
la propose pas. Une destination, sans quoi on recueillerait une adresse sans savoir
où elle va. Un responsable de traitement, sans quoi le visiteur ne saurait pas à
qui il confie son adresse ni à qui réclamer son effacement.

Ce qui est transmis : l'adresse saisie, le logiciel, le secteur et le volume
déclarés, tous facultatifs, et les faits techniques de la validation, verdict,
profil, syntaxe et codes de règles en échec.

Ce qui ne l'est jamais : le fichier, son nom, son empreinte, et **toute donnée
figurant dans la facture**. Ni le vendeur, ni l'acheteur, ni le numéro, ni les
montants.

Le filtre est construit par liste blanche et non par exclusion : une future clé du
rapport contenant une donnée de facture ne se retrouverait pas transmise par oubli.
Un test le vérifie sur des données réelles, en s'assurant d'abord que le rapport
contient bien ces données, sans quoi le test ne prouverait rien.

Les mentions affichées au visiteur viennent du service et non du code de
l'interface : elles engagent, elles doivent donc refléter la configuration réelle.

### Compteurs partagés

Deux faiblesses se résolvent au même endroit. Les quotas mensuels tenus en mémoire
repartent de zéro à chaque redémarrage d'instance, ce qui interdit de facturer. Les
plafonds de débit tenus en mémoire ignorent les autres instances.

```bash
export REDIS_URL=redis://:motdepasse@hote:6379/0
```

Cela suffit : les quotas deviennent persistants et communs à toutes les instances,
et les plafonds de débit s'appliquent à l'échelle du service. `GET /api/health`
annonce l'état du compteur, et `GET /api/key` dit explicitement si le décompte fait
foi.

L'interface reste volontairement minimale, incrémenter et lire, pour qu'un autre
adossement, Firestore ou une table, se substitue sans toucher au reste du code.

**En cas d'indisponibilité du compteur partagé, le service laisse passer.** Bloquer
un client sous contrat parce que notre compteur est tombé serait plus dommageable
qu'un bref dépassement, et le seau à jetons local continue de protéger l'instance.
L'incident est journalisé et visible dans l'état de santé. C'est un choix, pas un
oubli.

### Accès par clé

L'outil public sert de vitrine : un éditeur y dépose un fichier à la main. Celui
qui veut valider un lot ou brancher la validation sur son intégration continue a
besoin d'autre chose. C'est l'objet de l'accès par clé, et c'est le chemin de
conversion du produit.

| Plan | Par minute | Par mois | Usage visé |
|---|---|---|---|
| `essai` | 60 | 500 | Découverte et tests d'intégration |
| `integration` | 120 | 50 000 | Validation continue dans une chaîne de production |
| `volume` | 600 | 1 000 000 | Validation de masse, reprise de parc, plateformes |

Chaque clé peut surcharger les plafonds de son plan et porter une date
d'expiration.

#### Créer une clé

```bash
python scripts/make_api_key.py --id acme --label "ACME Logiciels" \
  --plan integration --expires 2027-12-31
```

La clé en clair n'est affichée qu'une fois. **La configuration ne reçoit que son
empreinte SHA-256** : une fuite de la variable d'environnement ne livre donc pas
de clé utilisable.

```bash
export API_KEYS='[{"id":"acme","label":"ACME Logiciels","plan":"integration",
  "keyHash":"afb957…"}]'
```

Une déclaration erronée est signalée au démarrage sans empêcher le service public
de fonctionner : l'accès par clé reste simplement inactif.

#### Utiliser une clé

```bash
curl -X POST \
  -H "X-API-Key: fxv_…" \
  -F "file=@facture.pdf" \
  https://votre-domaine/api/validate
```

`Authorization: Bearer fxv_…` est également accepté.

Les réponses portent les en-têtes utiles à un intégrateur :

| En-tête | Contenu |
|---|---|
| `X-Plan` | Plan appliqué |
| `X-RateLimit-Limit` | Plafond par minute |
| `X-Quota-Limit` | Quota mensuel |
| `X-Quota-Remaining` | Solde restant |

#### `GET /api/key`

État de la clé et consommation du mois, pour vérifier un solde sans attendre un
refus.

```bash
curl -H "X-API-Key: fxv_…" https://votre-domaine/api/key
```

#### Codes propres à l'accès par clé

| Code | Situation |
|---|---|
| `401` `CLE_INVALIDE` | Clé inconnue ou révoquée |
| `403` `CLE_EXPIREE` | Date d'expiration dépassée |
| `402` `QUOTA_EPUISE` | Quota mensuel atteint |

Le quota n'est décompté que pour une requête recevable : un fichier refusé pour
son extension, sa taille ou sa vacuité n'ampute pas le solde, puisqu'il n'a rien
coûté au service.

#### Avant de facturer

Renseignez `REDIS_URL`. Sans compteur partagé, les quotas repartent de zéro à
chaque redémarrage d'instance : suffisant pour brider un usage, insuffisant pour
facturer. La réponse de `/api/key` porte un champ `usage.shared` qui dit lequel des
deux régimes s'applique, plutôt que de laisser deviner.

### `GET /api/metrics`

Compteurs agrégés. **Fermé par défaut** : le volume traité et la répartition des
profils sont des données commerciales, les exposer publiquement renseignerait un
concurrent. Sans `METRICS_TOKEN`, l'accès rend `404`. Avec, il faut présenter le
jeton dans l'en-tête `X-Metrics-Token`.

```bash
curl -H "X-Metrics-Token: $METRICS_TOKEN" http://127.0.0.1:8080/api/metrics
```

Ce que l'on obtient, et qui sert directement l'argument commercial : volume traité,
répartition des verdicts, **répartition des profils dans le parc réel**, part de
fichiers non conformes, et surtout `topFailedRules`, le classement des règles sur
lesquelles les éditeurs achoppent le plus.

Rien d'identifiant n'est compté : aucun nom de fichier, aucune empreinte de
contenu, aucune adresse, aucune donnée de facture. Uniquement des totaux par
catégorie fermée. Les compteurs vivent en mémoire et repartent de zéro à chaque
démarrage d'instance : pour une série historique, il faut les collecter
périodiquement.

### `GET /api/health`

État du service et durées de précompilation des artefacts.

### `GET /api/about`

Versions des artefacts, empreintes SHA256, profils reconnus, repères
réglementaires, politique de non-conservation. Sert à rendre un rapport
vérifiable.

## Le rapport JSON

Le JSON est un livrable à part entière, pensé pour être consommé par un script.
Clés stables, énumérations fermées, index séquentiel des constats.

```json
{
  "schemaVersion": "1.0",
  "verdict": { "code": "non_conforme", "label": "Non conforme", "summary": "..." },
  "input": { "filename": "facture.pdf", "sizeBytes": 302582, "sha256": "...", "kind": "pdf" },
  "document": {
    "syntax": "CII",
    "profile": {
      "code": "EN16931",
      "urn": "urn:cen.eu:en16931:2017",
      "recognised": true,
      "en16931Scope": true,
      "fiscallyComplete": true
    },
    "identification": { "invoiceNumber": "F20260023", "issueDate": "2026-01-31" },
    "attachment": { "selected": "factur-x.xml", "afRelationship": "Source", "pdfaPart": "3" }
  },
  "levels": [
    { "id": "container", "status": "passed", "errors": 0, "warnings": 0 },
    { "id": "xsd", "status": "passed", "errors": 0 },
    { "id": "en16931", "status": "failed", "errors": 2 },
    { "id": "profil", "status": "passed", "errors": 0, "reason": "1 constat(s) ... écartés" }
  ],
  "findings": [
    {
      "index": 1,
      "level": "en16931",
      "severity": "error",
      "ruleId": "BR-CO-15",
      "internalRuleId": null,
      "xpath": "/rsm:CrossIndustryInvoice",
      "message": "Montant total toutes taxes comprises (BT-112) = ...",
      "messageOriginal": "Invoice total amount with VAT (BT-112) = ...",
      "messageSource": "catalogue_fr",
      "test": "...",
      "specification": "EN 16931 / CEN TC 434"
    }
  ],
  "summary": { "errors": 2, "warnings": 0, "infos": 0, "byLevel": { "...": {} } },
  "notices": [{ "code": "PROFIL_INCOMPLET", "severity": "warning", "message": "..." }],
  "regulatory": { "verifiedOn": "2026-07-24", "milestones": [] },
  "engine": { "durationMs": 71.1, "artifacts": {}, "levelsRun": [] }
}
```

### Énumérations

- `verdict.code` : `conforme`, `conforme_avec_avertissements`, `non_conforme`,
  `non_evaluable`.
- `levels[].status` : `passed`, `failed`, `warning`, `skipped`,
  `not_applicable`. Un niveau non exécuté porte toujours un `reason`.
- `findings[].severity` : `error`, `warning`, `info`.
- `findings[].level` : `container`, `pdfa`, `xsd`, `en16931`, `profil`, `frctc`.
- `findings[].internalRuleId` : numérotation interne du producteur du
  Schematron, présente seulement quand elle diffère du code normalisé.
- `findings[].messageSource` : `catalogue_fr`, `gabarit_fr`, `original_en`,
  `interne`.

## Décisions de conception

Quatre points ont demandé une vérification et méritent d'être justifiés, parce
qu'une implémentation naïve se tromperait.

### MINIMUM et BASIC WL sortent du périmètre EN 16931, sans rester sans contrôle

Ces deux profils ne déclarent pas l'URN de conformité CEN : ce sont des
sous-ensembles, pas des spécialisations conformes. Leur appliquer le Schematron
EN 16931 produirait des dizaines d'erreurs sans portée, la norme exigeant des
données que le profil n'autorise pas à porter. Le niveau est donc déclaré
`not_applicable`, avec son motif.

Ils ne sont pas pour autant dispensés de règles métier : le Schematron FNFE de
leur profil s'applique, et c'est leur niveau de référence. Sur un MINIMUM privé du
code pays vendeur, il remonte bien `BR-09` avec son message français.

### `AFRelationship` n'a pas une valeur unique attendue

Contrairement à une idée répandue, la valeur dépend du profil et du pays.

| Profil | Spécification Factur-X (France) | Usage allemand (ZUGFeRD) |
|---|---|---|
| MINIMUM, BASIC WL | `Data` | `Data` |
| BASIC, EN 16931, EXTENDED | `Data`, `Source` ou `Alternative` | `Alternative` |

L'outil refuse donc les valeurs hors liste PDF/A-3, signale un écart avec le
profil détecté comme un avertissement, et se contente d'une remarque quand la
valeur est licite en France mais pas conforme à l'usage allemand. Un contrôle qui
exigerait `Data` partout, ou `Alternative` partout, produirait de faux positifs.

### Les règles propres au profil viennent d'artefacts officiels, pas de code

Deux sources complémentaires, aucune règle réécrite.

Les XSD Factur-X sont publiés par profil et encodent les champs obligatoires
comme les éléments interdits : détecter le profil puis choisir le bon schéma
couvre la structure. Le Schematron FNFE, publié lui aussi par profil, couvre les
règles métier que le schéma ne peut pas exprimer.

Seuls les contrôles qu'aucun artefact ne peut porter, parce qu'ils concernent le
conteneur PDF et non le XML, sont codés ici. Ils portent des codes en `FX-PDF-`,
`FX-XML-` et `FX-PROFILE-`, distincts des codes officiels.

Attention à un piège de lecture : le Schematron FNFE numérote ses assertions en
`FX-SCH-A-000121` tout en citant le code normalisé entre crochets dans le message.
Retenir l'identifiant de l'attribut plutôt que le code entre crochets ferait perdre
le rattachement à `BR-CO-15`, donc la traduction et le dédoublonnage. Le rapport
retient le code normalisé et conserve la numérotation interne dans
`internalRuleId`.

### Le XML peut être CII ou UBL

La syntaxe est déduite du nom qualifié de la racine, jamais supposée. Le CII part
vers `EN16931-CII-validation.xslt` et les XSD Factur-X, l'UBL vers
`EN16931-UBL-validation.xslt` et les XSD UBL 2.1. À noter qu'un XML UBL ne peut
pas être incorporé dans un PDF Factur-X, le format hybride reposant sur le CII :
le rapport le signale quand un UBL est déposé.

## Messages en français

Le Schematron officiel s'exprime en anglais. Les rendre en français est le
principal apport pour un éditeur français, mais jamais au prix de la
traçabilité : chaque constat conserve son code de règle, le test évalué, et le
texte anglais d'origine.

| Provenance | Portée | Part du catalogue |
|---|---|---|
| `catalogue_fr` | Règles métier rédigées et vérifiées terme à terme : `BR-*`, `BR-CO-*`, `BR-CL-*`, `BR-DEC-*`, familles de catégories de TVA | 13 % |
| `gabarit_fr` | Règles de liaison syntaxique, de formulation mécanique et répétée : `CII-SR-*`, `UBL-CR-*`, `CII-DT-*` | 85 % |
| `original_en` | Formulations non reconnues, conservées telles quelles plutôt que devinées | 2 % |

Soit 97,8 % des 1562 règles du jeu EN 16931 rendues en français. Les 34 règles
restantes sont affichées en anglais et signalées comme telles : une traduction
approximative serait plus nuisible qu'un texte d'origine assumé.

## Parti pris de l'interface

L'outil s'adresse à des éditeurs de logiciels qui viennent lire un diagnostic, pas
à un visiteur qu'il faudrait convaincre. La mise en forme emprunte donc à
l'imprimé réglementaire plutôt qu'à la page d'accueil : titres en serif, parties
numérotées dans la marge, filets d'un pixel au lieu d'ombres portées, une seule
couleur d'accent, valeurs techniques et chiffres en caractères à chasse fixe. Les
couleurs de gravité sont désaturées, pour se distinguer sans passer devant le
texte.

Le balisage suit la contrainte du projet : les éléments HTML qui portent déjà le
sens voulu sont utilisés tels quels, et les styles s'y accrochent directement
plutôt que d'empiler des classes.

| Besoin | Élément retenu |
|---|---|
| Résultat de l'analyse | `<output>`, annoncé aux lecteurs d'écran |
| Verdict | `<article data-verdict>` |
| Niveau dépliable | `<details>` et `<summary>` |
| Constats | `<table>` avec `<caption>` |
| Identification du document | `<dl>`, `<dt>`, `<dd>` |
| Dates du calendrier | `<time datetime>` |
| Remarques | `<aside data-severity>` |
| Erreur de dépôt | `<p role="alert">` |
| Analyse en cours | `<progress>` |

Les seules classes du projet sont `.actions` et `.defilement-horizontal`. Les
variantes passent par des attributs de données explicites, `data-severity`,
`data-status`, `data-verdict`, qui décrivent un état et non une apparence.

La page suit le thème clair ou sombre du système, et une feuille d'impression
déplie tous les constats pour que le rapport s'imprime en entier.

## Performance

Mesuré par `python scripts/measure_performance.py`, cible de moins de
3 secondes pour un PDF de 1 Mo.

| Cas | Médiane |
|---|---|
| Première validation, artefacts non compilés | 446 ms |
| PDF Factur-X de 295 Ko | 33 ms |
| PDF de 1,4 Mo | 33 ms |
| PDF de 5,4 Mo | 36 ms |
| XML CII seul de 64 Ko | 35 ms |

Le coût réel est la compilation des artefacts, faite une fois au démarrage, soit
environ 1,17 s dont 550 ms pour le seul Schematron du profil EXTENDED, qui pèse
1,8 Mo. Les validations suivantes restent presque deux ordres de grandeur sous la
cible.

L'ajout du niveau de profil a fait passer une validation à chaud de 8 à 33 ms.
C'est le prix d'une seconde passe Schematron, jugé acceptable au regard de la
couverture gagnée sur MINIMUM et BASIC WL.

## Mise en production

### Configuration

`.env.example` recense toutes les variables, avec leur défaut et la raison de
chaque choix. Deux mises en garde y figurent, elles méritent d'être répétées.

`TRUST_PROXY_HEADERS` doit valoir `1` derrière Cloud Run, sans quoi tous les
appelants partagent un même plafond. À l'inverse, l'activer sans proxy de confiance
rend l'en-tête `X-Forwarded-For` forgeable, donc la limitation contournable.

`REDIS_URL` conditionne la possibilité de facturer à l'usage. Sans lui, les quotas
repartent de zéro à chaque redémarrage.

### Intégration continue

`.github/workflows/tests.yml` exécute quatre tâches : le backend avec un service
Redis pour que les compteurs partagés soient réellement éprouvés, l'audit PDF/A
avec veraPDF installé, la construction de l'interface, et enfin l'image Docker,
démarrée pour vérifier qu'elle valide une facture et rend le verdict attendu.

Les artefacts de validation sont récupérés à chaque exécution, comme à la
construction de l'image. Une montée de version chez le CEN ou la FNFE peut donc
faire échouer la chaîne, et c'est voulu : mieux vaut l'apprendre là qu'en
production.

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest
```

211 tests, dont un module par critère d'acceptation.

Les dépendances externes optionnelles ne sont pas obligatoires pour exécuter la
suite : sans veraPDF ni Redis, les tests concernés se sautent au lieu d'échouer.
Pour tout exécuter :

```bash
docker run -d --name fxv-redis -p 6379:6379 redis:7-alpine
cd backend
REDIS_URL=redis://127.0.0.1:6379/0 VERAPDF_ENABLED=1 VERAPDF_JAR=/opt/verapdf/bin/cli.jar   ../.venv/Scripts/python -m pytest
```

| Fichier | Objet |
|---|---|
| `test_acceptance.py` | Les quatre critères d'acceptation, un par classe |
| `test_validation.py` | Détection de syntaxe, portée EN 16931, niveau de profil et dédoublonnage, séparation des niveaux, conteneur PDF |
| `test_messages.py` | Catalogue français, gabarits, repli anglais, messages XSD |
| `test_api.py` | Contrat HTTP, garde-fous de taille et d'extension |
| `test_throttle.py` | Seau à jetons, garde-fou de concurrence, non-conservation des adresses, métriques et leur fermeture par défaut |
| `test_apikeys.py` | Chargement et validation des clés, expiration, quotas, contournement du plafond anonyme, absence de fuite de secret |
| `test_verapdf.py` | Lecture du rapport veraPDF, dégradation propre quand l'outil manque, non-écriture sur disque |
| `test_store.py` | Compteurs en mémoire et partagés, masquage des secrets, comportement en cas de panne du compteur |
| `test_leads.py` | Consentement, absence de fuite de données de facture vérifiée sur données réelles, détection du logiciel émetteur |

### Les échantillons

`python scripts/build_samples.py` reconstruit le jeu depuis les fixtures. Chaque
échantillon vise un constat précis.

| Échantillon | Attendu |
|---|---|
| `01-valide-en16931.pdf` | Conforme, profil EN 16931, zéro erreur, deux pièces jointes dont le XML |
| `02-pdf-sans-xml.pdf` | Message explicite `FX-PDF-010`, pas d'erreur technique |
| `03-profil-minimum.pdf` | Profil MINIMUM détecté, avertissement fiscal, EN 16931 sans objet |
| `04-xsd-invalide.xml` | XSD en échec avec XPath, EN 16931 franchi |
| `05-en16931-champ-obligatoire-manquant.xml` | XSD franchi, `BR-07` avec XPath, plus une cardinalité de profil |
| `06-en16931-totaux-incoherents.xml` | `BR-CO-15` et `BR-CO-16` |
| `07-ubl-valide.xml` | UBL 2.1 routé vers ses propres règles |
| `08-xml-mal-forme.xml` | Message lisible avec numéro de ligne |
| `09-profil-inconnu.xml` | Avertissement `FX-PROFILE-002`, sans blocage |

## Calendrier réglementaire

Vérifié le 24 juillet 2026. Base légale : article 91 de la loi de finances pour
2024, décret n° 2024-266 du 25 mars 2024.

| Date | Périmètre | Obligation |
|---|---|---|
| 1er septembre 2026 | Toutes les entreprises assujetties à la TVA | Réception |
| 1er septembre 2026 | Grandes entreprises et ETI | Émission et e-reporting |
| 1er septembre 2027 | PME, TPE et micro-entreprises | Émission et e-reporting |

Un décret peut décaler le premier palier, sans pouvoir le reporter au-delà du
1er décembre 2026. Ces valeurs sont centralisées dans
`backend/app/engine/regulatory.py`, avec leur date de vérification : le rapport
dit quand il a été informé, il n'affirme pas une date sans origine.

La transmission passe par une **Plateforme Agréée (PA)**. L'appellation
Plateforme de Dématérialisation Partenaire (PDP) n'est plus celle en vigueur et
n'apparaît dans le code que pour être signalée comme obsolète.

## Configuration

| Variable | Défaut | Rôle |
|---|---|---|
| `PORT` | `8080` | Port d'écoute |
| `MAX_UPLOAD_BYTES` | `10485760` | Taille maximale acceptée |
| `RESOURCES_DIR` | `backend/resources` | Emplacement des artefacts |
| `STATIC_DIR` | `backend/static` | Interface construite |
| `WARMUP_ON_STARTUP` | `1` | Précompilation des artefacts au démarrage |
| `MAX_FINDINGS_PER_LEVEL` | `300` | Plafond de constats par niveau, troncature signalée |
| `FRCTC_ENABLED` | `0` | Active le niveau des règles France (CTC), indicatif |
| `RATE_LIMIT_ENABLED` | `1` | Limitation de débit par appelant |
| `RATE_LIMIT_PER_MINUTE` | `20` | Validations par minute et par appelant |
| `RATE_LIMIT_BURST` | `8` | Rafale tolérée |
| `RATE_LIMIT_MAX_TRACKED` | `20000` | Appelants suivis, pour borner la mémoire |
| `MAX_CONCURRENT_VALIDATIONS` | `12` | Requêtes de validation admises, en traitement comme en attente |
| `TRUST_PROXY_HEADERS` | `0` | Lire l'adresse dans `X-Forwarded-For`, à activer derrière un proxy de confiance |
| `METRICS_TOKEN` | vide | Ouvre `/api/metrics`. Vide, l'accès est fermé |
| `API_KEYS` | vide | Déclaration JSON des clés d'API. Vide, seul l'accès anonyme existe |
| `CONTACT_EMAIL` | vide | Contact proposé pour demander une clé. Vide, rien n'est proposé |
| `CONTACT_URL` | vide | Page de contact, prioritaire sur le courriel |
| `LEADS_WEBHOOK_URL` | vide | Destination des manifestations d'intérêt |
| `LEADS_WEBHOOK_TOKEN` | vide | Jeton porteur envoyé à la destination |
| `LEADS_VIA_REDIS` | `0` | À défaut de webhook, empile dans une file Redis |
| `LEADS_RETENTION_MONTHS` | `24` | Durée de conservation annoncée au visiteur |
| `LEADS_CONTROLLER` | vide | Responsable du traitement. Sans lui, la fonction est inactive |
| `REDIS_URL` | vide | Compteurs partagés et persistants. Vide, les compteurs sont en mémoire |
| `REDIS_TIMEOUT_SECONDS` | `1.5` | Délai d'attente sur le compteur partagé |
| `VERAPDF_ENABLED` | `0` | Active l'audit PDF/A par veraPDF |
| `VERAPDF_JAR` | vide | Chemin du `cli.jar` de veraPDF |
| `JAVA_BIN` | `java` | Exécutable Java utilisé par veraPDF |
| `VERAPDF_TIMEOUT_SECONDS` | `25` | Délai au-delà duquel l'audit est abandonné |
| `VERAPDF_DEFAULT_FLAVOUR` | `3b` | Niveau appliqué si la détection par les métadonnées échoue |
| `CORS_ORIGINS` | vide | Origines autorisées, inutile si l'interface est servie par le même conteneur |

## Confidentialité

- Le fichier reçu est lu en mémoire, jamais écrit sur disque.
- Aucune conservation après la réponse, aucun historique, aucun compte.
- Seule une empreinte SHA256 figure dans le rapport rendu à l'appelant, pour lui
  permettre de rapprocher deux rapports. Elle n'est stockée nulle part.
- Les journaux du service ne contiennent aucun contenu de facture : en cas
  d'erreur interne, seule la trace technique est journalisée.
- Aucune adresse IP n'est conservée. La limitation de débit repose sur une
  empreinte de 8 octets, salée aléatoirement au démarrage du processus.
- Les compteurs agrégés ne retiennent aucune donnée identifiante, et l'accès y
  est fermé par défaut.
- L'analyse XML est verrouillée contre les entités externes et l'accès réseau,
  le service acceptant des fichiers arbitraires.
- Le nom du fichier déposé est assaini avant d'être renvoyé : séparateurs de
  chemin retirés, caractères de contrôle écartés, longueur bornée.
- Les réponses publiques ne divulguent aucun chemin serveur. Le détail des
  incidents va dans les journaux, la réponse reste générique.

## Limites connues

À dire clairement, parce qu'un outil de diagnostic qui surestime sa portée est
pire qu'inutile.

- **Sans veraPDF, le contrôle PDF/A reste structurel.** L'outil vérifie alors la
  présence et la cohérence des marqueurs, pas l'intégralité de la spécification.
  Le rapport porte cette réserve, et l'audit réel est disponible en option.
- **L'audit PDF/A coûte 1,5 s par PDF**, presque entièrement du démarrage de JVM.
  D'où sa désactivation par défaut.
- **Aucune vérification de fond.** Existence réelle d'un SIREN, validité d'un
  numéro de TVA intracommunautaire auprès de VIES, cohérence comptable : hors
  périmètre.
- **Les règles France (CTC) sont désactivées.** Elles visent le flux entre
  Plateformes Agréées et produiraient du bruit sur une facture examinée hors de
  ce contexte.
- **Le dédoublonnage entre niveaux masque les occurrences multiples** d'une règle
  déjà traitée au niveau EN 16931. Le nombre de constats écartés est affiché.
- **Une validation ne peut pas être interrompue en cours.** Saxon s'exécute en
  processus, sans point d'annulation : un document pathologique occupe le fil de
  validation jusqu'au bout. La borne de taille et la profondeur de file limitent la
  portée du problème, sans le supprimer.
- **34 règles restent en anglais**, signalées par `messageSource`.
- **Pas de routage, pas de génération, pas d'e-reporting.** L'outil valide un
  fichier, il ne l'émet pas et ne l'achemine pas.

Ce rapport est un diagnostic technique automatisé. Il ne constitue ni une
attestation de conformité fiscale, ni un conseil juridique, et ne préjuge pas de
l'acceptation du document par une Plateforme Agréée.

## Structure du dépôt

```
scripts/
  fetch_artifacts.py        Récupération des artefacts officiels, avec manifeste
                            (Schematron CEN et FNFE, XSD, bases de listes de codes)
  build_samples.py          Construction des échantillons de test
  measure_performance.py    Mesure des durées de validation
  make_api_key.py           Génération d'une clé et de son empreinte
  stress_test.py            Tenue du service sous charge concurrente
backend/
  app/
    main.py                 API FastAPI, service de l'interface
    config.py               Configuration par variables d'environnement
    report.py               Modèle de rapport et calcul du verdict
    throttle.py             Limitation de débit et plafond de concurrence
    metrics.py              Compteurs agrégés, sans donnée identifiante
    store.py                Compteurs de quota et de débit, mémoire ou Redis
    apikeys.py              Accès par clé, plans et quotas
    leads.py                Manifestations d'intérêt, sur consentement explicite
    engine/
      orchestrator.py       Enchaînement des niveaux
      detect.py             Syntaxe CII ou UBL, identifiants du document
      profiles.py           Profils Factur-X et portée EN 16931
      pdf.py                Conteneur PDF/A-3 et extraction du XML
      xsd.py                Validation de schéma
      schematron.py         Exécution Saxon et lecture du SVRL
      verapdf.py            Audit PDF/A par veraPDF, via l'entrée standard
      messages.py           Catalogue français, gabarits, libellés BT
      regulatory.py         Repères réglementaires datés
      resources.py          Cache des artefacts compilés, verrou Saxon
  tests/
    fixtures/               Exemplaires publiés, voir PROVENANCE.md
    samples/                Échantillons dérivés, produits par script
frontend/
  src/
    App.vue                 Assemblage de la page
    components/             Dépôt, verdict, niveaux, constats, calendrier
    styles.css              Styles sur sélecteurs d'éléments
```

## Voir aussi

Pour lire une facture plutôt que la valider, [Factur-X Viewer](https://facturxviewer.fr)
affiche un PDF Factur-X ou un XML CII ou UBL comme un document lisible, avec
des contrôles rapides des totaux, de la TVA et de l'IBAN. Le traitement se fait
entièrement dans le navigateur, en ligne ou via l'extension Chrome.

## Licences

Le code de ce dépôt est sous licence MIT. Les artefacts récupérés à la
construction conservent les leurs : Schematron EN 16931 sous EUPL-1.2, schémas
obtenus via le paquet `factur-x` sous BSD-3-Clause. Voir `LICENSE`.
