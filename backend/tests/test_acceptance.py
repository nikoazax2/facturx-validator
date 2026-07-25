"""Les quatre criteres d'acceptation, un test par critere.

Ces tests sont volontairement redigees comme des affirmations sur le comportement
visible du service, pas sur son implementation : ils doivent rester valables si le
moteur interne change.
"""

from __future__ import annotations

import json

from conftest import findings, level, load_sample, rule_ids


class TestCritere1FacturXValide:
    """Un Factur-X EN 16931 valide : verdict conforme, profil detecte, zero erreur."""

    def test_verdict_conforme_et_zero_erreur(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        assert report["summary"]["errors"] == 0, findings(report, severity="error")
        assert report["verdict"]["code"] == "conforme"

    def test_profil_detecte(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        assert report["document"]["profile"]["code"] == "EN16931"
        assert report["document"]["profile"]["recognised"] is True
        assert report["document"]["profile"]["urn"] == "urn:cen.eu:en16931:2017"
        assert report["document"]["syntax"] == "CII"

    def test_les_trois_niveaux_sont_franchis(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        assert level(report, "container")["status"] == "passed"
        assert level(report, "xsd")["status"] == "passed"
        assert level(report, "en16931")["status"] == "passed"

    def test_piece_jointe_identifiee_parmi_plusieurs(self, validate):
        """L'echantillon porte deux pieces jointes : le XML doit etre isole."""
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        attachment = report["document"]["attachment"]
        assert attachment["count"] == 2
        assert attachment["selected"] == "factur-x.xml"


class TestCritere2PdfSansXml:
    """Un PDF sans XML incorpore : message explicite, pas d'erreur technique."""

    def test_message_explicite_et_actionnable(self, validate):
        report = validate(load_sample("02-pdf-sans-xml.pdf"), "02-pdf-sans-xml.pdf")

        container = findings(report, level_id="container", severity="error")
        assert len(container) == 1
        message = container[0]["message"]

        # Le message doit nommer le probleme et le nom de fichier attendu, sans
        # exposer de detail d'implementation.
        assert "aucune pièce jointe" in message.lower()
        assert "factur-x.xml" in message
        for leak in ("Traceback", "pikepdf", "None", "Exception", "/EF"):
            assert leak not in message

    def test_pas_de_plantage_et_rapport_complet(self, validate):
        report = validate(load_sample("02-pdf-sans-xml.pdf"), "02-pdf-sans-xml.pdf")

        assert report["verdict"]["code"] == "non_evaluable"
        # Les niveaux non atteints sont declares, et motives.
        assert level(report, "xsd")["status"] == "skipped"
        assert level(report, "en16931")["status"] == "skipped"
        assert level(report, "xsd")["reason"]
        assert level(report, "en16931")["reason"]

    def test_le_pdf_reste_decrit(self, validate):
        """Meme sans XML, ce qui a pu etre lu du PDF est rapporte."""
        report = validate(load_sample("02-pdf-sans-xml.pdf"), "02-pdf-sans-xml.pdf")

        attachment = report["document"]["attachment"]
        assert attachment["count"] == 0
        assert attachment["pageCount"] >= 1
        assert report["input"]["kind"] == "pdf"


class TestCritere3ChampObligatoireManquant:
    """Un champ obligatoire manquant : erreur portant le code de regle et le XPath."""

    def test_code_de_regle_et_xpath_presents(self, validate):
        name = "05-en16931-champ-obligatoire-manquant.xml"
        report = validate(load_sample(name), name)

        errors = findings(report, level_id="en16931", severity="error")
        assert errors, "aucune erreur EN 16931 relevee"

        # BR-07 : la facture doit indiquer le nom de l'acheteur (BT-44).
        matched = [e for e in errors if e["ruleId"] == "BR-07"]
        assert matched, f"BR-07 attendu, obtenu {rule_ids(report, level_id='en16931')}"

        finding = matched[0]
        assert finding["ruleId"] == "BR-07"
        assert finding["xpath"], "le XPath est obligatoire dans le constat"
        assert finding["xpath"].startswith("/")
        assert finding["severity"] == "error"

    def test_message_en_francais_et_tracable(self, validate):
        name = "05-en16931-champ-obligatoire-manquant.xml"
        report = validate(load_sample(name), name)

        finding = next(f for f in report["findings"] if f["ruleId"] == "BR-07")
        assert finding["messageSource"] == "catalogue_fr"
        assert "acheteur" in finding["message"].lower()
        # Le texte d'origine reste joint, pour que la traduction soit verifiable.
        assert finding["messageOriginal"]
        assert "Buyer name" in finding["messageOriginal"]
        # Le test Schematron evalue est conserve.
        assert finding["test"]

    def test_xsd_valide_mais_en16931_en_echec(self, validate):
        """Le coeur de la separation des niveaux : le premier passe, le second non."""
        name = "05-en16931-champ-obligatoire-manquant.xml"
        report = validate(load_sample(name), name)

        assert level(report, "xsd")["status"] == "passed"
        assert level(report, "en16931")["status"] == "failed"
        assert report["verdict"]["code"] == "non_conforme"


class TestCritere4JsonExploitable:
    """Le JSON exporte doit etre utilisable par un script tiers."""

    def test_serialisable_sans_perte(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        encoded = json.dumps(report, ensure_ascii=False)
        decoded = json.loads(encoded)
        assert decoded == json.loads(json.dumps(report, ensure_ascii=False))

        # Aucune enumeration ne doit fuir sous forme d'objet Python.
        assert "<" not in encoded.replace("\\u003c", "")

    def test_cles_racine_stables(self, validate):
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        assert report["schemaVersion"] == "1.0"
        for key in (
            "generatedAt",
            "verdict",
            "input",
            "document",
            "levels",
            "findings",
            "summary",
            "notices",
            "regulatory",
            "engine",
        ):
            assert key in report, f"cle racine manquante : {key}"

    def test_types_previsibles(self, validate):
        name = "06-en16931-totaux-incoherents.xml"
        report = validate(load_sample(name), name)

        assert isinstance(report["summary"]["errors"], int)
        assert isinstance(report["findings"], list)
        assert isinstance(report["levels"], list)

        for finding in report["findings"]:
            assert set(finding) >= {
                "index",
                "level",
                "severity",
                "ruleId",
                "xpath",
                "message",
                "messageSource",
            }
            assert finding["severity"] in {"error", "warning", "info"}
            assert finding["level"] in {"container", "xsd", "en16931", "frctc"}
            assert isinstance(finding["index"], int)

        for entry in report["levels"]:
            assert entry["status"] in {
                "passed",
                "failed",
                "warning",
                "skipped",
                "not_applicable",
            }

    def test_index_sequentiel_et_totaux_coherents(self, validate):
        name = "06-en16931-totaux-incoherents.xml"
        report = validate(load_sample(name), name)

        indexes = [f["index"] for f in report["findings"]]
        assert indexes == list(range(1, len(indexes) + 1))

        counted = {"error": 0, "warning": 0, "info": 0}
        for finding in report["findings"]:
            counted[finding["severity"]] += 1
        assert counted["error"] == report["summary"]["errors"]
        assert counted["warning"] == report["summary"]["warnings"]

        # Le detail par niveau doit se recouper avec le total.
        assert sum(v["errors"] for v in report["summary"]["byLevel"].values()) == (
            report["summary"]["errors"]
        )

    def test_provenance_des_artefacts_citee(self, validate):
        """Un tiers doit pouvoir savoir contre quoi la validation a ete faite."""
        report = validate(load_sample("01-valide-en16931.pdf"), "01-valide-en16931.pdf")

        artifacts = report["engine"]["artifacts"]
        assert artifacts["en16931SchematronVersion"]
        assert artifacts["sources"]
        for source in artifacts["sources"]:
            assert source["role"]
            assert source["sha256"]
