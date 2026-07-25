<script setup>
import { computed, ref } from 'vue'

/*
  Demande de contact, sur initiative du visiteur.

  Placee apres le rapport, jamais avant : la promesse de l'outil est qu'on
  l'utilise sans compte et sans friction, et le resultat est rendu quoi qu'il
  arrive. Rien n'est prerempli, rien n'est coche d'avance, et le formulaire ne
  s'affiche qu'une fois deplie.

  Les mentions d'information viennent du service et non du code de l'interface :
  elles engagent, elles doivent donc refleter la configuration reelle.
*/
const props = defineProps({
  service: { type: Object, default: null },
  rapport: { type: Object, default: null }
})

const mentions = computed(() => props.service?.leadCapture ?? null)
const actif = computed(() => mentions.value?.enabled === true)

const courriel = ref('')
const logiciel = ref('')
const secteur = ref('')
const volume = ref('')
const consentement = ref(false)
const envoi = ref(false)
const resultat = ref(null)
const erreur = ref(null)

// Le logiciel declare par le fichier sert de valeur suggeree, jamais imposee.
const logicielDetecte = computed(() => props.rapport?.document?.producer?.label ?? null)

async function envoyer() {
  if (envoi.value) return
  erreur.value = null
  envoi.value = true
  try {
    const reponse = await fetch('/api/lead', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: courriel.value,
        consent: consentement.value,
        software: logiciel.value || logicielDetecte.value || null,
        sector: secteur.value || null,
        monthlyVolume: volume.value || null,
        report: props.rapport
      })
    })
    const charge = await reponse.json()
    if (!reponse.ok) {
      erreur.value = charge?.error?.message ?? `Le service a répondu ${reponse.status}.`
      return
    }
    resultat.value = charge.message
  } catch {
    erreur.value = "La demande n'a pas pu être envoyée. Vérifiez votre connexion."
  } finally {
    envoi.value = false
  }
}
</script>

<template>
  <section v-if="actif">
    <h2>Être recontacté</h2>

    <p v-if="resultat" role="status">{{ resultat }}</p>

    <details v-else>
      <summary>
        <span data-etape>Facultatif</span>
        Faire examiner votre parc de factures
        <small>vous laissez une adresse, rien d'autre</small>
      </summary>
      <div>
        <p>
          Ce rapport porte sur un fichier. Si vous voulez faire examiner un
          ensemble de factures, ou comprendre pourquoi votre logiciel produit ces
          écarts, laissez une adresse et le sujet sera repris avec vous.
        </p>

        <form @submit.prevent="envoyer">
          <dl>
            <dt><label for="courriel">Adresse de courriel</label></dt>
            <dd>
              <input
                id="courriel"
                v-model="courriel"
                type="email"
                required
                autocomplete="email"
                placeholder="vous@votre-societe.fr"
              />
            </dd>

            <dt><label for="logiciel">Logiciel émetteur</label></dt>
            <dd>
              <input
                id="logiciel"
                v-model="logiciel"
                type="text"
                :placeholder="logicielDetecte || 'facultatif'"
              />
              <small v-if="logicielDetecte">
                Le fichier déclare <code>{{ logicielDetecte }}</code>. Corrigez si
                ce n'est pas le nom commercial.
              </small>
            </dd>

            <dt><label for="secteur">Secteur</label></dt>
            <dd>
              <input id="secteur" v-model="secteur" type="text" placeholder="facultatif" />
            </dd>

            <dt><label for="volume">Factures par mois</label></dt>
            <dd>
              <input id="volume" v-model="volume" type="text" placeholder="facultatif" />
            </dd>
          </dl>

          <p>
            <label for="consentement">
              <input id="consentement" v-model="consentement" type="checkbox" />
              J'accepte d'être recontacté à cette adresse au sujet de la validation
              de mes factures.
            </label>
          </p>

          <aside data-severity="info">
            <p>
              <strong>Ce qui est transmis :</strong> votre adresse, ce que vous
              déclarez ci-dessus, et les faits techniques de cette validation,
              verdict et codes de règles en échec.
            </p>
            <p>
              <strong>Ce qui ne l'est jamais :</strong> le fichier déposé, son nom,
              et toute donnée figurant dans la facture. Ni vos clients, ni vos
              montants, ni vos numéros de facture.
            </p>
            <p>
              <small>
                Responsable du traitement : {{ mentions.controller }}.
                Base légale : {{ mentions.legalBasis }}. Conservation :
                {{ mentions.retentionMonths }} mois. {{ mentions.rights }}
              </small>
            </p>
          </aside>

          <p v-if="erreur" role="alert">{{ erreur }}</p>

          <div class="actions">
            <button type="submit" :disabled="envoi || !consentement || !courriel">
              {{ envoi ? 'Envoi en cours' : 'Envoyer' }}
            </button>
          </div>
        </form>
      </div>
    </details>
  </section>
</template>

<style scoped>
/* Le formulaire n'est pas une zone de depot : il ne reprend donc pas le cadre en
   pointilles du depot de fichier. */
form {
  border: none;
  background: none;
  padding: 0;
}

input[type='text'],
input[type='email'] {
  font: inherit;
  font-size: 0.9375rem;
  width: 100%;
  max-width: 22rem;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--filet-appuye);
  border-radius: 2px;
  background: var(--surface);
  color: var(--encre);
}

input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

dd > small {
  display: block;
  margin-top: 0.3rem;
}

label[for='consentement'] {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  max-width: var(--mesure);
  cursor: pointer;
  font-size: 0.9375rem;
}

label[for='consentement'] input {
  flex-shrink: 0;
  margin: 0;
}

form > p {
  margin-top: 1.25rem;
}

form aside {
  margin-top: 1.25rem;
}

[role='status'] {
  border: 1px solid var(--succes);
  border-left-width: 3px;
  background: var(--succes-voile);
  padding: 0.9rem 1.15rem;
  font-size: 0.9375rem;
  max-width: var(--mesure);
}

summary > [data-etape] {
  min-width: auto;
}
</style>
