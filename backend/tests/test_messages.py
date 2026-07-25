"""Tests du catalogue de messages francais.

Les regles EN 16931 sont formulees en anglais. La traduction est le principal
apport de cet outil pour un editeur francais, mais elle ne doit ni inventer, ni
perdre la trace du texte d'origine. Ces tests verifient les deux.
"""

from __future__ import annotations

import pytest

from app.engine import messages


class TestCatalogueRedige:
    @pytest.mark.parametrize(
        "rule_id,attendu",
        [
            ("BR-01", "identifiant de spécification"),
            ("BR-02", "numéro de facture"),
            ("BR-16", "au moins une ligne de facture"),
            ("BR-CO-15", "montant total"),
            ("BR-CL-04", "ISO 4217"),
        ],
    )
    def test_regles_courantes_traduites(self, rule_id, attendu):
        message, source = messages.translate(rule_id, "texte anglais ignoré")
        assert source == "catalogue_fr"
        assert attendu in message

    def test_familles_de_tva_couvertes(self):
        """Les dix regles de chaque famille de categorie de TVA sont presentes."""
        for famille in ("S", "Z", "E", "AE", "G", "IC", "O", "AF", "AG"):
            for numero in range(1, 11):
                rule_id = f"BR-{famille}-{numero:02d}"
                assert rule_id in messages.RULES_FR, f"manquant : {rule_id}"

    def test_libelle_de_categorie_present_dans_le_message(self):
        message, _ = messages.translate("BR-IC-01", "")
        assert "livraison intracommunautaire" in message
        message, _ = messages.translate("BR-AE-05", "")
        assert "autoliquidation" in message

    def test_contrainte_de_taux_correcte_par_famille(self):
        """Taux normal : superieur a zero. Taux zero : egal a zero."""
        normal, _ = messages.translate("BR-S-05", "")
        assert "supérieur à zéro" in normal

        zero, _ = messages.translate("BR-Z-05", "")
        assert "égal à zéro" in zero

        hors_champ, _ = messages.translate("BR-O-05", "")
        assert "ne doit pas être renseigné" in hors_champ

    def test_motif_exoneration_selon_la_famille(self):
        exonere, _ = messages.translate("BR-E-10", "")
        assert "doit comporter" in exonere

        taux_normal, _ = messages.translate("BR-S-10", "")
        assert "ne doit comporter ni" in taux_normal

    def test_aucun_message_vide_ou_tronque(self):
        for rule_id, message in messages.RULES_FR.items():
            assert message.strip(), rule_id
            assert message.endswith((".", ")")), f"{rule_id} : {message[-40:]}"
            assert "{" not in message, f"gabarit non substitué dans {rule_id}"


class TestGabarits:
    @pytest.mark.parametrize(
        "original,attendu",
        [
            ("- TypeCode should not be present", "ne devrait pas être présent"),
            ("- ID shall not be used.", "ne doit pas être utilisé"),
            ("- GuidelineSpecifiedDocumentContextParameter must exist exactly once",
             "exactement une fois"),
            ("- IncludedNote should exist maximum once", "plus d'une fois"),
            ("A UBL invoice should not include the UUID", "ne devrait pas comporter"),
            ("Payment means text shall occur maximum once", "plus d'une fois"),
            ("Scheme name attribute should not be present", "L'attribut"),
        ],
    )
    def test_formes_mecaniques_traduites(self, original, attendu):
        message, source = messages.translate("CII-SR-999", original)
        assert source == "gabarit_fr", message
        assert attendu in message

    def test_regle_de_decimales_utilise_le_libelle_metier(self):
        message, source = messages.translate(
            "BR-DEC-12",
            "The allowed maximum number of decimals for the Invoice total amount "
            "without VAT (BT-109) is 2.",
        )
        assert source == "gabarit_fr"
        assert "montant total hors TVA" in message
        assert "BT-109" in message
        assert "2" in message

    def test_element_avec_arobase_reconnu(self):
        """Les attributs XML comme @format doivent passer le gabarit."""
        message, source = messages.translate(
            "CII-DT-013", "- @format should not be present"
        )
        assert source == "gabarit_fr"
        assert "@format" in message

    def test_formulation_ubl_reste_grammaticale_au_pluriel(self):
        message, _ = messages.translate(
            "UBL-CR-001", "A UBL invoice should not include extensions"
        )
        # La tournure avec deux points evite un accord d'article impossible a deviner.
        assert message == "Une facture UBL ne devrait pas comporter : extensions."


class TestRepliAnglais:
    def test_texte_inconnu_conserve_tel_quel(self):
        original = "Some entirely unexpected wording from a future release."
        message, source = messages.translate("XX-999", original)
        assert source == "original_en"
        assert message == original

    def test_pas_de_traduction_inventee(self):
        """Un message non reconnu ne doit jamais etre remplace par autre chose."""
        original = "An invoice line shall not contain more than one X with TypeCode 130."
        message, source = messages.translate("CII-SR-474", original)
        assert source == "original_en"
        assert message == original


class TestMessagesXsd:
    def test_element_inattendu(self):
        message, source = messages.translate_xsd(
            "Element '{urn:un:unece:uncefact:data:standard:"
            "ReusableAggregateBusinessInformationEntity:100}Bidon': This element is "
            "not expected. Expected is ( {urn:un:unece:uncefact:data:standard:"
            "ReusableAggregateBusinessInformationEntity:100}TypeCode )."
        )
        assert source == "gabarit_fr"
        assert "n'est pas attendu" in message
        assert "ram:Bidon" in message
        assert "ram:TypeCode" in message
        assert "urn:un:unece" not in message

    def test_enfant_obligatoire_manquant(self):
        message, source = messages.translate_xsd(
            "Element '{urn:x}Parent': Missing child element(s). Expected is ( {urn:x}Fils )."
        )
        assert source == "gabarit_fr"
        assert "manque un élément obligatoire" in message

    def test_valeur_de_type_invalide(self):
        message, source = messages.translate_xsd(
            "Element '{urn:x}Montant': 'abc' is not a valid value of the atomic type "
            "'xs:decimal'."
        )
        assert source == "gabarit_fr"
        assert "abc" in message
        assert "xs:decimal" in message

    def test_prefixes_appliques_meme_sans_gabarit(self):
        message, source = messages.translate_xsd(
            "Une tournure inedite sur {urn:oasis:names:specification:ubl:schema:xsd:"
            "CommonBasicComponents-2}ID."
        )
        assert source == "original_en"
        assert "cbc:ID" in message

    def test_couverture_annoncee(self):
        couverture = messages.coverage()
        assert couverture["cataloguedRules"] > 200
        assert couverture["templates"] > 10
