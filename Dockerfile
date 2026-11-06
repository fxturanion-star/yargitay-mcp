FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY passage_selection.py semantik.py surum.py release-revision erisim.py upstream.py metin.py main.py hukuk_server.py kanun.py server.py bedesten.py emsal.py kaynaklar.py .

# Bağımsız Docker build için: --build-arg RELEASE_REVISION=$(git rev-parse HEAD)
ARG RELEASE_REVISION=""
RUN python -c "import os,re; from pathlib import Path; value=os.environ.get('RELEASE_REVISION',''); assert not value or re.fullmatch('[0-9a-f]{40}',value), 'RELEASE_REVISION must be a full lowercase git SHA'; Path('build-revision').write_text(value)"
LABEL org.opencontainers.image.revision=$RELEASE_REVISION

ENV PORT=8000
EXPOSE 8000
CMD ["python", "server.py"]
