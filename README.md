# Probenplaner

Theater-Probenplaner mit Google OAuth und direkter Google Sheets Anbindung.

## Lokale Entwicklung

### 1. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 2. Umgebungsvariablen setzen
```bash
export GOOGLE_CLIENT_ID="deine-client-id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="dein-client-secret"
export SECRET_KEY="beliebiger-zufallsstring"
export BASE_URL="http://localhost:8000"
```

### 3. Starten
```bash
uvicorn main:app --reload
```

Dann im Browser: http://localhost:8000

---

## Deployment auf Render.com

### 1. GitHub Repository erstellen
Alle Dateien in ein neues GitHub Repository pushen.

### 2. Render.com
1. https://render.com → «New Web Service»
2. GitHub Repository verbinden
3. Die Einstellungen werden automatisch aus `render.yaml` übernommen
4. Unter «Environment» die fehlenden Variablen eintragen:
   - `GOOGLE_CLIENT_ID` → aus Google Cloud Console
   - `GOOGLE_CLIENT_SECRET` → aus Google Cloud Console
   - `BASE_URL` → die Render-URL, z.B. `https://probenplaner.onrender.com`

### 3. Google Cloud: Callback-URL nachtragen
In der Google Cloud Console unter «Anmeldedaten» → OAuth-Client bearbeiten:
- Autorisierte Weiterleitungs-URIs: `https://probenplaner.onrender.com/auth/callback` hinzufügen

---

## Projektstruktur

```
probenplaner/
├── main.py              # FastAPI Backend (OAuth, Sheets API, Analyse)
├── requirements.txt     # Python-Abhängigkeiten
├── render.yaml          # Render.com Deployment-Konfiguration
├── templates/
│   └── index.html       # Frontend (Single-Page App)
└── static/              # Statische Dateien (optional)
```

## Datenbank

SQLite (lokal) bzw. Postgres (Render). Die Szenen werden persistent gespeichert.
Für Render: SQLite-Dateien werden bei jedem Deploy zurückgesetzt → für Produktion
`DATABASE_URL` auf eine Postgres-Instanz setzen und `DB_PATH` ersetzen.
