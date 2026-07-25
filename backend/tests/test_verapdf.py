"""Tests de l'audit PDF/A par veraPDF.

veraPDF n'etant pas une dependance Python, il n'est pas toujours installe. Les
tests qui l'exigent se sautent alors, mais ceux qui verifient la degradation
propre s'executent toujours : un outil absent ne doit jamais se traduire par un
niveau franchi.

Pour executer la totalite, renseigner VERAPDF_JAR et VERAPDF_ENABLED=1.
"""

from __future__ import annotations

import io
import os

import pytest

from conftest import findings, level, load_sample


def verapdf_disponible() -> bool:
    from app import config
    from app.engine import verapdf

    if not os.getenv("VERAPDF_JAR"):
        return False
    utilisable, _ = verapdf.configure()
    return utilisable or bool(config.VERAPDF_JAR)


exige_verapdf = pytest.mark.skipif(
    not verapdf_disponible(),
    reason="veraPDF absent : renseignez VERAPDF_JAR et VERAPDF_ENABLED=1",
)


@pytest.fixture
def pdf_ordinaire() -> bytes:
    """Un PDF valide mais sans aucun marqueur PDF/A."""
    import pikepdf

    document = pikepdf.new()
    document.add_blank_page(page_size=(595, 842))
    tampon = io.BytesIO()
    document.save(tampon)
    return tampon.getvalue()


class TestDegradationPropre:
    """Le comportement quand veraPDF n'est pas utilisable."""

    def test_niveau_saute_et_motive_quand_desactive(self, validate, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "VERAPDF_ENABLED", False)
        report = validate(load_sample("01-valide-en16931.pdf"), "a.pdf")

        pdfa = level(report, "pdfa")
        assert pdfa["status"] == "skipped"
        assert pdfa["errors"] == 0
        assert "désactivé" in pdfa["reason"]
        # La réserve sur la portée des contrôles doit rester affichée.
        codes = {notice["code"] for notice in report["notices"]}
        assert "PDFA_PORTEE" in codes
        assert "PDFA_AUDIT" not in codes

    def test_jar_introuvable_ne_fait_pas_echouer_la_validation(
        self, validate, monkeypatch
    ):
        from app import config

        monkeypatch.setattr(config, "VERAPDF_ENABLED", True)
        monkeypatch.setattr(config, "VERAPDF_JAR", "/chemin/qui/n/existe/pas.jar")

        report = validate(load_sample("01-valide-en16931.pdf"), "a.pdf")

        assert level(report, "pdfa")["status"] == "skipped"
        assert "introuvable" in level(report, "pdfa")["reason"]
        # Le reste de la validation doit se dérouler normalement.
        assert level(report, "en16931")["status"] == "passed"
        assert report["summary"]["errors"] == 0

    def test_java_absent_signale_sans_planter(self, monkeypatch):
        from app import config
        from app.engine import verapdf

        monkeypatch.setattr(config, "VERAPDF_ENABLED", True)
        monkeypatch.setattr(config, "VERAPDF_JAR", __file__)
        monkeypatch.setattr(config, "JAVA_BIN", "java-qui-n-existe-pas")

        resultat = verapdf.auditer(b"%PDF-1.4\n")

        assert resultat.disponible is False
        assert "introuvable" in (resultat.erreur or "")

    def test_sans_objet_pour_un_xml(self, validate):
        report = validate(load_sample("07-ubl-valide.xml"), "a.xml")

        pdfa = level(report, "pdfa")
        assert pdfa["status"] == "not_applicable"
        assert "XML seul" in pdfa["reason"]

    def test_niveau_toujours_present(self, validate):
        """Même sur les chemins d'arrêt précoce, le niveau est déclaré."""
        for name in ("02-pdf-sans-xml.pdf", "08-xml-mal-forme.xml"):
            report = validate(load_sample(name), name)
            assert level(report, "pdfa")["status"] in {
                "skipped",
                "not_applicable",
                "passed",
                "failed",
            }


class TestLectureDuRapport:
    """Analyse de la sortie de veraPDF, sans l'appeler."""

    def test_message_d_aide_avant_le_xml_est_ignore(self):
        from app.engine.verapdf import _extraire_xml

        sortie = b"Some help text printed first\n<?xml version='1.0'?><report/>"
        assert _extraire_xml(sortie).startswith(b"<?xml")

    def test_sortie_vide(self):
        from app.engine.verapdf import _extraire_xml

        assert _extraire_xml(b"") is None
        assert _extraire_xml(b"aucune balise ici") is None

    def test_rapport_conforme(self):
        from app.engine.verapdf import _lire_rapport

        xml = b"""<report><jobs><job>
          <validationReport profileName="PDF/A-3b validation profile" isCompliant="true">
            <details passedRules="146" failedRules="0" passedChecks="31173"
                     failedChecks="0"/>
          </validationReport></job></jobs></report>"""

        resultat = _lire_rapport(xml, 1200.0)

        assert resultat.conforme is True
        assert resultat.regles_passees == 146
        assert resultat.echecs == []
        assert resultat.erreur is None

    def test_rapport_non_conforme(self):
        from app.engine.verapdf import _lire_rapport

        xml = b"""<report><jobs><job>
          <validationReport profileName="PDF/A-3b validation profile" isCompliant="false">
            <details passedRules="145" failedRules="1" passedChecks="61" failedChecks="1"/>
            <rule specification="ISO 19005-3:2012" clause="6.6.2.1" testNumber="1"
                  status="failed" failedChecks="1">
              <description>The Catalog dictionary shall contain the Metadata key.</description>
              <check status="failed"><context>root/document[0]</context></check>
            </rule>
          </validationReport></job></jobs></report>"""

        resultat = _lire_rapport(xml, 1000.0)

        assert resultat.conforme is False
        assert len(resultat.echecs) == 1
        echec = resultat.echecs[0]
        assert echec.code == "PDFA-6.6.2.1-1"
        assert echec.clause == "6.6.2.1"
        assert echec.contexte == "root/document[0]"
        assert "Metadata" in echec.description

    def test_regles_passees_non_comptees_comme_echecs(self):
        from app.engine.verapdf import _lire_rapport

        xml = b"""<report><jobs><job>
          <validationReport isCompliant="true">
            <details passedRules="2" failedRules="0"/>
            <rule clause="6.1.1" testNumber="1" status="passed"><description>ok</description></rule>
          </validationReport></job></jobs></report>"""

        assert _lire_rapport(xml, 0.0).echecs == []

    def test_document_illisible_est_une_erreur_pas_une_conformite(self):
        from app.engine.verapdf import _lire_rapport

        xml = b"""<report><jobs><job/></jobs>
          <batchSummary failedToParse="1"><validationReports>0</validationReports>
          </batchSummary></report>"""

        resultat = _lire_rapport(xml, 0.0)

        assert resultat.conforme is None
        assert resultat.erreur is not None
        assert "analyser" in resultat.erreur


class TestMessagesFrancais:
    def test_clause_connue_rendue_en_francais(self):
        from app.engine.orchestrator import _message_pdfa
        from app.engine.verapdf import Echec

        message = _message_pdfa(
            Echec(
                specification="ISO 19005-3:2012",
                clause="6.6.2.1",
                test="1",
                description="The Catalog dictionary shall contain the Metadata key.",
                contexte=None,
            )
        )

        assert "métadonnées XMP" in message
        assert "6.6.2.1" in message

    def test_clause_inconnue_conserve_le_libelle_normatif(self):
        """Le texte de la norme ne doit pas être reformulé au hasard."""
        from app.engine.orchestrator import _message_pdfa
        from app.engine.verapdf import Echec

        original = "Some clause text that has no French entry."
        message = _message_pdfa(
            Echec(
                specification="ISO 19005-3:2012",
                clause="9.9.9",
                test="1",
                description=original,
                contexte=None,
            )
        )

        assert original in message
        assert "Non-conformité PDF/A" in message


@exige_verapdf
class TestAuditReel:
    """Tests qui appellent effectivement veraPDF."""

    @pytest.fixture(autouse=True)
    def active(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "VERAPDF_ENABLED", True)
        monkeypatch.setattr(config, "VERAPDF_JAR", os.environ["VERAPDF_JAR"])

    def test_factur_x_authentique_est_conforme_pdfa3(self, validate):
        """L'échantillon de référence est réellement conforme, pas seulement bien balisé."""
        report = validate(load_sample("01-valide-en16931.pdf"), "a.pdf")

        pdfa = level(report, "pdfa")
        assert pdfa["status"] == "passed"
        assert pdfa["errors"] == 0
        assert "PDF/A-3b" in pdfa["reason"]

        codes = {notice["code"] for notice in report["notices"]}
        assert "PDFA_AUDIT" in codes
        assert "PDFA_PORTEE" not in codes

    def test_pdf_ordinaire_detecte_comme_non_conforme(self, validate, pdf_ordinaire):
        report = validate(pdf_ordinaire, "ordinaire.pdf")

        pdfa = level(report, "pdfa")
        assert pdfa["status"] == "failed"
        assert pdfa["errors"] >= 1

        constats = findings(report, level_id="pdfa", severity="error")
        assert any(f["ruleId"].startswith("PDFA-") for f in constats)
        assert all(f["messageOriginal"] for f in constats)
        assert all("ISO 19005" in (f["specification"] or "") for f in constats)

    def test_le_pdf_n_est_jamais_ecrit_sur_disque(self, validate, tmp_path, monkeypatch):
        """Le document est transmis par l'entrée standard, pas par un fichier."""
        import tempfile

        # On isole le répertoire temporaire du processus et on vérifie qu'il reste
        # vide : si l'implémentation passait par un fichier, il apparaîtrait ici.
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setenv("TEMP", str(tmp_path))

        validate(load_sample("01-valide-en16931.pdf"), "a.pdf")

        assert list(tmp_path.iterdir()) == []
