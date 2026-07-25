"""Tests des compteurs, en memoire et partages.

Les tests adosses a Redis ne s'executent que si REDIS_URL est renseigne. Sans
cela, ils se sautent : le service doit rester testable sans dependance externe.

    docker run -d --name fxv-redis -p 6379:6379 redis:7-alpine
    REDIS_URL=redis://127.0.0.1:6379/0 pytest tests/test_store.py
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from conftest import load_sample

REDIS_URL = os.getenv("REDIS_URL", "")
exige_redis = pytest.mark.skipif(
    not REDIS_URL, reason="REDIS_URL absent : compteur partagé non testé"
)


class TestCompteurMemoire:
    def _compteur(self, **kwargs):
        from app.store import CompteurMemoire

        return CompteurMemoire(**kwargs)

    def test_incremente(self):
        compteur = self._compteur()

        assert compteur.incrementer("a", 60) == 1
        assert compteur.incrementer("a", 60) == 2
        assert compteur.lire("a") == 2

    def test_cles_independantes(self):
        compteur = self._compteur()

        compteur.incrementer("a", 60)
        assert compteur.lire("b") == 0

    def test_valeur_absente_vaut_zero(self):
        assert self._compteur().lire("jamais-vue") == 0

    def test_peremption(self):
        """Une valeur perimee repart de zero."""
        import time

        compteur = self._compteur()
        compteur.incrementer("a", 60)

        # On avance le temps plutôt que d'attendre.
        with pytest.MonkeyPatch.context() as patch:
            depart = time.monotonic()
            patch.setattr(time, "monotonic", lambda: depart + 61)
            assert compteur.lire("a") == 0
            assert compteur.incrementer("a", 60) == 1

    def test_memoire_bornee(self):
        compteur = self._compteur(max_cles=10)

        for numero in range(100):
            compteur.incrementer(f"cle-{numero}", 60)

        assert compteur.sante()["keys"] <= 10

    def test_annonce_ne_pas_etre_partage(self):
        compteur = self._compteur()

        assert compteur.partage is False
        assert compteur.sante()["shared"] is False


class TestMasquageDesSecrets:
    @pytest.mark.parametrize(
        "url,attendu_absent",
        [
            ("redis://user:motdepasse@hote:6379/0", "motdepasse"),
            ("rediss://default:jeton-secret@upstash.example:6379", "jeton-secret"),
        ],
    )
    def test_identifiants_retires(self, url, attendu_absent):
        from app.store import _masquer

        masquee = _masquer(url)

        assert attendu_absent not in masquee
        assert "***" in masquee

    def test_url_sans_identifiants_inchangee(self):
        from app.store import _masquer

        assert _masquer("redis://127.0.0.1:6379/0") == "redis://127.0.0.1:6379/0"


class TestConstruction:
    def test_sans_url_compteur_memoire(self):
        from app.store import CompteurMemoire, construire

        compteur, erreur = construire(None)

        assert isinstance(compteur, CompteurMemoire)
        assert erreur is None

    def test_url_injoignable_retombe_sur_la_memoire(self):
        """Une panne de compteur ne doit pas empêcher le service de démarrer."""
        from app.store import CompteurMemoire, construire

        compteur, erreur = construire("redis://127.0.0.1:1/0")

        assert isinstance(compteur, CompteurMemoire)
        assert erreur is not None
        assert "injoignable" in erreur or "inutilisable" in erreur

    def test_url_absurde_signalee_sans_exception(self):
        from app.store import CompteurMemoire, construire

        compteur, erreur = construire("ceci-n-est-pas-une-url")

        assert isinstance(compteur, CompteurMemoire)
        assert erreur is not None


class TestPanneDuCompteurPartage:
    """Le service laisse passer plutot que de bloquer un client."""

    def test_quota_non_decompte_si_compteur_indisponible(self, monkeypatch):
        from app import apikeys, store

        class CompteurEnPanne:
            partage = True

            def incrementer(self, cle, ttl):
                return None

            def lire(self, cle):
                return None

            def sante(self):
                return {"type": "panne", "shared": True}

            def reinitialiser(self):
                pass

        monkeypatch.setattr(store, "COMPTEUR", CompteurEnPanne())
        registre = apikeys.Registre()
        registre.charger(json.dumps([{"id": "x", "key": "fxv_k", "perMonth": 1}]))
        cle = registre.resoudre("fxv_k")

        # Deux appels, alors que le quota est de un : la panne ne doit pas bloquer.
        for _ in range(2):
            autorise, _ = registre.consommer(cle)
            assert autorise is True

    def test_debit_partage_ne_refuse_pas_si_indisponible(self, monkeypatch):
        from app import store, throttle

        class CompteurEnPanne:
            partage = True

            def incrementer(self, cle, ttl):
                return None

            def lire(self, cle):
                return None

            def sante(self):
                return {}

            def reinitialiser(self):
                pass

        monkeypatch.setattr(store, "COMPTEUR", CompteurEnPanne())

        assert throttle.debit_partage_depasse("portee", 1) is False

    def test_compteur_local_ignore_le_debit_partage(self, monkeypatch):
        """Sans compteur partagé, la vérification globale est simplement sautée."""
        from app import store, throttle

        monkeypatch.setattr(store, "COMPTEUR", store.CompteurMemoire())

        for _ in range(50):
            assert throttle.debit_partage_depasse("portee", 1) is False


@exige_redis
class TestCompteurPartage:
    @pytest.fixture
    def compteur(self):
        from app.store import CompteurRedis

        instance = CompteurRedis(REDIS_URL)
        assert instance.verifier() is None
        instance.reinitialiser()
        yield instance
        instance.reinitialiser()

    def test_incremente_et_lit(self, compteur):
        assert compteur.incrementer("fxv:test:a", 60) == 1
        assert compteur.incrementer("fxv:test:a", 60) == 2
        assert compteur.lire("fxv:test:a") == 2

    def test_annonce_etre_partage(self, compteur):
        assert compteur.partage is True
        assert compteur.sante()["shared"] is True
        assert compteur.sante()["available"] is True

    def test_peremption_posee(self, compteur):
        """La clé doit porter une péremption, sinon elle vivrait indéfiniment."""
        compteur.incrementer("fxv:test:ttl", 60)
        restant = compteur._client.ttl("fxv:test:ttl")

        assert 0 < restant <= 60

    def test_peremption_non_repoussee_a_chaque_appel(self, compteur):
        """Un quota mensuel ne doit pas voir son échéance repoussée sans fin."""
        compteur.incrementer("fxv:test:fixe", 100)
        premier = compteur._client.ttl("fxv:test:fixe")
        compteur.incrementer("fxv:test:fixe", 100)
        second = compteur._client.ttl("fxv:test:fixe")

        assert second <= premier

    def test_deux_instances_partagent_le_compte(self, compteur):
        """Le point de tout l'exercice : deux processus, un seul compteur."""
        from app.store import CompteurRedis

        autre = CompteurRedis(REDIS_URL)

        compteur.incrementer("fxv:test:commun", 60)
        assert autre.incrementer("fxv:test:commun", 60) == 2
        assert compteur.lire("fxv:test:commun") == 2

    def test_url_masquee_dans_l_etat(self, compteur):
        etat = json.dumps(compteur.sante())

        assert "fxv:" not in etat
        if "@" in REDIS_URL:
            assert "***" in etat


@exige_redis
class TestQuotaPartageSurApi:
    CLE = "fxv_cle-quota-partage"

    @pytest.fixture
    def client(self, monkeypatch):
        from app import apikeys, config, store
        from app.apikeys import hacher

        monkeypatch.setattr(config, "REDIS_URL", REDIS_URL)
        erreur = store.initialiser()
        assert erreur is None, erreur
        store.COMPTEUR.reinitialiser()

        declaration = json.dumps(
            [{"id": "partage", "plan": "essai", "keyHash": hacher(self.CLE), "perMonth": 2}]
        )
        from app.main import app

        with TestClient(app) as test_client:
            monkeypatch.setattr(config, "REDIS_URL", REDIS_URL)
            store.initialiser()
            store.COMPTEUR.reinitialiser()
            apikeys.REGISTRE.charger(declaration)
            yield test_client
        apikeys.REGISTRE.charger(None)
        store.COMPTEUR.reinitialiser()

    def test_quota_survit_a_un_redemarrage(self, client, monkeypatch):
        """Un compteur partagé ne repart pas de zéro : c'est ce qui permet de facturer."""
        from app import config, store

        charge = {"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")}
        assert client.post("/api/validate", files=charge).status_code == 200

        # On simule un redemarrage : nouveau compteur, memes donnees.
        monkeypatch.setattr(config, "REDIS_URL", REDIS_URL)
        store.initialiser()

        deuxieme = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": self.CLE},
        )
        assert deuxieme.status_code == 200
        etat = client.get("/api/key", headers={"X-API-Key": self.CLE}).json()
        assert etat["usage"]["shared"] is True
        assert "partagé" in etat["usage"]["note"]

    def test_quota_epuise_au_dela_du_plafond(self, client):
        for _ in range(2):
            reponse = client.post(
                "/api/validate",
                files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
                headers={"X-API-Key": self.CLE},
            )
            assert reponse.status_code == 200

        epuise = client.post(
            "/api/validate",
            files={"file": ("a.xml", load_sample("07-ubl-valide.xml"), "text/xml")},
            headers={"X-API-Key": self.CLE},
        )
        assert epuise.status_code == 402

    def test_sante_annonce_les_compteurs_partages(self, client):
        etat = client.get("/api/health").json()

        assert etat["counters"]["shared"] is True
        assert etat["counters"]["type"] == "redis"
        assert etat["countersError"] is None
