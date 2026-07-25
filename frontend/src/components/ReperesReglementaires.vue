<script setup>
defineProps({
  reglementation: { type: Object, required: true }
})

const OBLIGATIONS = {
  reception: 'Réception',
  emission: 'Émission'
}

function dateLisible(iso) {
  const [annee, mois, jour] = iso.split('-')
  const mois_ = [
    'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
  ]
  return `${Number(jour)} ${mois_[Number(mois) - 1]} ${annee}`
}
</script>

<template>
  <section>
    <h2>Le calendrier applicable</h2>

    <ol>
      <li v-for="etape in reglementation.milestones" :key="`${etape.date}-${etape.obligation}`">
        <time :datetime="etape.date">{{ dateLisible(etape.date) }}</time>
        <div>
          <strong>{{ OBLIGATIONS[etape.obligation] || etape.obligation }} : {{ etape.scope }}</strong>
          <br />
          <small>{{ etape.label }}</small>
        </div>
      </li>
    </ol>

    <aside data-severity="warning" style="margin-top: 1rem">
      <p>{{ reglementation.deferralNote }}</p>
    </aside>

    <p style="margin-top: 1rem">
      <small>
        Base légale : {{ reglementation.legalBasis }}
        Calendrier vérifié le
        <time :datetime="reglementation.verifiedOn">{{ dateLisible(reglementation.verifiedOn) }}</time>.
      </small>
    </p>

    <p>
      <small>
        La transmission s'effectue par une <strong>{{ reglementation.terminology.transmissionOperator }}</strong>.
        L'appellation « {{ reglementation.terminology.deprecated }} » n'est plus celle en vigueur.
      </small>
    </p>
  </section>
</template>
