<script setup>
import { computed } from 'vue'

/*
  Presentation de l'acces par cle.

  Deliberement sobre, et placee apres le rapport : la promesse de l'outil est
  qu'on l'utilise sans compte et sans friction, et une sollicitation avant le
  resultat la trahirait. Le propos reste factuel, il decrit une capacite technique
  destinee a qui en a besoin.

  Le bouton de contact ne s'affiche que si un contact est configure : mieux vaut ne
  rien proposer que renvoyer vers une adresse inexistante.
*/
const props = defineProps({
  service: { type: Object, default: null }
})

const acces = computed(() => props.service?.apiAccess ?? null)
const plans = computed(() => acces.value?.plans ?? [])
const plafondPublic = computed(() => props.service?.limits?.perMinute ?? null)

const lienContact = computed(() => {
  if (acces.value?.contactUrl) return acces.value.contactUrl
  if (acces.value?.contactEmail) {
    const objet = encodeURIComponent('Accès par clé au validateur Factur-X')
    return `mailto:${acces.value.contactEmail}?subject=${objet}`
  }
  return null
})

const origine = window.location.origin
const nombre = (valeur) => new Intl.NumberFormat('fr-FR').format(valeur)
</script>

<template>
  <section v-if="plans.length">
    <h2>Valider en série</h2>
    <p>
      Cette page traite un fichier à la fois, ce qui convient pour un contrôle
      ponctuel. Les mêmes contrôles sont accessibles par API, pour valider un lot,
      vérifier un parc existant, ou brancher la validation sur une chaîne
      d'intégration continue.
    </p>

    <div class="defilement-horizontal">
      <table>
        <caption>
          Le rapport rendu par l'API est celui affiché ici, au format JSON. Les
          plafonds s'appliquent par clé.
        </caption>
        <thead>
          <tr>
            <th scope="col">Formule</th>
            <th scope="col">Par minute</th>
            <th scope="col">Par mois</th>
            <th scope="col">Usage visé</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="plan in plans" :key="plan.id">
            <th scope="row">{{ plan.label }}</th>
            <td>{{ nombre(plan.perMinute) }}</td>
            <td>{{ nombre(plan.perMonth) }}</td>
            <td>{{ plan.description }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3>Un appel</h3>
    <pre><code>curl -X POST \
  -H "X-API-Key: fxv_…" \
  -F "file=@facture.pdf" \
  {{ origine }}/api/validate</code></pre>

    <dl>
      <dt>Documentation</dt>
      <dd>
        <a :href="acces.documentationUrl">Référence de l'API</a>, avec le schéma
        complet des réponses.
      </dd>
      <dt>Suivi de consommation</dt>
      <dd>
        <code>GET /api/key</code> rend le plan, le solde du mois et les plafonds.
      </dd>
      <dt>Sans clé</dt>
      <dd>
        L'API reste utilisable au plafond de l'accès public,
        <template v-if="plafondPublic">
          {{ nombre(plafondPublic) }} validations par minute.
        </template>
        <template v-else>sans engagement.</template>
      </dd>
    </dl>

    <div v-if="lienContact" class="actions">
      <a :href="lienContact">Demander une clé</a>
    </div>
    <p v-else>
      <small>
        L'accès par clé n'est pas ouvert aux demandes sur cette instance.
      </small>
    </p>
  </section>
</template>

<style scoped>
h3 {
  margin-top: 1.75rem;
}

pre {
  margin: 0 0 1.5rem;
  padding: 0.9rem 1.1rem;
  border: 1px solid var(--filet);
  background: var(--surface-creuse);
  overflow-x: auto;
  font-size: 0.8125rem;
  line-height: 1.6;
}

pre code {
  background: none;
  padding: 0;
}

td:last-child,
th:last-child {
  min-width: 18rem;
}

tbody th {
  font-weight: 600;
  white-space: nowrap;
}

/* Lien d'appel a l'action, dessine comme un bouton sans en etre un : il navigue,
   il ne declenche pas d'action dans la page. */
.actions a {
  display: inline-block;
  font-weight: 600;
  font-size: 0.9375rem;
  padding: 0.55rem 1.1rem;
  border: 1px solid var(--accent);
  border-radius: 2px;
  background: var(--accent);
  color: var(--papier);
  text-decoration: none;
}

.actions a:hover {
  background: var(--encre);
  border-color: var(--encre);
}
</style>
