import os
import json
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── Config ────────────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
SECRET_KEY           = os.environ.get("SECRET_KEY", "change-me-in-production")
BASE_URL             = os.environ.get("BASE_URL", "http://localhost:8000")
SHEET_ID             = os.environ.get("SHEET_ID", "1ytHSYObmi1GG3Kok1F-TFLUH0EloWljpiclLIhuBkxg")

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

DB_PATH = os.environ.get("DB_PATH", "probenplaner.db")

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scenes (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            actors  TEXT NOT NULL  -- JSON array of {name, vorname}
        );
    """)
    conn.commit()
    conn.close()

# ── App ───────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Auth helpers ──────────────────────────────────────────────────────────────
def require_login(request: Request):
    if "access_token" not in request.session:
        raise HTTPException(status_code=401, detail="Nicht angemeldet")
    return request.session["access_token"]

def google_credentials(access_token: str) -> Credentials:
    return Credentials(token=access_token)

# ── Routes: Auth ──────────────────────────────────────────────────────────────
@app.get("/auth/login")
def auth_login(request: Request):
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  f"{BASE_URL}/auth/callback",
        "response_type": "code",
        "scope":         " ".join(SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + "&".join(
        f"{k}={v}" for k, v in params.items()
    )
    return RedirectResponse(url)

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  f"{BASE_URL}/auth/callback",
                "grant_type":    "authorization_code",
            },
        )
    data = resp.json()
    if "access_token" not in data:
        raise HTTPException(400, f"OAuth Fehler: {data}")
    request.session["access_token"] = data["access_token"]
    return RedirectResponse("/")

@app.get("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

@app.get("/auth/me")
def auth_me(request: Request):
    token = request.session.get("access_token")
    return {"logged_in": token is not None}

# ── Routes: Sheets ────────────────────────────────────────────────────────────
@app.get("/api/sheets/tabs")
def get_tabs(access_token: str = Depends(require_login)):
    """Return list of sheet tab names."""
    creds = google_credentials(access_token)
    service = build("sheets", "v4", credentials=creds)
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    tabs = [s["properties"]["title"] for s in meta["sheets"]]
    return {"tabs": tabs}

@app.get("/api/sheets/data/{tab}")
def get_sheet_data(tab: str, access_token: str = Depends(require_login)):
    """Return raw sheet data for a given tab."""
    creds = google_credentials(access_token)
    service = build("sheets", "v4", credentials=creds)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SHEET_ID, range=f"'{tab}'")
        .execute()
    )
    rows = result.get("values", [])
    return {"rows": rows}

# ── Routes: Szenen ────────────────────────────────────────────────────────────
@app.get("/api/scenes")
def list_scenes(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT id, name, actors FROM scenes ORDER BY id").fetchall()
    return {"scenes": [{"id": r["id"], "name": r["name"], "actors": json.loads(r["actors"])} for r in rows]}

@app.post("/api/scenes")
async def create_scene(request: Request, db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    name   = body.get("name", "").strip()
    actors = body.get("actors", [])
    if not name:
        raise HTTPException(400, "Name fehlt")
    cur = db.execute(
        "INSERT INTO scenes (name, actors) VALUES (?, ?)",
        (name, json.dumps(actors))
    )
    db.commit()
    return {"id": cur.lastrowid, "name": name, "actors": actors}

@app.put("/api/scenes/{scene_id}")
async def update_scene(scene_id: int, request: Request, db: sqlite3.Connection = Depends(get_db)):
    body = await request.json()
    name   = body.get("name", "").strip()
    actors = body.get("actors", [])
    db.execute(
        "UPDATE scenes SET name=?, actors=? WHERE id=?",
        (name, json.dumps(actors), scene_id)
    )
    db.commit()
    return {"id": scene_id, "name": name, "actors": actors}

@app.delete("/api/scenes/{scene_id}")
def delete_scene(scene_id: int, db: sqlite3.Connection = Depends(get_db)):
    db.execute("DELETE FROM scenes WHERE id=?", (scene_id,))
    db.commit()
    return {"deleted": scene_id}

# ── Routes: Analyse ───────────────────────────────────────────────────────────
@app.post("/api/analyse")
async def analyse(request: Request, db: sqlite3.Connection = Depends(get_db),
                  access_token: str = Depends(require_login)):
    body    = await request.json()
    tab     = body.get("tab")
    if not tab:
        raise HTTPException(400, "Tab fehlt")

    # Load sheet
    creds   = google_credentials(access_token)
    service = build("sheets", "v4", credentials=creds)
    result  = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SHEET_ID, range=f"'{tab}'")
        .execute()
    )
    rows = result.get("values", [])

    if len(rows) < 5:
        raise HTTPException(400, "Sheet hat zu wenige Zeilen")

    # Parse header
    date_row = rows[2] if len(rows) > 2 else []
    time_row = rows[3] if len(rows) > 3 else []

    # Find date columns (index >= 2 with both date and time)
    date_cols = []
    for c in range(2, max(len(date_row), len(time_row))):
        d = date_row[c] if c < len(date_row) else None
        t = time_row[c] if c < len(time_row) else None
        if d and t and isinstance(d, str) and isinstance(t, str):
            if "kommentar" in t.lower() or "kommentar" in d.lower():
                continue
            date_cols.append({"col": c, "date": d.strip(), "time": t.strip()})

    # Parse actor availability
    actor_avail: dict[str, dict[int, bool]] = {}
    for r in range(4, len(rows)):
        row = rows[r]
        if len(row) < 2:
            continue
        name    = str(row[0]).strip() if row[0] else ""
        vorname = str(row[1]).strip() if row[1] else ""
        if not name or not vorname:
            continue
        key = f"{name}|{vorname}"
        actor_avail[key] = {}
        for dc in date_cols:
            c   = dc["col"]
            val = row[c].strip().lower() if c < len(row) and row[c] else ""
            actor_avail[key][c] = (val == "x")

    # Load scenes from DB
    scene_rows = db.execute("SELECT id, name, actors FROM scenes ORDER BY id").fetchall()
    scenes = [{"id": r["id"], "name": r["name"], "actors": json.loads(r["actors"])} for r in scene_rows]

    # Compute result
    results = []
    for dc in date_cols:
        c = dc["col"]
        possible = []
        for scene in scenes:
            if not scene["name"].strip():
                continue
            if not scene["actors"]:
                continue
            if all(
                actor_avail.get(f"{a['name']}|{a['vorname']}", {}).get(c, False)
                for a in scene["actors"]
            ):
                possible.append({"id": scene["id"], "name": scene["name"],
                                  "actors": scene["actors"]})
        results.append({"date": dc["date"], "time": dc["time"], "scenes": possible})

    return {"results": results}

# ── Frontend ──────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
