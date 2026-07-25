<script setup>
import { computed } from 'vue'

const props = defineProps({
  rapport: { type: Object, required: true }
})

/*
  Chaque chiffre cle est presente comme une valeur surmontant son libelle, en
  chasse fixe : le bandeau se lit comme un releve, pas comme une serie
  d'etiquettes decoratives.
*/
const chiffres = computed(() => {
  const rapport = props.rapport
  const entrees = [
    { valeur: rapport.summary.errors, libelle: accord(rapport.summary.errors, 'erreur') },
    {
      valeur: rapport.summary.warnings,
      libelle: accord(rapport.summary.warnings, 'avertissement')
    },
    { valeur: rapport.summary.infos, libelle: accord(rapport.summary.infos, 'remarque') }
  ]

  if (rapport.document.profile) {
    entrees.push({ valeur: rapport.document.profile.label, libelle: 'profil détecté' })
  }
  if (rapport.document.syntax) {
    entrees.push({ valeur: rapport.document.syntax, libelle: 'syntaxe' })
  }
  entrees.push({
    valeur: `${Math.round(rapport.engine.durationMs)} ms`,
    libelle: "durée d'analyse"
  })
  return entrees
})

function accord(nombre, mot) {
  return nombre > 1 ? `${mot}s` : mot
}
</script>

<template>
  <article :data-verdict="rapport.verdict.code">
    <h2>{{ rapport.verdict.label }}</h2>
    <p>{{ rapport.verdict.summary }}</p>

    <ul>
      <li v-for="chiffre in chiffres" :key="chiffre.libelle">
        <strong>{{ chiffre.valeur }}</strong>
        {{ chiffre.libelle }}
      </li>
    </ul>
  </article>
</template>
