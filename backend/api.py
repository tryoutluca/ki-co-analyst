"""
backend/api.py — KI-Co-Analyst FastAPI Backend

Start: uvicorn backend.api:app --reload --port 8000
"""

import hashlib
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Projektroot ins sys.path damit agents/graph/tools importierbar sind
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

SECRET_KEY       = os.environ.get("JWT_SECRET", "ki-co-analyst-dev-secret-change-in-prod")
ALGORITHM        = "HS256"
TOKEN_EXPIRE_MIN = 480  # 8 Stunden

CREDENTIALS_FILE = ROOT / "credentials.json"
HISTORY_DIR      = ROOT / "history"
HISTORY_DIR.mkdir(exist_ok=True)

_DEFAULT_CREDS: dict = {}

# In-Memory Job-Store  { job_id: { status, progress, result, error } }
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS: AUTH
# ══════════════════════════════════════════════════════════════════════════════

def _load_creds() -> dict:
    if CREDENTIALS_FILE.exists():
        try:
            return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _DEFAULT_CREDS

def _save_creds(creds: dict):
    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2), encoding="utf-8")

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _verify_user(username: str, password: str) -> bool:
    return _load_creds().get(username) == _hash(password)

def _create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MIN)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS: HISTORY
# ══════════════════════════════════════════════════════════════════════════════

def _save_history(data: dict) -> str:
    ticker = data.get("ticker", "UNKNOWN")
    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    name   = f"{ticker}_{ts}"
    fp     = HISTORY_DIR / f"{name}.json"
    fp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return name

def _list_history(limit: int = 50) -> list[dict]:
    out = []
    for fp in sorted(HISTORY_DIR.glob("*.json"),
                     key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            out.append({
                "id":          fp.stem,
                "ticker":      d.get("ticker", "-"),
                "company":     d.get("company", "-"),
                "date":        d.get("date", "-"),
                "recommendation": d.get("final_recommendation", "-"),
                "price_target":   d.get("price_target", "-"),
                "upside":         d.get("upside_downside_pct", None),
                "conviction":     d.get("conviction_level", "-"),
                "score":          d.get("data_consistency_score", None),
                "currency":       d.get("currency", ""),
            })
        except Exception:
            pass
    return out

def _get_history_item(item_id: str) -> dict | None:
    fp = HISTORY_DIR / f"{item_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="KI-Co-Analyst API", version="1.0.0")

_CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ══════════════════════════════════════════════════════════════════════════════
# AUTH DEPENDENCY
# ══════════════════════════════════════════════════════════════════════════════

def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Ungültiger oder abgelaufener Token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    if username not in _load_creds():
        raise credentials_exception
    return username


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES: AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    if not _verify_user(form.username, form.password):
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")
    token = _create_token(form.username)
    return {"access_token": token, "token_type": "bearer", "username": form.username}

@app.get("/auth/me")
def me(current_user: str = Depends(get_current_user)):
    return {"username": current_user}

@app.put("/auth/password")
def change_password(body: PasswordChangeRequest,
                    current_user: str = Depends(get_current_user)):
    if not _verify_user(current_user, body.old_password):
        raise HTTPException(status_code=400, detail="Aktuelles Passwort falsch")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Mindestens 8 Zeichen")
    creds = _load_creds()
    creds[current_user] = _hash(body.new_password)
    _save_creds(creds)
    return {"ok": True}

@app.post("/auth/register", status_code=201)
def register(req: RegisterRequest):
    if not req.username or not req.email or not req.password:
        raise HTTPException(status_code=422, detail="Alle Felder sind erforderlich.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 8 Zeichen haben.")
    creds = _load_creds()
    if req.username in creds:
        raise HTTPException(status_code=409, detail="Benutzername bereits vergeben.")
    creds[req.username] = _hash(req.password)
    _save_creds(creds)
    return {"message": "Registrierung erfolgreich."}


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES: TICKER SEARCH
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/search")
def search(q: str, _: str = Depends(get_current_user)):
    if len(q) < 2:
        return []
    try:
        from tools.finance_tools import search_ticker
        return search_ticker(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES: ANALYSE (Job-based)
# ══════════════════════════════════════════════════════════════════════════════

def _run_job(job_id: str, ticker: str):
    """Läuft in einem Background-Thread."""
    def _progress(msg: str):
        with _jobs_lock:
            _jobs[job_id]["progress"].append(msg)

    _progress(f"Starte Analyse für {ticker}…")
    try:
        # Wir leiten print() um, damit LangGraph-Logs als Progress erscheinen
        import io

        class ProgressCapture(io.StringIO):
            def write(self, text: str):
                text = text.strip()
                if text:
                    _progress(text)
                return len(text)

        old_stdout = sys.stdout
        sys.stdout = ProgressCapture()

        try:
            from graph.graph import run_analysis
            result = run_analysis(ticker)
        finally:
            sys.stdout = old_stdout

        result["ticker"] = ticker.upper()
        if not result.get("date"):
            result["date"] = datetime.now().strftime("%Y-%m-%d")

        # Deterministic recommendation based on upside/downside
        upside = result.get("upside_downside_pct")
        if isinstance(upside, (int, float)):
            if upside > 10:
                rec = "KAUFEN"
            elif upside > 5:
                rec = "ÜBERGEWICHTEN"
            elif upside >= -5:
                rec = "HALTEN"
            elif upside >= -10:
                rec = "UNTERGEWICHTEN"
            else:
                rec = "VERKAUFEN"
            result["final_recommendation"] = rec

        hist_id = _save_history(result)

        with _jobs_lock:
            _jobs[job_id].update({
                "status":   "done",
                "result":   result,
                "hist_id":  hist_id,
            })
        _progress("✅ Analyse abgeschlossen")

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id].update({"status": "error", "error": str(e)})
        _progress(f"❌ Fehler: {e}")


@app.post("/analyse/{ticker}")
def start_analysis(ticker: str, current_user: str = Depends(get_current_user)):
    ticker = ticker.upper().strip()
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status":   "running",
            "ticker":   ticker,
            "progress": [],
            "result":   None,
            "error":    None,
            "hist_id":  None,
            "started_at": datetime.now().isoformat(),
        }
    thread = threading.Thread(target=_run_job, args=(job_id, ticker), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "running"}


@app.get("/analyse/jobs/{job_id}")
def job_status(job_id: str, after: int = 0, _: str = Depends(get_current_user)):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return {
        "job_id":   job_id,
        "status":   job["status"],
        "ticker":   job["ticker"],
        "progress": job["progress"][after:],   # nur neue Zeilen ab Index 'after'
        "result":   job["result"],
        "error":    job["error"],
        "hist_id":  job["hist_id"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES: HISTORY
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/history")
def history(limit: int = 50, _: str = Depends(get_current_user)):
    return _list_history(limit)

@app.get("/history/{item_id}")
def history_item(item_id: str, _: str = Depends(get_current_user)):
    d = _get_history_item(item_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Analyse nicht gefunden")
    return d

@app.get("/history/{item_id}/pdf")
def history_pdf(item_id: str, _: str = Depends(get_current_user)):
    d = _get_history_item(item_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Analyse nicht gefunden")
    try:
        from backend.pdf_generator import generate_memo_pdf
        pdf_bytes = generate_memo_pdf(d)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF-Generierung fehlgeschlagen: {e}")
    ticker = d.get("ticker", "memo")
    date   = d.get("date", "")
    filename = f"{ticker}_{date}_memo.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.delete("/history/{item_id}")
def delete_history(item_id: str, _: str = Depends(get_current_user)):
    fp = HISTORY_DIR / f"{item_id}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    fp.unlink()
    return {"ok": True}

@app.get("/history/stats/summary")
def history_stats(_: str = Depends(get_current_user)):
    items = _list_history(500)
    return {
        "total":     len(items),
        "last":      items[0] if items else None,
        "by_rec":    _group_by(items, "recommendation"),
    }

def _group_by(items: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for i in items:
        v = i.get(key, "?")
        out[v] = out.get(v, 0) + 1
    return out


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
