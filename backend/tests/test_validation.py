"""Tests du comportement du moteur au-dela des criteres d'acceptation."""

from __future__ import annotations

import pytest

from conftest import findings, level, load_fixture, load_sample, rule_ids


class TestDetectionSyntaxe:
    def test_cii_reconnu(self, validate):
        report = validate(load_fixture("factur-x-en16931.xml"), "a.xml")
        assert report["document"]["syntax"] == "CII"

    def test_ubl_reconnu_et_route_vers_ses_regles(self, validate):
        """Ne jamais supposer du CII : l'UBL doit suivre sa propre liaison."""
        report = validate(load_sample("07-ubl-valide.xml"), "07-ubl-valide.xml")

        assert report["document"]["syntax"] == "UBL"
        assert report["document"]["xsdFlavour"] == "ubl-2.1:invoice"
        assert level(report, "en16931")["status"] == "passed"
        assert report["summary"]["errors"] == 0

    def test_zugferd_1_signale_comme_historique(self, validate):
        report = validate(load_fixture("zugferd-comfort.xml"), "z.xml")

        errors = findings(report, severity="error")
        assert errors
        assert "ZUGFeRD 1.0" in errors[0]["message"]
        assert report["verdict"]["code"] == "non_evaluable"

    def test_xml_mal_forme_donne_un_message_lisible(self, validate):
        report = validate(load_sample("08-xml-mal-forme.xml"), "08-xml-mal-forme.xml")

        errors = findings(report, level_id="xsd", severity="error")
        assert len(errors) == 1
        assert errors[0]["ruleId"] == "FX-XML-001"
        assert "bien formé" in errors[0]["message"]
        assert "ligne" in errors[0]["message"]
        assert level(report, "en16931")["status"] == "skipped"

    def test_contenu_non_xml_refuse_proprement(self, validate):
        report = validate(b"ceci n'est pas un document", "note.xml")
        assert report["verdict"]["code"] == "non_evaluable"
        assert findings(report, severity="error")


class TestPorteeEN16931:
    """MINIMUM et BASIC WL ne declarent pas EN 16931 : le niveau doit etre ecarte."""

    @pytest.mark.parametrize(
        "fixture,expected",
        [
            ("factur-x-minimum.xml", "MINIMUM"),
            ("factur-x-basicwl.xml", "BASIC_WL"),
        ],
    )
    def test_niveau_declare_non_applicable_avec_motif(self, validate, fixture, expected):
        report = validate(load_fixture(fixture), fixture)

        assert report["document"]["profile"]["code"] == expected
        en16931 = level(report, "en16931")
        assert en16931["status"] == "not_applicable"
        assert en16931["errors"] == 0
        # Le motif doit expliquer pourquoi, sans laisser croire a une reussite.
        assert en16931["reason"]
        assert "EN 16931" in en16931["reason"]

    @pytest.mark.parametrize(
        "fixture", ["factur-x-basic.xml", "factur-x-en16931.xml", "factur-x-extended.xml"]
    )
    def test_niveau_execute_pour_les_profils_conformes(self, validate, fixture):
        report = validate(load_fixture(fixture), fixture)

        assert report["document"]["profile"]["en16931Scope"] is True
        assert level(report, "en16931")["status"] in {"passed", "warning", "failed"}
        assert "en16931" in report["engine"]["levelsRun"]

    def test_profils_valides_sans_erreur(self, validate):
        for fixture in (
            "factur-x-minimum.xml",
            "factur-x-basicwl.xml",
            "factur-x-basic.xml",
            "factur-x-en16931.xml",
        ):
            report = validate(load_fixture(fixture), fixture)
            assert report["summary"]["errors"] == 0, (
                fixture,
                findings(report, severity="error"),
            )


class TestProfilMinimum:
    """Le profil MINIMUM ne vaut pas facture complete : il faut le dire."""

    def test_avertissement_fiscal_present(self, validate):
        report = validate(load_sample("03-profil-minimum.pdf"), "03-profil-minimum.pdf")

        assert report["document"]["profile"]["code"] == "MINIMUM"
        assert report["document"]["profile"]["fiscallyComplete"] is False

        notices = {n["code"]: n for n in report["notices"]}
        assert "PROFIL_INCOMPLET" in notices
        notice = notices["PROFIL_INCOMPLET"]
        assert notice["severity"] == "warning"
        assert "fiscale" in notice["message"]

    def test_pas_traite_comme_une_erreur_bloquante(self, validate):
        """Le profil est licite : c'est un avertissement, pas une non-conformite."""
        report = validate(load_fixture("factur-x-minimum.xml"), "m.xml")

        assert report["summary"]["errors"] == 0
        assert report["verdict"]["code"] in {
            "conforme",
            "conforme_avec_avertissements",
        }


class TestProfilInconnu:
    def test_urn_non_reconnu_avertit_sans_bloquer(self, validate):
        report = validate(load_sample("09-profil-inconnu.xml"), "09-profil-inconnu.xml")

        assert report["document"]["profile"]["recognised"] is False
        assert "FX-PROFILE-002" in rule_ids(report, level_id="xsd")
        assert report["summary"]["errors"] == 0

    def test_absence_de_guideline_id_est_une_erreur(self, validate):
        import re

        text = load_fixture("factur-x-en16931.xml").decode("utf-8")
        stripped = re.sub(
            r"<ram:GuidelineSpecifiedDocumentContextParameter>.*?"
            r"</ram:GuidelineSpecifiedDocumentContextParameter>",
            "",
            text,
            count=1,
            flags=re.S,
        )
        report = validate(stripped.encode("utf-8"), "sans-profil.xml")

        assert "FX-PROFILE-001" in rule_ids(report, level_id="xsd")
        assert findings(report, level_id="xsd", severity="error")


class TestSeparationDesNiveaux:
    """Un fichier peut passer un niveau et echouer l'autre, dans les deux sens."""

    def test_xsd_en_echec_mais_en16931_conforme(self, validate):
        report = validate(load_sample("04-xsd-invalide.xml"), "04-xsd-invalide.xml")

        assert level(report, "xsd")["status"] == "failed"
        assert level(report, "en16931")["status"] == "passed"

        error = findings(report, level_id="xsd", severity="error")[0]
        assert error["ruleId"] == "XSD"
        assert error["xpath"]
        assert "ElementQuiNExistePas" in (error["xpath"] or "")

    def test_xsd_conforme_mais_en16931_en_echec(self, validate):
        name = "06-en16931-totaux-incoherents.xml"
        report = validate(load_sample(name), name)

        assert level(report, "xsd")["status"] == "passed"
        assert level(report, "en16931")["status"] == "failed"
        assert "BR-CO-15" in rule_ids(report, level_id="en16931")

    def test_messages_xsd_traduits_en_francais(self, validate):
        report = validate(load_sample("04-xsd-invalide.xml"), "04-xsd-invalide.xml")

        error = findings(report, level_id="xsd", severity="error")[0]
        assert error["messageSource"] == "gabarit_fr"
        assert "élément" in error["message"]
        # Les URI d'espaces de noms sont remplaces par les prefixes usuels.
        assert "urn:un:unece" not in error["message"]
        assert "ram:" in error["message"]


class TestNiveauProfil:
    """Regles metier propres au profil, evaluees par le Schematron FNFE.

    C'est le seul niveau de regles metier applicable a MINIMUM et BASIC WL : sans
    lui, ces deux profils ne recevaient aucun controle metier.
    """

    @pytest.mark.parametrize(
        "fixture",
        [
            "factur-x-minimum.xml",
            "factur-x-basicwl.xml",
            "factur-x-basic.xml",
            "factur-x-en16931.xml",
            "factur-x-extended.xml",
        ],
    )
    def test_execute_sans_faux_positif_sur_fichier_valide(self, validate, fixture):
        report = validate(load_fixture(fixture), fixture)

        profil = level(report, "profil")
        assert profil["status"] == "passed", findings(report, level_id="profil")
        assert profil["errors"] == 0
        assert "profil" in report["engine"]["levelsRun"]

    @pytest.mark.parametrize(
        "fixture,profil_attendu",
        [("factur-x-minimum.xml", "MINIMUM"), ("factur-x-basicwl.xml", "BASIC_WL")],
    )
    def test_couvre_les_profils_hors_perimetre_en16931(
        self, validate, fixture, profil_attendu
    ):
        """Le trou fonctionnel que ce niveau comble."""
        import re

        text = load_fixture(fixture).decode("utf-8")
        # Retirer le code pays du vendeur : BR-09 est une regle EN 16931 que le
        # profil reprend, alors que le niveau EN 16931 n'est pas applicable ici.
        casse = re.sub(r"<ram:CountryID>[^<]*</ram:CountryID>", "", text, count=1)
        report = validate(casse.encode("utf-8"), fixture)

        assert report["document"]["profile"]["code"] == profil_attendu
        assert level(report, "en16931")["status"] == "not_applicable"
        assert level(report, "profil")["status"] == "failed"
        assert "BR-09" in rule_ids(report, level_id="profil")

    def test_code_normalise_prime_sur_identifiant_interne(self, validate):
        """Le Schematron FNFE numerote en FX-SCH-A-*, mais cite le code EN 16931."""
        import re

        text = load_fixture("factur-x-minimum.xml").decode("utf-8")
        casse = re.sub(r"<ram:CountryID>[^<]*</ram:CountryID>", "", text, count=1)
        report = validate(casse.encode("utf-8"), "m.xml")

        constat = next(f for f in report["findings"] if f["ruleId"] == "BR-09")
        # Le code lisible est retenu, et la numerotation interne reste tracable.
        assert constat["internalRuleId"]
        assert constat["internalRuleId"].startswith("FX-SCH-")
        # Et grace a ce code, la traduction francaise s'applique.
        assert constat["messageSource"] == "catalogue_fr"
        assert "code pays" in constat["message"]

    def test_aucune_regle_comptee_deux_fois(self, validate):
        """Les deux Schematron se recouvrent : rien ne doit apparaitre en double."""
        name = "06-en16931-totaux-incoherents.xml"
        report = validate(load_sample(name), name)

        codes_en16931 = rule_ids(report, level_id="en16931")
        codes_profil = rule_ids(report, level_id="profil")
        assert codes_en16931
        assert not (codes_en16931 & codes_profil), "regle remontee dans les deux niveaux"

        # L'ecart est declare, pas silencieux.
        assert "écartés" in (level(report, "profil")["reason"] or "")

    def test_le_total_ne_double_pas(self, validate):
        """Sans dedoublonnage, ce fichier remonterait quatre erreurs au lieu de deux."""
        name = "06-en16931-totaux-incoherents.xml"
        report = validate(load_sample(name), name)

        assert report["summary"]["errors"] == 2
        assert rule_ids(report, level_id="en16931") == {"BR-CO-15", "BR-CO-16"}

    def test_apporte_des_regles_propres_au_profil(self, validate):
        """Au-dela d'EN 16931, le profil ajoute ses propres contraintes."""
        name = "05-en16931-champ-obligatoire-manquant.xml"
        report = validate(load_sample(name), name)

        profil = findings(report, level_id="profil", severity="error")
        assert profil, "le niveau du profil devrait apporter au moins un constat"
        # Cardinalite propre au profil, absente du jeu EN 16931.
        assert any("exactement" in f["message"] for f in profil)

    def test_sans_objet_pour_ubl(self, validate):
        report = validate(load_sample("07-ubl-valide.xml"), "07-ubl-valide.xml")

        profil = level(report, "profil")
        assert profil["status"] == "not_applicable"
        assert "UBL" in profil["reason"]

    def test_sans_objet_pour_profil_non_reconnu(self, validate):
        report = validate(load_sample("09-profil-inconnu.xml"), "09-profil-inconnu.xml")

        profil = level(report, "profil")
        assert profil["status"] == "not_applicable"
        assert profil["reason"]

    def test_niveau_toujours_present_dans_le_rapport(self, validate):
        """Meme quand le XML est hors d'atteinte, le niveau est declare."""
        for name in ("02-pdf-sans-xml.pdf", "08-xml-mal-forme.xml"):
            report = validate(load_sample(name), name)
            profil = level(report, "profil")
            assert profil["status"] == "skipped"
            assert profil["reason"]


class TestConteneurPdf:
    def test_af_relationship_lue_et_jugee_selon_le_profil(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        assert report["document"]["attachment"]["afRelationship"] == "Source"
        # Source est admise par la specification francaise pour EN 16931 : ce n'est
        # donc ni une erreur ni un avertissement, mais une remarque sur l'usage
        # allemand.
        assert "FX-PDF-034" in rule_ids(report, level_id="container")
        assert level(report, "container")["errors"] == 0

    def test_af_relationship_incorrecte_pour_minimum(self, validate):
        """MINIMUM attend Data : l'echantillon porte Source, donc un avertissement."""
        report = validate(load_sample("03-profil-minimum.pdf"), "03-profil-minimum.pdf")

        assert "FX-PDF-033" in rule_ids(report, level_id="container")
        warnings = [
            f for f in findings(report, level_id="container") if f["ruleId"] == "FX-PDF-033"
        ]
        assert warnings[0]["severity"] == "warning"
        assert "Data" in warnings[0]["message"]

    def test_metadonnees_xmp_lues(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        attachment = report["document"]["attachment"]
        assert attachment["pdfaPart"] == "3"
        assert attachment["pdfaConformance"] in {"A", "B", "U"}
        xmp = attachment["xmpFacturX"]
        assert xmp["DocumentType"] == "INVOICE"
        assert xmp["DocumentFileName"] == "factur-x.xml"
        assert xmp["ConformanceLevel"] == "EN 16931"

    def test_bom_utf8_ne_bloque_pas_le_schematron(self, validate):
        """Le XML incorpore de l'echantillon porte un BOM, tres courant en pratique."""
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        assert level(report, "en16931")["status"] == "passed"
        assert "en16931" in report["engine"]["levelsRun"]

    def test_xml_seul_declare_le_conteneur_non_applicable(self, validate):
        report = validate(load_fixture("factur-x-en16931.xml"), "a.xml")

        container = level(report, "container")
        assert container["status"] == "not_applicable"
        assert container["reason"]

    def test_pdf_illisible_signale_sans_trace_technique(self, validate):
        report = validate(b"%PDF-1.4\nceci est tronque", "casse.pdf")

        errors = findings(report, level_id="container", severity="error")
        assert errors
        assert errors[0]["ruleId"] == "FX-PDF-001"
        assert "Traceback" not in errors[0]["message"]


class TestConfidentialiteEtReperes:
    def test_aucun_contenu_de_facture_dans_les_traces(self, validate):
        """L'empreinte identifie le fichier sans le conserver."""
        raw = load_fixture("factur-x-en16931.xml")
        report = validate(raw, "a.xml")

        assert len(report["input"]["sha256"]) == 64
        assert report["input"]["sizeBytes"] == len(raw)

    def test_reperes_reglementaires_joints(self, validate):
        report = validate(load_fixture("factur-x-en16931.xml"), "a.xml")

        regulatory = report["regulatory"]
        assert regulatory["verifiedOn"] == "2026-07-24"
        dates = {m["date"] for m in regulatory["milestones"]}
        assert "2026-09-01" in dates
        assert "2027-09-01" in dates
        assert regulatory["deferralNote"]

    def test_terminologie_plateforme_agreee(self, validate):
        """Le terme PDP n'est plus en vigueur : il ne doit pas etre presente comme tel."""
        report = validate(load_fixture("factur-x-en16931.xml"), "a.xml")

        terminology = report["regulatory"]["terminology"]
        assert "Plateforme Agréée" in terminology["transmissionOperator"]
        assert "PDP" in terminology["deprecated"]

        # Nulle part ailleurs le terme PDP ne doit apparaitre comme terme courant.
        import json

        payload = json.dumps(
            {k: v for k, v in report.items() if k != "regulatory"}, ensure_ascii=False
        )
        assert "PDP" not in payload

    def test_duree_mesuree_et_niveaux_traces(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        assert report["engine"]["durationMs"] > 0
        assert "container" in report["engine"]["levelsRun"]
        assert report["engine"]["messageCatalogue"]["cataloguedRules"] > 200
