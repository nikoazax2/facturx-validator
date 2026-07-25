<script setup>
import { ref } from 'vue'

const props = defineProps({
  enCours: { type: Boolean, default: false },
  tailleMax: { type: Number, default: 10 * 1024 * 1024 }
})
const emit = defineEmits(['valider'])

const fichier = ref(null)
const survol = ref(false)
const refuse = ref('')
const champ = ref(null)

const megaoctets = () => Math.round(props.tailleMax / (1024 * 1024))

function accepter(candidat) {
  refuse.value = ''
  if (!candidat) return

  const nom = candidat.name.toLowerCase()
  if (!nom.endsWith('.pdf') && !nom.endsWith('.xml')) {
    refuse.value = `« ${candidat.name} » n'est ni un PDF ni un XML.`
    fichier.value = null
    return
  }
  if (candidat.size > props.tailleMax) {
    refuse.value = `« ${candidat.name} » dépasse la taille maximale de ${megaoctets()} Mo.`
    fichier.value = null
    return
  }
  if (candidat.size === 0) {
    refuse.value = `« ${candidat.name} » est vide.`
    fichier.value = null
    return
  }
  fichier.value = candidat
}

function surSelection(evenement) {
  accepter(evenement.target.files?.[0] ?? null)
}

function surDepot(evenement) {
  survol.value = false
  accepter(evenement.dataTransfer?.files?.[0] ?? null)
}

function soumettre() {
  if (fichier.value && !props.enCours) emit('valider', fichier.value)
}

function reinitialiser() {
  fichier.value = null
  refuse.value = ''
  if (champ.value) champ.value.value = ''
}

defineExpose({ reinitialiser })

function poids(octets) {
  if (octets < 1024) return `${octets} octets`
  if (octets < 1024 * 1024) return `${(octets / 1024).toFixed(0)} Ko`
  return `${(octets / (1024 * 1024)).toFixed(2)} Mo`
}

function nature(nom) {
  return nom.toLowerCase().endsWith('.pdf')
    ? 'PDF, conteneur et XML incorporé'
    : 'XML seul, sans conteneur'
}
</script>

<template>
  <form
    :data-dragging="survol"
    @submit.prevent="soumettre"
    @dragover.prevent="survol = true"
    @dragleave.prevent="survol = false"
    @drop.prevent="surDepot"
  >
    <p>
      <input
        id="facture"
        ref="champ"
        type="file"
        accept=".pdf,.xml,application/pdf,text/xml,application/xml"
        :disabled="enCours"
        @change="surSelection"
      />
      <label for="facture">Choisir un fichier</label>
      ou le déposer dans ce cadre.
    </p>

    <p>
      PDF Factur-X, ou XML seul au format CII ou UBL 2.1. {{ megaoctets() }} Mo au
      maximum. Le fichier n'est pas conservé.
    </p>

    <p v-if="refuse" role="alert">{{ refuse }}</p>

    <template v-if="fichier">
      <dl>
        <dt>Fichier retenu</dt>
        <dd>
          <strong>{{ fichier.name }}</strong>
        </dd>
        <dt>Taille</dt>
        <dd>{{ poids(fichier.size) }}</dd>
        <dt>Nature attendue</dt>
        <dd>{{ nature(fichier.name) }}</dd>
      </dl>

      <div class="actions">
        <button type="submit" :disabled="enCours">
          {{ enCours ? 'Analyse en cours' : 'Valider la facture' }}
        </button>
        <button type="button" :disabled="enCours" @click="reinitialiser">
          Changer de fichier
        </button>
      </div>

      <progress v-if="enCours" aria-label="Analyse en cours"></progress>
    </template>
  </form>
</template>
