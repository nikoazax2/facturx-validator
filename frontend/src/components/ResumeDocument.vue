<script setup>
import { computed } from 'vue'

const props = defineProps({
  rapport: { type: Object, required: true }
})

const identification = computed(() => props.rapport.document.identification ?? {})
const piece = computed(() => props.rapport.document.attachment ?? null)
// Logiciel declare par le fichier. Metadonnee technique, sans rapport avec les
// donnees de la facture : utile au lecteur pour situer l'origine d'un ecart.
const emetteur = computed(() => props.rapport.document.producer ?? null)

const montant = computed(() => {
  const valeur = identification.value.grandTotalAmount
  if (!valeur) return null
  const devise = identification.value.currency
  return devise ? `${valeur} ${devise}` : valeur
})

const declarationPdfa = computed(() => {
  if (!piece.value?.pdfaPart) return 'non déclarée'
  const niveau = piece.value.pdfaConformance
  return `PDF/A-${piece.value.pdfaPart}${niveau ? niveau.toLowerCase() : ''}`
})

const kilooctets = (octets) => `${(octets / 1024).toFixed(0)} Ko`
</script>

<template>
  <section>
    <h2>Le document lu</h2>

    <dl>
      <dt>Fichier déposé</dt>
      <dd>
        {{ rapport.input.filename }}
        <small>({{ kilooctets(rapport.input.sizeBytes) }})</small>
      </dd>

      <template v-if="rapport.document.profile">
        <dt>Profil Factur-X</dt>
        <dd>
          {{ rapport.document.profile.label }}
          <small v-if="!rapport.document.profile.recognised">(non reconnu)</small>
        </dd>

        <dt>Identifiant de spécification</dt>
        <dd>
          <code>{{ rapport.document.profile.urn || 'absent' }}</code>
        </dd>
      </template>

      <template v-if="rapport.document.syntax">
        <dt>Syntaxe</dt>
        <dd>
          {{ rapport.document.syntax }}
          <small v-if="rapport.document.xsdFlavour">
            (schéma {{ rapport.document.xsdFlavour }})
          </small>
        </dd>
      </template>

      <template v-if="identification.invoiceNumber">
        <dt>Numéro de facture</dt>
        <dd>{{ identification.invoiceNumber }}</dd>
      </template>

      <template v-if="identification.issueDate">
        <dt>Date d'émission</dt>
        <dd>
          <time :datetime="identification.issueDate">{{ identification.issueDate }}</time>
        </dd>
      </template>

      <template v-if="identification.typeCode">
        <dt>Type de document</dt>
        <dd>
          {{ identification.typeLabel || 'code non répertorié' }}
          <small>(code {{ identification.typeCode }})</small>
        </dd>
      </template>

      <template v-if="identification.sellerName">
        <dt>Vendeur</dt>
        <dd>{{ identification.sellerName }}</dd>
      </template>

      <template v-if="identification.buyerName">
        <dt>Acheteur</dt>
        <dd>{{ identification.buyerName }}</dd>
      </template>

      <template v-if="montant">
        <dt>Montant total</dt>
        <dd>{{ montant }}</dd>
      </template>

      <template v-if="identification.lineCount !== undefined">
        <dt>Lignes de facture</dt>
        <dd>{{ identification.lineCount }}</dd>
      </template>
    </dl>

    <template v-if="piece">
      <h3>La pièce jointe et le conteneur</h3>
      <dl>
        <dt>Pièces jointes trouvées</dt>
        <dd>
          {{ piece.count }}
          <template v-if="piece.names && piece.names.length">
            :
            <code v-for="nom in piece.names" :key="nom">{{ nom }}</code>
          </template>
        </dd>

        <template v-if="piece.selected">
          <dt>XML retenu</dt>
          <dd>
            <code>{{ piece.selected }}</code>
            <small v-if="piece.selectedSizeBytes">
              ({{ kilooctets(piece.selectedSizeBytes) }})
            </small>
          </dd>

          <dt>
            <abbr title="Nature du lien entre le PDF et le fichier incorporé">
              AFRelationship
            </abbr>
          </dt>
          <dd>
            <code>{{ piece.afRelationship || 'absente' }}</code>
          </dd>

          <dt>Type MIME déclaré</dt>
          <dd>
            <code>{{ piece.mimeSubtype || 'absent' }}</code>
          </dd>
        </template>

        <dt>Version PDF</dt>
        <dd>
          {{ piece.pdfVersion || 'inconnue' }}
          <small v-if="piece.pageCount">, {{ piece.pageCount }} page(s)</small>
        </dd>

        <dt>Déclaration PDF/A</dt>
        <dd>{{ declarationPdfa }}</dd>

        <template v-if="emetteur">
          <dt>Logiciel émetteur</dt>
          <dd>
            {{ emetteur.label }}
            <small v-if="emetteur.producer && emetteur.producer !== emetteur.label">
              Écrit par {{ emetteur.producer }}.
            </small>
            <small>
              Déclaré par le fichier lui-même, dans ses métadonnées.
            </small>
          </dd>
        </template>

        <template v-if="piece.xmpFacturX">
          <dt>Métadonnées XMP Factur-X</dt>
          <dd>
            <code v-for="(valeur, cle) in piece.xmpFacturX" :key="cle">
              {{ cle }} = {{ valeur }}
            </code>
          </dd>
        </template>
      </dl>
    </template>
  </section>
</template>

<style scoped>
h3 {
  margin-top: 1.5rem;
}

dd > code + code {
  margin-left: 0.4rem;
}
</style>
