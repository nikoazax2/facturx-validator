from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SAMPLES = BACKEND / "tests" / "samples"
FIXTURES = BACKEND / "tests" / "fixtures"


def load_sample(name: str) -> bytes:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(
            f"echantillon absent : {name}. Executez python scripts/build_samples.py"
        )
    return path.read_bytes()


def load_fixture(name: str) -> bytes:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"fixture absente : {name}")
    return path.read_bytes()


def level(report: dict, level_id: str) -> dict:
    for entry in report["levels"]:
        if entry["id"] == level_id:
            return entry
    raise AssertionError(f"niveau absent du rapport : {level_id}")


def findings(report: dict, *, level_id: str | None = None, severity: str | None = None):
    result = report["findings"]
    if level_id:
        result = [f for f in result if f["level"] == level_id]
    if severity:
        result = [f for f in result if f["severity"] == severity]
    return result


def rule_ids(report: dict, **kwargs) -> set[str]:
    return {f["ruleId"] for f in findings(report, **kwargs) if f["ruleId"]}


@pytest.fixture(scope="session", autouse=True)
def artifacts_available():
    """Verifie les artefacts et cree l'isolat Saxon depuis le fil principal.

    La creation depuis ce fil est necessaire : sans elle, un module de test qui
    n'utilise l'API qu'a travers TestClient ferait naitre l'isolat dans un fil du
    reservoir de travail, et l'extinction de l'interpreteur le detruirait depuis le
    fil principal, ce qui fait tomber la machine virtuelle native apres coup.
    """
    from app.engine.resources import RESOURCES, ArtifactsMissing

    try:
        RESOURCES.verify()
        RESOURCES.ensure_processor()
    except ArtifactsMissing as exc:
        pytest.skip(f"{exc}")


@pytest.fixture(autouse=True)
def compteurs_vides():
    """Chaque test part de compteurs vides.

    Sans cela, les tests qui appellent l'API se partageraient un meme plafond et
    finiraient par se gener les uns les autres a mesure que la suite grossit. La
    remise a zero couvre aussi le compteur partage : quand REDIS_URL est renseigne
    pour toute la suite, les quotas survivraient sinon d'un test au suivant.
    """
    from app import store
    from app.throttle import LIMITEUR

    LIMITEUR.reinitialiser()
    store.COMPTEUR.reinitialiser()
    yield
    LIMITEUR.reinitialiser()
    store.COMPTEUR.reinitialiser()


@pytest.fixture(scope="session")
def validate():
    from app.engine.orchestrator import validate as _validate

    return _validate
