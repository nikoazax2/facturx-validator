"""Tests de la limitation de debit, du garde-fou de concurrence et des metriques."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from conftest import load_sample


class TestEmpreinteAppelant:
    def test_ne_contient_pas_l_adresse(self):
        from app.throttle import client_fingerprint

        empreinte = client_fingerprint("203.0.113.42", None)

        assert "203.0.113.42" not in empreinte
        assert len(empreinte) == 16
        assert all(c in "0123456789abcdef" for c in empreinte)

    def test_stable_pour_une_meme_adresse(self):
        from app.throttle import client_fingerprint

        assert client_fingerprint("203.0.113.42", None) == client_fingerprint(
            "203.0.113.42", None
        )

    def test_distincte_selon_l_adresse(self):
        from app.throttle import client_fingerprint

        assert client_fingerprint("203.0.113.42", None) != client_fingerprint(
            "203.0.113.43", None
        )

    def test_entete_de_proxy_ignoree_sans_confiance(self, monkeypatch):
        """Sans proxy de confiance, l'entete ne doit pas pouvoir etre forgee."""
        from app import config, throttle

        monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", False)
        directe = throttle.client_fingerprint("10.0.0.1", None)
        forgee = throttle.client_fingerprint("10.0.0.1", "1.2.3.4")

        assert directe == forgee

    def test_entete_de_proxy_lue_si_configuree(self, monkeypatch):
        from app import config, throttle

        monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
        sans = throttle.client_fingerprint("10.0.0.1", None)
        avec = throttle.client_fingerprint("10.0.0.1", "1.2.3.4, 10.0.0.1")

        assert sans != avec


class TestSeauAJetons:
    def _limiteur(self, **kwargs):
        from app.throttle import RateLimiter

        defauts = {"per_minute": 60, "burst": 3, "max_tracked": 100}
        defauts.update(kwargs)
        return RateLimiter(**defauts)

    def test_la_rafale_passe(self):
        limiteur = self._limiteur()

        for _ in range(3):
            autorise, _ = limiteur.autorise("client", maintenant=0.0)
            assert autorise

    def test_au_dela_de_la_rafale_refuse(self):
        limiteur = self._limiteur()

        for _ in range(3):
            limiteur.autorise("client", maintenant=0.0)
        autorise, attente = limiteur.autorise("client", maintenant=0.0)

        assert autorise is False
        assert attente > 0

    def test_les_jetons_se_regenerent(self):
        limiteur = self._limiteur()

        for _ in range(3):
            limiteur.autorise("client", maintenant=0.0)
        assert limiteur.autorise("client", maintenant=0.0)[0] is False
        # 60 par minute, donc un jeton par seconde.
        assert limiteur.autorise("client", maintenant=1.1)[0] is True

    def test_les_appelants_sont_independants(self):
        limiteur = self._limiteur()

        for _ in range(3):
            limiteur.autorise("premier", maintenant=0.0)
        assert limiteur.autorise("premier", maintenant=0.0)[0] is False
        assert limiteur.autorise("second", maintenant=0.0)[0] is True

    def test_memoire_bornee(self):
        """Le nombre d'appelants suivis ne doit pas croitre sans limite."""
        limiteur = self._limiteur(max_tracked=10)

        for numero in range(50):
            limiteur.autorise(f"client-{numero}", maintenant=0.0)

        assert limiteur.suivis <= 10

    def test_utilisable_depuis_plusieurs_fils(self):
        limiteur = self._limiteur(per_minute=6000, burst=200)
        acceptes: list[bool] = []
        verrou = threading.Lock()

        def frapper():
            for _ in range(20):
                autorise, _ = limiteur.autorise("commun")
                with verrou:
                    acceptes.append(autorise)

        fils = [threading.Thread(target=frapper) for _ in range(5)]
        for f in fils:
            f.start()
        for f in fils:
            f.join()

        # 100 appels, 200 jetons : tous doivent passer, sans perte de comptage.
        assert len(acceptes) == 100
        assert all(acceptes)


class TestGardeFouConcurrence:
    def test_refuse_au_dela_du_plafond(self):
        from app.throttle import ConcurrencyGuard, Saturated

        garde = ConcurrencyGuard(2)
        with garde:
            with garde:
                with pytest.raises(Saturated):
                    with garde:
                        pass

    def test_libere_a_la_sortie(self):
        from app.throttle import ConcurrencyGuard

        garde = ConcurrencyGuard(1)
        with garde:
            pass
        with garde:
            assert garde.etat["enCours"] == 1
        assert garde.etat["enCours"] == 0

    def test_libere_meme_en_cas_d_exception(self):
        from app.throttle import ConcurrencyGuard

        garde = ConcurrencyGuard(1)
        with pytest.raises(ValueError):
            with garde:
                raise ValueError("panne simulee")
        assert garde.etat["enCours"] == 0


class TestLimitationSurApi:
    @pytest.fixture
    def client(self):
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client

    def test_refus_apres_la_rafale(self, client, monkeypatch):
        from app import config, throttle

        monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr(
            throttle,
            "LIMITEUR",
            throttle.RateLimiter(per_minute=1, burst=1, max_tracked=10),
        )

        charge = {"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")}
        premiere = client.post("/api/validate", files=charge)
        assert premiere.status_code == 200

        seconde = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
        )
        assert seconde.status_code == 429
        corps = seconde.json()["error"]
        assert corps["code"] == "TROP_DE_REQUETES"
        assert corps["retryAfterSeconds"] >= 1
        assert "Retry-After" in seconde.headers
        # Le message doit orienter vers la solution, pas seulement refuser.
        assert "clé" in corps["message"]

    def test_desactivable(self, client, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)

        for _ in range(3):
            reponse = client.post(
                "/api/validate",
                files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            )
            assert reponse.status_code == 200

    def test_sante_expose_la_concurrence(self, client):
        etat = client.get("/api/health").json()

        assert "concurrency" in etat
        assert etat["concurrency"]["maximum"] >= 1

    def test_about_annonce_les_plafonds_et_la_non_conservation(self, client):
        charge = client.get("/api/about").json()

        assert charge["limits"]["perMinute"] >= 1
        assert "aucune adresse IP conservee" in charge["privacy"]["addresses"]


class TestMetriques:
    @pytest.fixture
    def client(self):
        from app.main import app

        with TestClient(app) as test_client:
            yield test_client

    def test_fermees_par_defaut(self, client, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "METRICS_TOKEN", "")
        reponse = client.get("/api/metrics")

        assert reponse.status_code == 404
        assert reponse.json()["error"]["code"] == "METRIQUES_DESACTIVEES"

    def test_jeton_exige(self, client, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "METRICS_TOKEN", "secret-de-test")

        assert client.get("/api/metrics").status_code == 401
        assert (
            client.get(
                "/api/metrics", headers={"X-Metrics-Token": "mauvais"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/metrics", headers={"X-Metrics-Token": "secret-de-test"}
            ).status_code
            == 200
        )

    def test_comptage_des_validations(self, client, monkeypatch):
        from app import config
        from app.metrics import METRIQUES

        monkeypatch.setattr(config, "METRICS_TOKEN", "secret-de-test")
        METRIQUES.reinitialiser()

        client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
        )
        client.post(
            "/api/validate",
            files={
                "file": (
                    "b.xml",
                    load_sample("06-en16931-totaux-incoherents.xml"),
                    "text/xml",
                )
            },
        )

        charge = client.get(
            "/api/metrics", headers={"X-Metrics-Token": "secret-de-test"}
        ).json()

        assert charge["validations"]["total"] == 2
        assert charge["validations"]["byVerdict"]["conforme"] == 1
        assert charge["validations"]["byVerdict"]["non_conforme"] == 1
        assert charge["validations"]["bySyntax"]["UBL"] == 1
        assert charge["validations"]["bySyntax"]["CII"] == 1
        assert charge["duration"]["meanMs"] > 0

    def test_regles_les_plus_violees(self, client, monkeypatch):
        """La statistique qui dit sur quoi les editeurs achoppent."""
        from app import config
        from app.metrics import METRIQUES

        monkeypatch.setattr(config, "METRICS_TOKEN", "secret-de-test")
        METRIQUES.reinitialiser()

        client.post(
            "/api/validate",
            files={
                "file": (
                    "b.xml",
                    load_sample("06-en16931-totaux-incoherents.xml"),
                    "text/xml",
                )
            },
        )

        charge = client.get(
            "/api/metrics", headers={"X-Metrics-Token": "secret-de-test"}
        ).json()
        codes = {entree["ruleId"] for entree in charge["topFailedRules"]}

        assert "BR-CO-15" in codes

    def test_refus_comptes(self, client, monkeypatch):
        from app import config
        from app.metrics import METRIQUES

        monkeypatch.setattr(config, "METRICS_TOKEN", "secret-de-test")
        METRIQUES.reinitialiser()

        client.post("/api/validate", files={"file": ("x.docx", b"abc", "text/plain")})
        client.post("/api/validate", files={"file": ("vide.xml", b"", "text/xml")})

        charge = client.get(
            "/api/metrics", headers={"X-Metrics-Token": "secret-de-test"}
        ).json()

        assert charge["rejections"]["EXTENSION_NON_SUPPORTEE"] == 1
        assert charge["rejections"]["FICHIER_VIDE"] == 1

    def test_aucune_donnee_identifiante(self, client, monkeypatch):
        """Ni nom de fichier, ni empreinte de contenu, ni adresse."""
        import json

        from app import config
        from app.metrics import METRIQUES

        monkeypatch.setattr(config, "METRICS_TOKEN", "secret-de-test")
        METRIQUES.reinitialiser()

        client.post(
            "/api/validate",
            files={
                "file": (
                    "facture-tres-confidentielle.xml",
                    load_sample("07-ubl-valide.xml"),
                    "text/xml",
                )
            },
        )

        brut = json.dumps(
            client.get(
                "/api/metrics", headers={"X-Metrics-Token": "secret-de-test"}
            ).json()
        )

        assert "facture-tres-confidentielle" not in brut
        assert "sha256" not in brut
        assert "LE FOURNISSEUR" not in brut
