"""Tests de l'acces par cle destine aux editeurs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import load_sample

CLE_VALIDE = "fxv_cle-de-test-integration"
CLE_ESSAI = "fxv_cle-de-test-essai"


def declaration(**surcharges) -> str:
    from app.apikeys import hacher

    entrees = [
        {
            "id": "acme",
            "label": "ACME Logiciels",
            "plan": "integration",
            "keyHash": hacher(CLE_VALIDE),
            **surcharges,
        },
        {
            "id": "essai-client",
            "label": "Client en essai",
            "plan": "essai",
            "keyHash": hacher(CLE_ESSAI),
        },
    ]
    return json.dumps(entrees)


@pytest.fixture
def registre_charge():
    from app.apikeys import REGISTRE

    REGISTRE.charger(declaration())
    REGISTRE.reinitialiser()
    yield REGISTRE
    REGISTRE.charger(None)
    REGISTRE.reinitialiser()


@pytest.fixture
def client(registre_charge):
    from app.main import app

    with TestClient(app) as test_client:
        # Le contexte de demarrage recharge les cles depuis l'environnement, qui
        # n'en declare pas : on les remet en place apres.
        registre_charge.charger(declaration())
        registre_charge.reinitialiser()
        yield test_client


class TestChargement:
    def test_cle_en_clair_acceptee_mais_hachee(self):
        from app.apikeys import Registre, hacher

        registre = Registre()
        registre.charger(json.dumps([{"id": "local", "key": "fxv_essai"}]))

        cle = registre.resoudre("fxv_essai")
        assert cle is not None
        assert cle.empreinte == hacher("fxv_essai")
        # La valeur en clair ne doit apparaitre nulle part dans l'objet conserve.
        assert "fxv_essai" not in json.dumps(cle.publique())

    def test_declaration_vide_desactive_l_acces(self):
        from app.apikeys import Registre

        registre = Registre()
        registre.charger(None)

        assert registre.actif is False
        assert registre.resoudre("fxv_peu importe") is None

    @pytest.mark.parametrize(
        "brut,motif",
        [
            ("pas du json", "JSON"),
            ('{"id": "x"}', "liste"),
            ('[{"label": "sans id"}]', "id"),
            ('[{"id": "x", "plan": "inexistant", "key": "k"}]', "plan"),
            ('[{"id": "x"}]', "keyHash"),
            ('[{"id": "x", "keyHash": "trop-court"}]', "SHA-256"),
            ('[{"id": "x", "key": "k", "expires": "hier"}]', "date"),
        ],
    )
    def test_declarations_invalides_refusees_avec_motif(self, brut, motif):
        from app.apikeys import ConfigurationInvalide, Registre

        with pytest.raises(ConfigurationInvalide) as capture:
            Registre().charger(brut)

        assert motif in str(capture.value)

    def test_empreinte_dupliquee_refusee(self):
        from app.apikeys import Registre, hacher

        empreinte = hacher("fxv_meme")
        with pytest.raises(Exception) as capture:
            Registre().charger(
                json.dumps(
                    [
                        {"id": "un", "keyHash": empreinte},
                        {"id": "deux", "keyHash": empreinte},
                    ]
                )
            )
        assert "déjà déclarée" in str(capture.value)

    def test_configuration_erronee_ne_bloque_pas_le_service(self, monkeypatch):
        """Le service public doit rester debout si les cles sont mal declarees."""
        from app import apikeys

        monkeypatch.setenv("API_KEYS", "ceci n'est pas du json")
        erreur = apikeys.charger_depuis_environnement()

        assert erreur is not None
        assert apikeys.REGISTRE.actif is False


class TestGenerationDeCle:
    def test_prefixe_et_empreinte_coherents(self):
        from app.apikeys import PREFIXE_CLE, generer_cle, hacher

        cle, empreinte = generer_cle()

        assert cle.startswith(PREFIXE_CLE)
        assert hacher(cle) == empreinte
        assert len(cle) > 30

    def test_cles_distinctes(self):
        from app.apikeys import generer_cle

        assert generer_cle()[0] != generer_cle()[0]


class TestExpiration:
    def test_cle_non_expiree(self):
        from app.apikeys import Registre

        demain = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
        registre = Registre()
        registre.charger(
            json.dumps([{"id": "x", "key": "fxv_k", "expires": demain}])
        )

        assert registre.resoudre("fxv_k").expiree() is False

    def test_cle_expiree_refusee_par_l_api(self, client, registre_charge):
        hier = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
        registre_charge.charger(declaration(expires=hier))

        reponse = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": CLE_VALIDE},
        )

        assert reponse.status_code == 403
        assert reponse.json()["error"]["code"] == "CLE_EXPIREE"


class TestAuthentification:
    def test_cle_valide_accepte_et_renseigne_les_entetes(self, client):
        reponse = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": CLE_VALIDE},
        )

        assert reponse.status_code == 200
        assert reponse.headers["X-Plan"] == "integration"
        assert reponse.headers["X-RateLimit-Limit"] == "120"
        assert reponse.headers["X-Quota-Limit"] == "50000"
        assert int(reponse.headers["X-Quota-Remaining"]) == 49999

    def test_cle_acceptee_en_bearer(self, client):
        reponse = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"Authorization": f"Bearer {CLE_VALIDE}"},
        )

        assert reponse.status_code == 200
        assert reponse.headers["X-Plan"] == "integration"

    def test_cle_inconnue_refusee(self, client):
        reponse = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": "fxv_inventee"},
        )

        assert reponse.status_code == 401
        assert reponse.json()["error"]["code"] == "CLE_INVALIDE"

    def test_absence_de_cle_reste_un_acces_anonyme(self, client):
        """L'outil public doit continuer de fonctionner sans clé."""
        reponse = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
        )

        assert reponse.status_code == 200
        assert "X-Plan" not in reponse.headers

    def test_la_cle_contourne_le_plafond_anonyme(self, client, monkeypatch):
        """Un client sous contrat ne doit pas subir la limite du trafic public."""
        from app import config, throttle

        monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr(
            throttle,
            "LIMITEUR",
            throttle.RateLimiter(per_minute=1, burst=1, max_tracked=10),
        )

        # Le plafond anonyme est epuise des la premiere requete sans cle.
        client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
        )
        refus = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
        )
        assert refus.status_code == 429

        # La cle passe malgre tout.
        avec_cle = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": CLE_VALIDE},
        )
        assert avec_cle.status_code == 200


class TestQuota:
    def test_decompte_a_chaque_validation(self, client, registre_charge):
        cle = registre_charge.resoudre(CLE_VALIDE)

        for attendu in (1, 2, 3):
            client.post(
                "/api/validate",
                files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
                headers={"X-API-Key": CLE_VALIDE},
            )
            assert registre_charge.consommation(cle) == attendu

    def test_quota_epuise_refuse_avec_402(self, client, registre_charge):
        """Le plan d'essai est volontairement petit, on le reduit encore."""
        registre_charge.charger(
            json.dumps(
                [
                    {
                        "id": "acme",
                        "plan": "integration",
                        "keyHash": registre_charge.resoudre(CLE_VALIDE).empreinte
                        if registre_charge.resoudre(CLE_VALIDE)
                        else "",
                        "perMonth": 2,
                    }
                ]
            )
        )
        registre_charge.reinitialiser()

        for _ in range(2):
            reponse = client.post(
                "/api/validate",
                files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
                headers={"X-API-Key": CLE_VALIDE},
            )
            assert reponse.status_code == 200

        epuise = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": CLE_VALIDE},
        )
        assert epuise.status_code == 402
        assert epuise.json()["error"]["code"] == "QUOTA_EPUISE"

    def test_le_refus_pour_quota_ne_consomme_pas(self, client, registre_charge):
        cle = registre_charge.resoudre(CLE_ESSAI)
        avant = registre_charge.consommation(cle)

        client.post(
            "/api/validate",
            files={"file": ("x.docx", b"abc", "text/plain")},
            headers={"X-API-Key": CLE_ESSAI},
        )

        # Une requete rejetee pour extension ne doit pas amputer le quota.
        assert registre_charge.consommation(cle) == avant


class TestEndpointEtatCle:
    def test_sans_cle(self, client):
        reponse = client.get("/api/key")

        assert reponse.status_code == 401
        assert reponse.json()["error"]["code"] == "CLE_ABSENTE"

    def test_cle_invalide(self, client):
        reponse = client.get("/api/key", headers={"X-API-Key": "fxv_faux"})

        assert reponse.status_code == 401

    def test_expose_le_plan_et_la_consommation(self, client):
        client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": CLE_VALIDE},
        )

        etat = client.get("/api/key", headers={"X-API-Key": CLE_VALIDE}).json()

        assert etat["keyId"] == "acme"
        assert etat["plan"] == "integration"
        assert etat["planLabel"] == "Intégration"
        assert etat["usage"]["used"] == 1
        assert etat["usage"]["remaining"] == 49999
        assert etat["expired"] is False

        # La nature du compteur doit etre annoncee dans les deux cas : sa limite
        # quand il est en memoire, sa fiabilite quand il est partage.
        assert isinstance(etat["usage"]["shared"], bool)
        if etat["usage"]["shared"]:
            assert "partagé" in etat["usage"]["note"]
        else:
            assert "facturation" in etat["usage"]["note"]

    def test_ne_divulgue_aucun_secret(self, client):
        etat = client.get("/api/key", headers={"X-API-Key": CLE_VALIDE}).json()
        brut = json.dumps(etat)

        assert CLE_VALIDE not in brut
        assert "keyHash" not in brut
        assert "empreinte" not in brut


class TestOffreAnnoncee:
    def test_about_decrit_les_plans(self, client):
        acces = client.get("/api/about").json()["apiAccess"]

        assert acces["enabled"] is True
        assert acces["header"] == "X-API-Key"
        assert acces["statusEndpoint"] == "/api/key"
        identifiants = {plan["id"] for plan in acces["plans"]}
        assert identifiants == {"essai", "integration", "volume"}
        for plan in acces["plans"]:
            assert plan["perMinute"] > 0
            assert plan["perMonth"] > 0
            assert plan["description"]

    def test_metriques_ventilent_par_plan(self, client, monkeypatch):
        from app import config
        from app.metrics import METRIQUES

        monkeypatch.setattr(config, "METRICS_TOKEN", "secret-de-test")
        METRIQUES.reinitialiser()

        client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": CLE_VALIDE},
        )
        client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
        )

        charge = client.get(
            "/api/metrics", headers={"X-Metrics-Token": "secret-de-test"}
        ).json()

        assert charge["validations"]["byPlan"]["integration"] == 1
        assert charge["validations"]["byPlan"]["anonyme"] == 1
