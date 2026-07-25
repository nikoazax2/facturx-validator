<script setup>
const props = defineProps({
  constats: { type: Array, required: true }
})

const LIBELLES = {
  error: 'Erreur',
  warning: 'Avertissement',
  info: 'Remarque'
}

const PROVENANCES = {
  catalogue_fr: 'Traduction française vérifiée',
  gabarit_fr: 'Traduction française par gabarit',
  original_en: 'Message d\'origine, non traduit',
  interne: 'Contrôle propre à cet outil'
}
</script>

<template>
  <div class="defilement-horizontal">
    <table>
      <caption>
        Chaque ligne porte le code de la règle et le chemin XPath de l'élément mis en
        cause, afin que le constat puisse être vérifié dans le document.
      </caption>
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">Gravité</th>
          <th scope="col">Règle</th>
          <th scope="col">Message</th>
          <th scope="col">Emplacement</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="constat in constats" :key="constat.index">
          <td>{{ constat.index }}</td>
          <td :data-severity="constat.severity">
            {{ LIBELLES[constat.severity] }}
          </td>
          <td>
            <code>{{ constat.ruleId || 'sans code' }}</code>
          </td>
          <td>
            {{ constat.message }}
            <template v-if="constat.hint">
              <br /><small>{{ constat.hint }}</small>
            </template>
            <details v-if="constat.messageOriginal || constat.test || constat.internalRuleId">
              <summary>
                <small>{{ PROVENANCES[constat.messageSource] || constat.messageSource }}</small>
              </summary>
              <p v-if="constat.messageOriginal">
                <small>Texte d'origine : <samp>{{ constat.messageOriginal }}</samp></small>
              </p>
              <p v-if="constat.internalRuleId">
                <small>
                  Référence interne du jeu de règles :
                  <samp>{{ constat.internalRuleId }}</samp>
                </small>
              </p>
              <p v-if="constat.test">
                <small>Test évalué : <samp>{{ constat.test }}</samp></small>
              </p>
              <p v-if="constat.specification">
                <small>Référentiel : {{ constat.specification }}</small>
              </p>
            </details>
          </td>
          <td>
            <code v-if="constat.xpath">{{ constat.xpath }}</code>
            <small v-else>non localisé</small>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
td > details {
  margin-top: 0.35rem;
}

td > details > summary {
  cursor: pointer;
  color: var(--texte-doux);
}

td > details > p {
  margin: 0.35rem 0 0;
}

td > details samp {
  word-break: break-word;
}

td:nth-child(4) {
  min-width: 22rem;
}

td:nth-child(5) {
  max-width: 18rem;
}
</style>
