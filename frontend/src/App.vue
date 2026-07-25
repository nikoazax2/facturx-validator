<script setup>
import { computed, onMounted, ref, useTemplateRef } from 'vue'
import DemandeContact from './components/DemandeContact.vue'
import DepotFichier from './components/DepotFichier.vue'
import NiveauValidation from './components/NiveauValidation.vue'
import OffreIntegration from './components/OffreIntegration.vue'
import ReperesReglementaires from './components/ReperesReglementaires.vue'
import ResumeDocument from './components/ResumeDocument.vue'
import Verdict from './components/Verdict.vue'

const rapport = ref(null)
const erreur = ref(null)
const enCours = ref(false)
const service = ref(null)
const depot = useTemplateRef('depot')
const resultat = useTemplateRef('resultat')

const tailleMax = computed(() => service.value?.maxUploadBytes ?? 10 * 1024 * 1024)

onMounted(async () => {
  try {
    const reponse = await fetch('/api/about')
    if (reponse.ok) service.value = await reponse.json()
  } catch {
    // L'interface reste utilisable sans ces informations : elles ne servent qu'a
    // afficher les versions des artefacts et la taille maximale exacte.
  }
})

async function valider(fichier) {
  enCours.value = true
  erreur.value = null
  rapport.value = null

  const corps = new FormData()
  corps.append('file', fichier)

  try {
    const reponse = await fetch('/api/validate', { method: 'POST', body: corps })
    const charge = await reponse.json()
    if (!reponse.ok) {
      erreur.value = charge?.error?.message ?? `Le service a répondu ${reponse.status}.`
      return
    }
    rapport.value = charge
    // Amener le lecteur au resultat, sans lui faire chercher ou il est apparu.
    requestAnimationFrame(() => {
      resultat.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  } catch {
    erreur.value =
      "Le service n'a pas pu être joint. Vérifiez votre connexion, puis réessayez."
  } finally {
    enCours.value = false
  }
}

const constatsDe = (identifiant) =>
  (rapport.value?.findings ?? []).filter((constat) => constat.level === identifiant)

const remarques = computed(() =>
  (rapport.value?.notices ?? []).filter((remarque) => remarque.code !== 'AVERTISSEMENT')
)

function exporterJson() {
  const contenu = JSON.stringify(rapport.value, null, 2)
  const lien = document.createElement('a')
  const objet = URL.createObjectURL(new Blob([contenu], { type: 'application/json' }))
  // Le nom vient du fichier depose, donc de l'utilisateur. Le serveur en a deja
  // retire les separateurs de chemin ; on le restreint ici a un jeu de caracteres
  // sur pour un nom de telechargement, et on le borne.
  const base = (rapport.value.input.filename ?? 'facture')
    .replace(/\.(pdf|xml)$/i, '')
    .replace(/[^\p{L}\p{N}._-]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
  lien.href = objet
  lien.download = `rapport-facturx-${base || 'facture'}.json`
  lien.click()
  URL.revokeObjectURL(objet)
}

async function copierJson() {
  await navigator.clipboard.writeText(JSON.stringify(rapport.value, null, 2))
}

function recommencer() {
  rapport.value = null
  erreur.value = null
  depot.value?.reinitialiser()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <header>
    <p data-surtitre>Facture électronique &middot; Norme EN 16931 &middot; France</p>
    <h1>Validateur Factur-X</h1>
    <p>
      Déposez une facture électronique : cet outil vérifie le conteneur PDF/A-3, la
      validité du schéma XSD et la conformité aux règles métier de la norme
      EN 16931, évaluées par le Schematron officiel du CEN.
    </p>
    <p>
      <strong>Aucun compte, aucun fichier conservé.</strong>
      Le document est analysé en mémoire et libéré dès la réponse envoyée. Il n'est
      ni enregistré, ni transmis à un tiers, ni utilisé à d'autres fins.
    </p>
  </header>

  <main>
    <section>
      <h2>Votre facture</h2>
      <DepotFichier
        ref="depot"
        :en-cours="enCours"
        :taille-max="tailleMax"
        @valider="valider"
      />
    </section>

    <section v-if="erreur">
      <p role="alert">{{ erreur }}</p>
    </section>

    <output v-if="rapport" ref="resultat">
      <section>
        <h2>Résultat</h2>
        <Verdict :rapport="rapport" />

        <div class="actions">
          <button type="button" @click="exporterJson">Télécharger le rapport JSON</button>
          <button type="button" @click="copierJson">Copier le JSON</button>
          <button type="button" @click="recommencer">Valider une autre facture</button>
        </div>
      </section>

      <section v-if="remarques.length">
        <h2>À retenir</h2>
        <aside
          v-for="remarque in remarques"
          :key="remarque.code"
          :data-severity="remarque.severity"
        >
          <p>{{ remarque.message }}</p>
        </aside>
      </section>

      <section>
        <h2>Les niveaux de validation</h2>
        <p>
          Ces niveaux sont indépendants. Un fichier peut être structurellement valide
          au regard de son schéma et violer malgré tout les règles métier de la norme,
          ou l'inverse.
        </p>
        <NiveauValidation
          v-for="niveau in rapport.levels"
          :key="niveau.id"
          :niveau="niveau"
          :constats="constatsDe(niveau.id)"
        />
      </section>

      <ResumeDocument :rapport="rapport" />

      <ReperesReglementaires :reglementation="rapport.regulatory" />

      <OffreIntegration :service="service" />

      <DemandeContact :service="service" :rapport="rapport" />

      <section>
        <h2>Ce sur quoi repose ce diagnostic</h2>
        <dl>
          <dt>Schematron EN 16931</dt>
          <dd>
            version {{ rapport.engine.artifacts.en16931SchematronVersion }}
            <small>(CEN/TC 434, licence EUPL-1.2)</small>
          </dd>
          <dt>Schémas Factur-X et UBL</dt>
          <dd>
            jeu {{ rapport.engine.artifacts.facturxSchemaPackageVersion }}
            <small>(UN/CEFACT et OASIS UBL)</small>
          </dd>
          <dt>Traduction française</dt>
          <dd>
            {{ rapport.engine.messageCatalogue.cataloguedRules }} règles métier
            rédigées, plus des gabarits couvrant les règles de liaison syntaxique.
            <small>
              Chaque constat indique la provenance de son libellé, et conserve le
              texte anglais d'origine.
            </small>
          </dd>
          <dt>Version de l'outil</dt>
          <dd>{{ rapport.engine.name }} {{ rapport.engine.version }}</dd>
        </dl>
        <aside data-severity="info" style="margin-top: 1rem">
          <p>{{ rapport.regulatory.disclaimer }}</p>
        </aside>
      </section>
    </output>

    <template v-else-if="!enCours">
    <section>
      <h2>Ce qui est vérifié</h2>
      <details>
        <summary>
          <span data-etape>1</span>
          Conteneur PDF/A-3
          <small>pour les fichiers PDF</small>
        </summary>
        <div>
          <p>
            Extraction de la pièce jointe XML, en acceptant le nom
            <code>factur-x.xml</code> attendu par la spécification comme les noms
            historiques <code>ZUGFeRD-invoice.xml</code> et
            <code>zugferd-invoice.xml</code>, et en signalant le cas de plusieurs
            pièces jointes. Contrôle de la clé <code>AFRelationship</code>, du type
            MIME déclaré, du tableau des fichiers associés et des métadonnées XMP
            Factur-X.
          </p>
        </div>
      </details>
      <details>
        <summary>
          <span data-etape>2</span>
          Validité XSD
          <small>structure et cardinalités</small>
        </summary>
        <div>
          <p>
            Le profil est déterminé à partir de l'identifiant de spécification, puis
            le XML est confronté au schéma de ce profil précis. Les obligations
            propres au profil, champs requis et éléments interdits, sont donc
            vérifiées ici.
          </p>
        </div>
      </details>
      <details>
        <summary>
          <span data-etape>3</span>
          Conformité EN 16931
          <small>règles métier de la norme</small>
        </summary>
        <div>
          <p>
            Les règles de la norme européenne sont évaluées par le Schematron publié
            par le CEN, jamais réécrites. Le CII et l'UBL sont routés chacun vers sa
            propre liaison. Les profils MINIMUM et BASIC WL ne déclarent pas de
            conformité EN 16931 : le niveau est alors déclaré sans objet, avec son
            motif, plutôt que rempli d'erreurs trompeuses.
          </p>
        </div>
      </details>
      <details>
        <summary>
          <span data-etape>4</span>
          Règles du profil Factur-X
          <small>publiées par la FNFE-MPE</small>
        </summary>
        <div>
          <p>
            Chaque profil a ses propres contraintes, au-delà de la norme. Elles sont
            évaluées par le jeu de règles que la FNFE-MPE publie pour ce profil.
            C'est le seul niveau de règles métier applicable à MINIMUM et BASIC WL.
            Les règles déjà traitées au niveau précédent ne sont pas répétées.
          </p>
        </div>
      </details>
    </section>

    <OffreIntegration :service="service" />
    </template>
  </main>

  <footer>
    <p>
      Outil gratuit de diagnostic technique. Le traitement est réalisé en mémoire,
      sans enregistrement du fichier ni création de compte, conformément au principe
      de minimisation des données du
      <abbr title="Règlement général sur la protection des données">RGPD</abbr>.
      Aucune donnée personnelle contenue dans la facture n'est conservée après la
      réponse.
    </p>
    <p v-if="service">
      Schematron EN 16931 {{ service.artifacts?.en16931SchematronVersion }} sous
      licence EUPL-1.2. Taille maximale acceptée
      {{ Math.round(service.maxUploadBytes / (1024 * 1024)) }} Mo.
    </p>
  </footer>
</template>
