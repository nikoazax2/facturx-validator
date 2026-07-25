"""Tests de la manifestation d'interet.

L'enjeu central de ce module n'est pas fonctionnel, il est de confidentialite : ce
point d'entree recoit un rapport de validation complet, qui contient le nom du
vendeur, celui de l'acheteur, le numero de facture et les montants. Rien de tout
cela ne doit sortir. Les tests le verifient sur des donnees reelles plutot que sur
une liste de cles.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from conftest import load_sample

RESPONSABLE = "Société de test, 1 rue Exemple, contact@exemple.test"


@pytest.fixture
def destination():
    """Destination factice, qui retient ce qui lui est transmis."""
    recues: list[dict] = []

    def _poster(url, charge):
        recues.append(charge)

    return recues, _poster


@pytest.fixture
def client(monkeypatch, destination):
    from app import config, leads

    recues, poster = destination
    monkeypatch.setattr(config, "LEADS_WEBHOOK_URL", "https://destination.test/hook")
    monkeypatch.setattr(config, "LEADS_CONTROLLER", RESPONSABLE)
    monkeypatch.setattr(leads, "_poster", poster)

    from app.main import app

    with TestClient(app) as test_client:
        monkeypatch.setattr(config, "LEADS_WEBHOOK_URL", "https://destination.test/hook")
        monkeypatch.setattr(config, "LEADS_CONTROLLER", RESPONSABLE)
        monkeypatch.setattr(leads, "_poster", poster)
        test_client.recues = recues
        yield test_client


def rapport_de(client, echantillon: str) -> dict:
    reponse = client.post(
        "/api/validate",
        files={"file": (echantillon, load_sample(echantillon), "application/octet-stream")},
    )
    assert reponse.status_code == 200
    return reponse.json()


class TestActivation:
    def test_inactive_sans_destination(self, monkeypatch):
        from app import config, leads

        monkeypatch.setattr(config, "LEADS_WEBHOOK_URL", "")
        monkeypatch.setattr(config, "LEADS_VIA_REDIS", False)
        monkeypatch.setattr(config, "LEADS_CONTROLLER", RESPONSABLE)

        assert leads.active() is False

    def test_inactive_sans_responsable(self, monkeypatch):
        """On ne recueille pas d'adresse sans dire qui la traite."""
        from app import config, leads

        monkeypatch.setattr(config, "LEADS_WEBHOOK_URL", "https://x.test/hook")
        monkeypatch.setattr(config, "LEADS_CONTROLLER", "")

        assert leads.active() is False

    def test_point_d_entree_absent_si_inactive(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "LEADS_WEBHOOK_URL", "")
        monkeypatch.setattr(config, "LEADS_VIA_REDIS", False)

        from app.main import app

        with TestClient(app) as client:
            reponse = client.post(
                "/api/lead", json={"email": "x@y.test", "consent": True}
            )

        assert reponse.status_code == 404
        assert reponse.json()["error"]["code"] == "CONTACT_INDISPONIBLE"

    def test_about_annonce_les_mentions(self, client):
        mentions = client.get("/api/about").json()["leadCapture"]

        assert mentions["enabled"] is True
        assert mentions["controller"] == RESPONSABLE
        assert mentions["retentionMonths"] >= 1
        assert "consentement" in mentions["legalBasis"]
        assert mentions["collected"] and mentions["neverCollected"]
        assert mentions["rights"]


class TestConsentement:
    def test_refus_sans_consentement(self, client):
        reponse = client.post(
            "/api/lead", json={"email": "dev@editeur.test", "consent": False}
        )

        assert reponse.status_code == 400
        assert reponse.json()["error"]["code"] == "CONSENTEMENT_REQUIS"
        assert client.recues == []

    def test_refus_si_consentement_absent(self, client):
        reponse = client.post("/api/lead", json={"email": "dev@editeur.test"})

        assert reponse.status_code == 400
        assert client.recues == []

    def test_consentement_doit_etre_vrai_et_non_verite_approchante(self, client):
        """Une chaine « true » n'est pas un consentement."""
        for valeur in ("true", 1, "oui", [1]):
            reponse = client.post(
                "/api/lead", json={"email": "dev@editeur.test", "consent": valeur}
            )
            assert reponse.status_code == 400, valeur
        assert client.recues == []

    @pytest.mark.parametrize(
        "adresse", ["", "pas-une-adresse", "a@b", "@exemple.test", "a b@exemple.test"]
    )
    def test_adresses_irrecevables(self, client, adresse):
        reponse = client.post("/api/lead", json={"email": adresse, "consent": True})

        assert reponse.status_code == 400
        assert reponse.json()["error"]["code"] == "COURRIEL_INVALIDE"
        assert client.recues == []


class TestConfidentialite:
    """Le coeur du sujet : rien de la facture ne doit sortir."""

    def test_aucune_donnee_de_facture_transmise(self, client):
        rapport = rapport_de(client, "06-en16931-totaux-incoherents.xml")

        # Le rapport contient bien ces donnees : le test n'aurait aucun sens sinon.
        brut_rapport = json.dumps(rapport, ensure_ascii=False)
        assert "LE FOURNISSEUR" in brut_rapport
        assert "F20260023" in brut_rapport

        reponse = client.post(
            "/api/lead",
            json={"email": "dev@editeur.test", "consent": True, "report": rapport},
        )
        assert reponse.status_code == 200

        transmis = json.dumps(client.recues[0], ensure_ascii=False)
        for donnee in ("LE FOURNISSEUR", "LE CLIENT", "F20260023", "999.99"):
            assert donnee not in transmis, donnee

    def test_ni_nom_de_fichier_ni_empreinte(self, client):
        rapport = rapport_de(client, "06-en16931-totaux-incoherents.xml")

        client.post(
            "/api/lead",
            json={"email": "dev@editeur.test", "consent": True, "report": rapport},
        )
        transmis = json.dumps(client.recues[0])

        assert "06-en16931" not in transmis
        assert rapport["input"]["sha256"] not in transmis
        assert "sha256" not in transmis

    def test_seuls_les_faits_techniques_sont_transmis(self, client):
        rapport = rapport_de(client, "06-en16931-totaux-incoherents.xml")

        client.post(
            "/api/lead",
            json={"email": "dev@editeur.test", "consent": True, "report": rapport},
        )
        validation = client.recues[0]["validation"]

        assert set(validation) == {
            "verdict",
            "profil",
            "syntaxe",
            "codesEnEchec",
            "logicielDeclare",
        }
        assert validation["verdict"] == "non_conforme"
        assert validation["profil"] == "EN16931"
        assert "BR-CO-15" in validation["codesEnEchec"]

    def test_liste_blanche_et_non_exclusion(self, client):
        """Une cle inconnue ajoutee au rapport ne doit pas se retrouver transmise."""
        rapport = rapport_de(client, "07-ubl-valide.xml")
        rapport["document"]["secretDuClient"] = "NE-DOIT-PAS-SORTIR"
        rapport["champInvente"] = "NE-DOIT-PAS-SORTIR-NON-PLUS"

        client.post(
            "/api/lead",
            json={"email": "dev@editeur.test", "consent": True, "report": rapport},
        )

        assert "NE-DOIT-PAS-SORTIR" not in json.dumps(client.recues[0])

    def test_codes_en_echec_bornes(self, client):
        """Un fichier tres degrade ne doit pas produire une charge demesuree."""
        rapport = rapport_de(client, "07-ubl-valide.xml")
        rapport["findings"] = [
            {"severity": "error", "ruleId": f"BR-{numero}"} for numero in range(500)
        ]

        client.post(
            "/api/lead",
            json={"email": "dev@editeur.test", "consent": True, "report": rapport},
        )

        assert len(client.recues[0]["validation"]["codesEnEchec"]) <= 25


class TestTransmission:
    def test_champs_declares_reprisez(self, client):
        client.post(
            "/api/lead",
            json={
                "email": "dev@editeur.test",
                "consent": True,
                "software": "MonERP 12.4",
                "sector": "BTP",
                "monthlyVolume": "5000",
            },
        )
        recue = client.recues[0]

        assert recue["courriel"] == "dev@editeur.test"
        assert recue["logiciel"] == "MonERP 12.4"
        assert recue["secteur"] == "BTP"
        assert recue["volumeMensuel"] == "5000"
        assert recue["consentementContact"] is True
        assert recue["source"] == "validateur-facturx"

    def test_champs_bornes_en_longueur(self, client):
        client.post(
            "/api/lead",
            json={
                "email": "dev@editeur.test",
                "consent": True,
                "software": "X" * 5000,
                "sector": "Y" * 5000,
            },
        )
        recue = client.recues[0]

        assert len(recue["logiciel"]) <= 200
        assert len(recue["secteur"]) <= 200

    def test_caracteres_de_controle_retires(self, client):
        client.post(
            "/api/lead",
            json={
                "email": "dev@editeur.test",
                "consent": True,
                "software": "Mon\x00ERP\r\n\tavec  espaces",
            },
        )

        assert client.recues[0]["logiciel"] == "MonERP avec espaces"

    def test_logiciel_declare_par_le_fichier_transmis(self, client):
        """La metadonnee qui identifie l'editeur, sans rien demander au visiteur."""
        rapport = rapport_de(client, "01-valide-en16931.pdf")
        assert rapport["document"]["producer"]["label"]

        client.post(
            "/api/lead",
            json={"email": "dev@editeur.test", "consent": True, "report": rapport},
        )

        assert client.recues[0]["validation"]["logicielDeclare"] == (
            rapport["document"]["producer"]["label"]
        )

    def test_panne_de_la_destination_signalee_sans_detail(self, client, monkeypatch):
        from app import leads

        def _echoue(url, charge):
            raise leads.Refus("DESTINATION_EN_ECHEC", "La demande n'a pas pu être transmise.")

        monkeypatch.setattr(leads, "_poster", _echoue)

        reponse = client.post(
            "/api/lead", json={"email": "dev@editeur.test", "consent": True}
        )

        assert reponse.status_code == 502
        message = reponse.json()["error"]["message"]
        assert "destination.test" not in message
        assert "hook" not in message

    def test_corps_non_json_refuse(self, client):
        reponse = client.post(
            "/api/lead",
            content=b"ceci n'est pas du json",
            headers={"Content-Type": "application/json"},
        )

        assert reponse.status_code == 400
        assert reponse.json()["error"]["code"] == "CORPS_INVALIDE"

    def test_corps_qui_n_est_pas_un_objet_refuse(self, client):
        reponse = client.post("/api/lead", json=["une", "liste"])

        assert reponse.status_code == 400


class TestLogicielEmetteur:
    """Detection passive du logiciel, sans rien demander au visiteur."""

    def test_detecte_dans_un_pdf(self, validate):
        rapport = validate(load_sample("01-valide-en16931.pdf"), "a.pdf")
        emetteur = rapport["document"]["producer"]

        assert emetteur is not None
        assert emetteur["label"]
        assert emetteur["producer"] == "PyPDF4"
        assert "factur-x" in emetteur["label"].lower()

    def test_absent_pour_un_xml(self, validate):
        rapport = validate(load_sample("07-ubl-valide.xml"), "a.xml")

        assert rapport["document"].get("producer") is None

    def test_libelle_prefere_l_application_a_la_bibliotheque(self, validate):
        """PyPDF4 nomme la bibliotheque, pas le logiciel de facturation."""
        rapport = validate(load_sample("01-valide-en16931.pdf"), "a.pdf")
        emetteur = rapport["document"]["producer"]

        assert emetteur["label"] != emetteur["producer"]
        assert emetteur["label"] == emetteur["creatorTool"]

    def test_metrique_croise_logiciel_et_conformite(self, monkeypatch):
        from app import config
        from app.metrics import METRIQUES

        monkeypatch.setattr(config, "METRICS_TOKEN", "jeton-de-test")
        METRIQUES.reinitialiser()

        from app.main import app

        with TestClient(app) as client:
            for echantillon in ("01-valide-en16931.pdf", "02-pdf-sans-xml.pdf"):
                client.post(
                    "/api/validate",
                    files={
                        "file": (
                            echantillon,
                            load_sample(echantillon),
                            "application/pdf",
                        )
                    },
                )
            charge = client.get(
                "/api/metrics", headers={"X-Metrics-Token": "jeton-de-test"}
            ).json()

        logiciels = {entree["label"]: entree for entree in charge["issuingSoftware"]}
        assert logiciels
        entree = next(iter(logiciels.values()))
        assert entree["total"] == 2
        # Le PDF sans XML est non evaluable : le ratio doit le refleter.
        assert entree["nonConformant"] == 1
        assert entree["nonConformantRatio"] == 0.5

    def test_cardinalite_bornee(self):
        """La valeur vient du fichier : le compteur ne doit pas croitre sans limite."""
        from app.metrics import Metrics, _EMETTEURS_MAX

        metriques = Metrics()
        for numero in range(_EMETTEURS_MAX + 250):
            metriques.enregistrer_validation(
                {
                    "verdict": {"code": "conforme"},
                    "document": {"producer": {"label": f"logiciel-{numero}"}},
                    "input": {},
                    "engine": {},
                }
            )

        instantane = metriques.instantane(top_regles=1000)
        assert len(instantane["issuingSoftware"]) <= _EMETTEURS_MAX + 1
        assert any(e["label"] == "autres" for e in instantane["issuingSoftware"])
