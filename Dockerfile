# Image de production pour Google Cloud Run.
#
# Les artefacts de validation sont recuperes pendant la construction, pas au
# demarrage : un conteneur qui demarre ne doit pas dependre de GitHub ni de PyPI,
# et la version des regles doit etre figee dans l'image plutot que varier d'une
# instance a l'autre.

# ---------------------------------------------------------------------------
# 1. Interface
# ---------------------------------------------------------------------------
FROM node:22-alpine AS interface

WORKDIR /interface
COPY frontend/package.json frontend/package-lock.json* ./
# Sans --omit=dev : Vite et le greffon Vue sont des dependances de developpement,
# et ce sont precisement elles qui construisent l'interface.
RUN if [ -f package-lock.json ]; then \
      npm ci --no-audit --no-fund; \
    else \
      npm install --no-audit --no-fund; \
    fi
COPY frontend/ ./
# Le vite.config.js ecrit dans ../backend/static, chemin qui n'existe pas dans
# cette etape : la sortie est donc redirigee explicitement.
RUN mkdir -p /backend/static && npm run build -- --outDir /backend/static --emptyOutDir

# ---------------------------------------------------------------------------
# 2. Artefacts officiels
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS artefacts

WORKDIR /build
COPY scripts/fetch_artifacts.py ./scripts/
RUN python scripts/fetch_artifacts.py --dest /artefacts

# ---------------------------------------------------------------------------
# 3. veraPDF, construit seulement pour la variante service-verapdf
#
# L'installateur est un jar IzPack : il faut une machine virtuelle Java pour le
# derouler, d'ou cette etape distincte. Seul le paquet CLI est retenu, l'interface
# graphique et la documentation n'ont pas leur place dans une image de service.
# ---------------------------------------------------------------------------
FROM eclipse-temurin:21-jre AS verapdf-install

WORKDIR /tmp/verapdf
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl unzip; \
    rm -rf /var/lib/apt/lists/*; \
    curl -sSL -o installer.zip https://software.verapdf.org/releases/verapdf-installer.zip; \
    unzip -q installer.zip; \
    printf '%s\n' \
      '<?xml version="1.0" encoding="UTF-8" standalone="no"?>' \
      '<AutomatedInstallation langpack="eng">' \
      '  <com.izforge.izpack.panels.htmlhello.HTMLHelloPanel id="welcome"/>' \
      '  <com.izforge.izpack.panels.target.TargetPanel id="install_dir">' \
      '    <installpath>/opt/verapdf</installpath>' \
      '  </com.izforge.izpack.panels.target.TargetPanel>' \
      '  <com.izforge.izpack.panels.packs.PacksPanel id="sdk_pack_select">' \
      '    <pack index="0" name="veraPDF GUI" selected="false"/>' \
      '    <pack index="1" name="veraPDF CLI" selected="true"/>' \
      '  </com.izforge.izpack.panels.packs.PacksPanel>' \
      '  <com.izforge.izpack.panels.install.InstallPanel id="install"/>' \
      '  <com.izforge.izpack.panels.finish.SimpleFinishPanel id="finish"/>' \
      '</AutomatedInstallation>' > auto-install.xml; \
    java -jar verapdf-greenfield-*/verapdf-izpack-installer-*.jar auto-install.xml; \
    # Le nom du jar porte la version : on fige un nom stable pour la configuration.
    ln -s "$(basename /opt/verapdf/bin/cli-*.jar)" /opt/verapdf/bin/cli.jar; \
    rm -rf /opt/verapdf/Uninstaller /opt/verapdf/documents; \
    test -f /opt/verapdf/bin/cli.jar

# ---------------------------------------------------------------------------
# 4. Service, socle commun
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS service-base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    RESOURCES_DIR=/app/resources \
    STATIC_DIR=/app/static \
    WARMUP_ON_STARTUP=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=artefacts /artefacts ./resources
COPY --from=interface /backend/static ./static

# Le service ne conserve rien : il n'a besoin d'ecrire nulle part.
RUN useradd --create-home --uid 10001 validateur \
    && chown -R validateur:validateur /app
USER validateur

EXPOSE 8080

# Un seul worker par instance. Le processeur Saxon n'est pas sur en usage
# concurrent et les appels sont serialises par un verrou : la montee en charge se
# fait par le nombre d'instances Cloud Run, pas par le nombre de workers. Chaque
# validation coutant quelques millisecondes une fois les artefacts compiles, une
# concurrence Cloud Run de 8 a 20 par instance reste confortable.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --no-server-header"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,os,sys,json; \
r=json.load(urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8080)}/api/health')); \
sys.exit(0 if r['status']=='ok' else 1)"

# ---------------------------------------------------------------------------
# 5. Variante avec audit PDF/A
#
#     docker build --target service-verapdf -t facturx-validator:verapdf .
#
# A construire en connaissance de cause : l'image gagne environ 300 Mo, et chaque
# validation de PDF coute environ une seconde et demie de plus, presque
# entierement du demarrage de machine virtuelle Java. Pour un audit permanent, un
# service veraPDF maintenu chaud a cote est preferable a un processus par requete.
# ---------------------------------------------------------------------------
FROM service-base AS service-verapdf

USER root
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends default-jre-headless; \
    rm -rf /var/lib/apt/lists/*
COPY --from=verapdf-install /opt/verapdf /opt/verapdf
ENV VERAPDF_ENABLED=1 \
    VERAPDF_JAR=/opt/verapdf/bin/cli.jar
USER validateur

# ---------------------------------------------------------------------------
# 6. Image par defaut, sans audit PDF/A
#
# Derniere etape du fichier, donc celle que `docker build` produit sans --target.
# ---------------------------------------------------------------------------
FROM service-base AS service
