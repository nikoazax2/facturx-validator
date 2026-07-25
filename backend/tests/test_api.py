"""Tests de l'API HTTP : contrat, garde-fous et absence de persistance."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from conftest import load_sample


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


class TestSante:
    def test_health_signale_les_artefacts(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["artifactsLoaded"] is True
        assert payload["error"] is None

    def test_about_expose_les_sources(self, client):
        response = client.get("/api/about")
        assert response.status_code == 200
        payload = response.json()

        assert payload["artifacts"]["en16931SchematronVersion"]
        assert payload["maxUploadBytes"] == 10 * 1024 * 1024
        assert len(payload["profiles"]) == 5
        assert {p["code"] for p in payload["profiles"]} == {
            "MINIMUM",
            "BASIC_WL",
            "BASIC",
            "EN16931",
            "EXTENDED",
        }

    def test_about_annonce_la_non_conservation(self, client):
        payload = client.get("/api/about").json()
        assert payload["privacy"]["storage"] == "aucun"
        assert payload["privacy"]["accounts"] == "aucun compte requis"

    def test_about_porte_le_calendrier(self, client):
        payload = client.get("/api/about").json()
        milestones = payload["regulatory"]["milestones"]
        assert {m["date"] for m in milestones} >= {"2026-09-01", "2027-09-01"}


class TestValidation:
    def test_pdf_valide(self, client):
        response = client.post(
            "/api/validate",
            files={
                "file": (
                    "01-valide-en16931.pdf",
                    load_sample("01-valide-en16931.pdf"),
                    "application/pdf",
                )
            },
        )
        assert response.status_code == 200
        report = response.json()
        assert report["verdict"]["code"] == "conforme"
        assert report["input"]["filename"] == "01-valide-en16931.pdf"

    def test_xml_seul(self, client):
        response = client.post(
            "/api/validate",
            files={
                "file": ("07-ubl-valide.xml", load_sample("07-ubl-valide.xml"), "text/xml")
            },
        )
        assert response.status_code == 200
        report = response.json()
        assert report["document"]["syntax"] == "UBL"

    def test_reponse_est_du_json_utilisable(self, client):
        response = client.post(
            "/api/validate",
            files={
                "file": (
                    "06.xml",
                    load_sample("06-en16931-totaux-incoherents.xml"),
                    "text/xml",
                )
            },
        )
        assert response.headers["content-type"].startswith("application/json")
        report = json.loads(response.content)
        assert report["summary"]["errors"] >= 1

    def test_fichier_non_conforme_reste_un_200(self, client):
        """Un fichier invalide est un resultat d'analyse, pas une erreur HTTP."""
        response = client.post(
            "/api/validate",
            files={"file": ("02.pdf", load_sample("02-pdf-sans-xml.pdf"), "application/pdf")},
        )
        assert response.status_code == 200
        assert response.json()["verdict"]["code"] == "non_evaluable"


class TestGardeFous:
    def test_extension_refusee(self, client):
        response = client.post(
            "/api/validate",
            files={"file": ("facture.docx", b"contenu", "application/octet-stream")},
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "EXTENSION_NON_SUPPORTEE"

    def test_fichier_vide(self, client):
        response = client.post(
            "/api/validate", files={"file": ("vide.xml", b"", "text/xml")}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "FICHIER_VIDE"

    def test_taille_maximale_appliquee(self, client):
        oversized = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 + 1024)
        response = client.post(
            "/api/validate",
            files={"file": ("gros.pdf", oversized, "application/pdf")},
        )
        assert response.status_code == 413
        payload = response.json()["error"]
        assert payload["code"] == "FICHIER_TROP_VOLUMINEUX"
        assert payload["maxUploadBytes"] == 10 * 1024 * 1024
        assert "10 Mo" in payload["message"]

    def test_fichier_absent(self, client):
        response = client.post("/api/validate")
        assert response.status_code == 422

    def test_nom_de_fichier_assaini(self, client):
        """Le nom vient de l'appelant : il est renvoye, donc il est nettoye."""
        malveillant = "../../etc/passwd<script>.xml"
        reponse = client.post(
            "/api/validate",
            files={"file": (malveillant, load_sample("07-ubl-valide.xml"), "text/xml")},
        )

        assert reponse.status_code == 200
        renvoye = reponse.json()["input"]["filename"]
        assert "/" not in renvoye
        assert ".." not in renvoye
        assert "<" not in renvoye
        assert renvoye.endswith(".xml")

    def test_nom_de_fichier_borne(self, client):
        demesure = "a" * 5000 + ".xml"
        reponse = client.post(
            "/api/validate",
            files={"file": (demesure, load_sample("07-ubl-valide.xml"), "text/xml")},
        )

        assert reponse.status_code == 200
        assert len(reponse.json()["input"]["filename"]) <= 180

    def test_pas_de_chemin_serveur_dans_les_erreurs_publiques(self, client, monkeypatch):
        """Un chemin d'installation n'a rien a faire dans une reponse publique."""
        from app import main

        monkeypatch.setitem(main._READY, "error", "artefacts de validation indisponibles")
        reponse = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
        )

        assert reponse.status_code == 503
        message = reponse.json()["error"]["message"]
        for fuite in ("/app/", "C:\\", "resources", ".jar", ".xslt"):
            assert fuite not in message

    def test_etat_de_sante_ne_divulgue_pas_de_chemin(self, client, monkeypatch):
        import json

        from app import main

        monkeypatch.setitem(main._READY, "error", "artefacts de validation indisponibles")
        brut = json.dumps(client.get("/api/health").json())

        for fuite in ("/app/", "resources/", ".xslt", ".jar"):
            assert fuite not in brut

    def test_erreurs_en_francais_et_structurees(self, client):
        response = client.post(
            "/api/validate", files={"file": ("x.txt", b"abc", "text/plain")}
        )
        error = response.json()["error"]
        assert set(error) >= {"code", "message"}
        assert "prise en charge" in error["message"]
