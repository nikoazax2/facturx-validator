<script setup>
import TableauConstats from './TableauConstats.vue'

const props = defineProps({
  niveau: { type: Object, required: true },
  constats: { type: Array, default: () => [] }
})

const ETATS = {
  passed: 'Franchi',
  failed: 'En échec',
  warning: 'Réserves',
  skipped: 'Non exécuté',
  not_applicable: 'Sans objet'
}

function decompte(n) {
  const parties = []
  if (n.errors) parties.push(`${n.errors} erreur${n.errors > 1 ? 's' : ''}`)
  if (n.warnings) parties.push(`${n.warnings} avertissement${n.warnings > 1 ? 's' : ''}`)
  if (n.infos) parties.push(`${n.infos} remarque${n.infos > 1 ? 's' : ''}`)
  return parties.length ? parties.join(', ') : 'aucun constat'
}

// Un niveau en echec s'ouvre de lui-meme : c'est ce que le visiteur vient lire.
const ouvertParDefaut = props.niveau.status === 'failed' || props.niveau.status === 'warning'

/*
  Le champ `reason` sert deux usages : expliquer un niveau non applique, ou
  apporter une precision sur un niveau applique, par exemple le nombre de constats
  ecartes par dedoublonnage. Le libelle doit suivre, sous peine d'affirmer qu'un
  niveau n'a pas tourne alors qu'il a tourne.
*/
const niveauNonApplique = ['skipped', 'not_applicable'].includes(props.niveau.status)
</script>

<template>
  <details :open="ouvertParDefaut">
    <summary>
      <span :data-status="niveau.status">{{ ETATS[niveau.status] || niveau.status }}</span>
      {{ niveau.label }}
      <small>{{ decompte(niveau) }}</small>
    </summary>
    <div>
      <p>{{ niveau.description }}</p>

      <p v-if="niveau.reason">
        <strong v-if="niveauNonApplique">Pourquoi ce niveau n'a pas été appliqué :</strong>
        <strong v-else>À noter :</strong>
        {{ niveau.reason }}
      </p>

      <p v-if="niveau.truncated" role="alert">
        Le nombre de constats a été plafonné pour ce niveau. Les totaux affichés
        restent exacts, mais tous les constats ne sont pas listés.
      </p>

      <TableauConstats v-if="constats.length" :constats="constats" />

      <p v-else-if="niveau.status === 'passed'">
        Aucun constat sur ce niveau.
      </p>
    </div>
  </details>
</template>
