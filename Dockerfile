FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py hukuk_server.py kanun.py server.py bedesten.py emsal.py kaynaklar.py .

ENV PORT=8000
EXPOSE 8000
CMD ["python", "server.py"]
