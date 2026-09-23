import os
import re
import json
import time
import secrets
import smtplib
import threading
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional, List, Union

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, constr, Field
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

RESEARCH_ADMIN_USERNAME = os.getenv("RESEARCH_ADMIN_USERNAME", "upload_research_paper")
RESEARCH_ADMIN_PASSWORD = os.getenv("RESEARCH_ADMIN_PASSWORD", "Upload_Research_Paper")
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "default-frl-secret-key-2026")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_PAPER_DIR = os.path.join(BASE_DIR, "research paper")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PUBLICATIONS_FILE = os.path.join(DATA_DIR, "publications.json")

os.makedirs(RESEARCH_PAPER_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="Frontier Research Lab API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === SESSION & AUTHENTICATION LAYER ===
# In-memory session store: token -> {"username": str, "expires_at": float}
ACTIVE_SESSIONS: dict[str, dict] = {}
SESSION_TTL_SECONDS = 86400  # 24 hours
SESSION_LOCK = threading.Lock()

security = HTTPBearer(auto_error=False)


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_TTL_SECONDS
    with SESSION_LOCK:
        # Cleanup expired sessions
        now = time.time()
        expired = [t for t, data in ACTIVE_SESSIONS.items() if data["expires_at"] < now]
        for t in expired:
            ACTIVE_SESSIONS.pop(t, None)
        ACTIVE_SESSIONS[token] = {"username": username, "expires_at": expires_at}
    return token


def invalidate_session(token: str) -> bool:
    with SESSION_LOCK:
        if token in ACTIVE_SESSIONS:
            del ACTIVE_SESSIONS[token]
            return True
        return False


def get_current_admin(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    with SESSION_LOCK:
        session = ACTIVE_SESSIONS.get(token)
        if not session or session["expires_at"] < time.time():
            if session:
                del ACTIVE_SESSIONS[token]
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return session["username"]


# === PERSISTENT PUBLICATIONS STORAGE ===
DATA_LOCK = threading.Lock()


def load_publications() -> list[dict]:
    with DATA_LOCK:
        if not os.path.exists(PUBLICATIONS_FILE):
            return []
        try:
            with open(PUBLICATIONS_FILE, "r", encoding="utf-8") as f:
                pubs = json.load(f)
                # Sort newest first by created_at
                return sorted(pubs, key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception as e:
            print(f"Error reading {PUBLICATIONS_FILE}: {e}")
            return []


def save_publications(pubs: list[dict]) -> None:
    with DATA_LOCK:
        # Atomic write pattern: write to tmp file first then rename
        tmp_file = PUBLICATIONS_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(pubs, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, PUBLICATIONS_FILE)


def generate_safe_slug(title: str, existing_slugs: list[str], current_slug: Optional[str] = None) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    if not slug:
        slug = f"paper-{secrets.token_hex(3)}"
    base_slug = slug
    counter = 2
    while slug in existing_slugs and slug != current_slug:
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def generate_unique_numeric_id(existing_ids: set) -> str:
    """Generate a stable, unique 9-digit numeric publication identifier (e.g. 786579303)."""
    while True:
        candidate = str(secrets.randbelow(900000000) + 100000000)
        if candidate not in existing_ids:
            return candidate


# === PYDANTIC SCHEMAS ===
class ContactForm(BaseModel):
    fullName: constr(min_length=1, strip_whitespace=True)
    phone: constr(min_length=1, strip_whitespace=True)
    email: EmailStr
    message: constr(min_length=1, strip_whitespace=True)


class DownloadRequest(BaseModel):
    email: EmailStr
    paperTitle: str
    paperFile: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class PublicationPayload(BaseModel):
    title: constr(min_length=3, strip_whitespace=True)
    subtitle: Optional[str] = ""
    type: Optional[str] = "Research Paper"
    status: Optional[str] = "In review"
    author: constr(min_length=1, strip_whitespace=True)
    authorRole: Optional[str] = ""
    authorAffiliation: Optional[str] = ""
    labAffiliation: Optional[str] = ""
    date: Optional[str] = ""
    series: Optional[str] = "Frontier Research Series"
    format: Optional[str] = "PDF / Research Paper"
    subjects: Optional[List[str]] = Field(default_factory=list)
    provenance: Optional[str] = (
        "Preprints in the Frontier Research Series are reviewed internally and by outside researchers. "
        "Published artifacts, reference implementations, and evaluations remain subject to open reproduction."
    )
    abstract: Union[List[str], str]
    file: Optional[str] = ""


# === PUBLIC ENDPOINTS ===

@app.get("/api/publications")
async def get_public_publications():
    """Retrieve all publications ordered newest-first."""
    return load_publications()


@app.get("/api/publications/{pub_id}")
async def get_public_publication(pub_id: str):
    """Retrieve a single publication by its unique numeric ID (with backward compatibility)."""
    pub_id_str = str(pub_id).strip()
    pubs = load_publications()

    # 1. Match by numeric ID
    for p in pubs:
        if str(p.get("id")) == pub_id_str or str(p.get("numeric_id")) == pub_id_str:
            return p

    # 2. Match by legacy title slug for backward compatibility
    for p in pubs:
        if p.get("legacy_slug") == pub_id_str or str(p.get("slug")) == pub_id_str:
            return p

    raise HTTPException(status_code=404, detail="Publication not found.")


@app.post("/api/contact")
async def handle_contact(form: ContactForm):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise HTTPException(status_code=500, detail="Server email configuration is missing.")

    subject = "New Contact Form Submission - Frontier Research Lab"
    body = f"""Name:
{form.fullName}

Phone:
{form.phone}

Email:
{form.email}

Message:
{form.message}
"""

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = f"Frontier Research Lab <{GMAIL_USER}>"
    msg["To"] = "frontierresearchlabb@gmail.com"
    msg.add_header("Reply-To", form.email)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")
        raise HTTPException(status_code=500, detail="Oops! There was a problem submitting your form. Please try again later.")

    return {"success": True, "message": "Thank you. Your message has been sent."}


@app.post("/api/download")
async def handle_download(req: DownloadRequest):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise HTTPException(status_code=500, detail="Server email configuration is missing.")

    # Prevent directory traversal attacks
    target_path = os.path.abspath(os.path.join(BASE_DIR, req.paperFile))
    if not target_path.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(status_code=400, detail="Invalid publication file path.")

    subject = f"Your Research Paper Download: {req.paperTitle} - Frontier Research Lab"
    
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #0D1115; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #001ACF; border-bottom: 2px solid #C4EA02; padding-bottom: 8px;">Frontier Research Lab</h2>
        <p>Dear Researcher,</p>
        <p>Thank you for your interest in our research. Here is your requested research paper:</p>
        <div style="background-color: #F2F3F0; padding: 16px; border-radius: 4px; margin: 20px 0;">
          <h3 style="margin-top: 0; color: #0D1115;">{req.paperTitle}</h3>
          <p style="margin-bottom: 0;">Attached or linked below for your review.</p>
        </div>
        <p>Best regards,<br><strong>Frontier Research Lab Team</strong><br><a href="mailto:frontierresearchlabb@gmail.com" style="color: #001ACF;">frontierresearchlabb@gmail.com</a></p>
      </body>
    </html>
    """

    msg = EmailMessage()
    msg.set_content(f"Thank you for requesting '{req.paperTitle}'. Please see attached.")
    msg.add_alternative(html_content, subtype="html")
    msg["Subject"] = subject
    msg["From"] = f"Frontier Research Lab <{GMAIL_USER}>"
    msg["To"] = req.email

    if os.path.exists(target_path):
        filename = os.path.basename(target_path)
        with open(target_path, "rb") as f:
            file_data = f.read()
            msg.add_attachment(file_data, maintype="application", subtype="octet-stream", filename=filename)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send download email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email. Please check your email address and try again.")

    return {"success": True, "message": "Research paper sent to your email successfully!"}


# === ADMIN AUTHENTICATION ENDPOINTS ===

@app.post("/api/admin/login")
async def admin_login(req: AdminLoginRequest):
    # Constant-time string comparison to prevent timing side-channel attacks
    valid_user = secrets.compare_digest(req.username, RESEARCH_ADMIN_USERNAME)
    valid_pass = secrets.compare_digest(req.password, RESEARCH_ADMIN_PASSWORD)

    if not (valid_user and valid_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_session(req.username)
    return {
        "success": True,
        "token": token,
        "username": req.username,
        "expires_in": SESSION_TTL_SECONDS
    }


@app.post("/api/admin/logout")
async def admin_logout(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials and credentials.credentials:
        invalidate_session(credentials.credentials)
    return {"success": True, "message": "Logged out successfully."}


@app.get("/api/admin/check-auth")
async def admin_check_auth(admin: str = Depends(get_current_admin)):
    return {"authenticated": True, "username": admin}


# === ADMIN PUBLICATION MANAGEMENT ENDPOINTS ===

@app.get("/api/admin/publications")
async def admin_list_publications(admin: str = Depends(get_current_admin)):
    return load_publications()


@app.post("/api/admin/publications")
async def admin_create_publication(payload: PublicationPayload, admin: str = Depends(get_current_admin)):
    pubs = load_publications()
    existing_ids = {str(p.get("id")) for p in pubs if p.get("id")}
    existing_ids.update({str(p.get("numeric_id")) for p in pubs if p.get("numeric_id")})
    existing_ids.update({str(p.get("slug")) for p in pubs if p.get("slug") and str(p.get("slug")).isdigit()})

    numeric_id = generate_unique_numeric_id(existing_ids)

    # Normalize abstract to list of clean non-empty paragraphs
    if isinstance(payload.abstract, str):
        paragraphs = [p.strip() for p in payload.abstract.split("\n\n") if p.strip()]
    else:
        paragraphs = [str(p).strip() for p in payload.abstract if str(p).strip()]

    now_iso = datetime.now(timezone.utc).isoformat()
    pub_date = payload.date if payload.date else datetime.now(timezone.utc).strftime("%B %Y")

    new_pub = {
        "id": numeric_id,
        "numeric_id": numeric_id,
        "slug": numeric_id,
        "title": payload.title,
        "subtitle": payload.subtitle or "",
        "type": payload.type or "Research Paper",
        "status": payload.status or "In review",
        "author": payload.author,
        "authorRole": payload.authorRole or "",
        "authorAffiliation": payload.authorAffiliation or "",
        "labAffiliation": payload.labAffiliation or "",
        "date": pub_date,
        "series": payload.series or "Frontier Research Series",
        "format": payload.format or "PDF / Research Paper",
        "subjects": payload.subjects or [],
        "provenance": payload.provenance or "",
        "abstract": paragraphs,
        "file": payload.file or "",
        "created_at": now_iso,
    }

    # Prepend to list so newest is stored first
    pubs.insert(0, new_pub)
    save_publications(pubs)
    return {"success": True, "publication": new_pub}


@app.put("/api/admin/publications/{slug}")
async def admin_update_publication(slug: str, payload: PublicationPayload, admin: str = Depends(get_current_admin)):
    pubs = load_publications()
    found_idx = None
    slug_str = str(slug).strip()
    for idx, p in enumerate(pubs):
        if str(p.get("id")) == slug_str or str(p.get("numeric_id")) == slug_str or str(p.get("slug")) == slug_str or p.get("legacy_slug") == slug_str:
            found_idx = idx
            break

    if found_idx is None:
        raise HTTPException(status_code=404, detail=f"Publication with ID '{slug}' not found.")

    target = pubs[found_idx]

    # Normalize abstract
    if isinstance(payload.abstract, str):
        paragraphs = [p.strip() for p in payload.abstract.split("\n\n") if p.strip()]
    else:
        paragraphs = [str(p).strip() for p in payload.abstract if str(p).strip()]

    target["title"] = payload.title
    target["subtitle"] = payload.subtitle or ""
    target["type"] = payload.type or target.get("type", "Research Paper")
    target["status"] = payload.status or target.get("status", "In review")
    target["author"] = payload.author
    target["authorRole"] = payload.authorRole or ""
    target["authorAffiliation"] = payload.authorAffiliation or ""
    target["labAffiliation"] = payload.labAffiliation or ""
    target["date"] = payload.date or target.get("date", "")
    target["series"] = payload.series or target.get("series", "Frontier Research Series")
    target["format"] = payload.format or target.get("format", "PDF / Research Paper")
    target["subjects"] = payload.subjects or []
    target["provenance"] = payload.provenance or target.get("provenance", "")
    target["abstract"] = paragraphs
    if payload.file:
        target["file"] = payload.file

    # Ensure stable numeric ID is strictly preserved across edits
    stable_id = str(target.get("id") or target.get("numeric_id") or target.get("slug"))
    target["id"] = stable_id
    target["numeric_id"] = stable_id
    target["slug"] = stable_id

    save_publications(pubs)
    return {"success": True, "publication": target}


@app.delete("/api/admin/publications/{slug}")
async def admin_delete_publication(slug: str, admin: str = Depends(get_current_admin)):
    pubs = load_publications()
    found_idx = None
    deleted_pub = None
    slug_str = str(slug).strip()
    for idx, p in enumerate(pubs):
        if str(p.get("id")) == slug_str or str(p.get("numeric_id")) == slug_str or str(p.get("slug")) == slug_str or p.get("legacy_slug") == slug_str:
            found_idx = idx
            deleted_pub = p
            break

    if found_idx is None:
        raise HTTPException(status_code=404, detail=f"Publication with ID '{slug}' not found.")

    pubs.pop(found_idx)
    save_publications(pubs)

    # Note: We do not automatically delete PDF files from disk to prevent accidental data loss,
    # but the paper is fully removed from metadata, listing, and detail page routes.
    return {"success": True, "message": f"Publication '{deleted_pub.get('title')}' deleted successfully."}


@app.post("/api/admin/upload-pdf")
async def admin_upload_pdf(file: UploadFile = File(...), admin: str = Depends(get_current_admin)):
    # 1. Validate file extension
    original_name = file.filename or "paper.pdf"
    ext = os.path.splitext(original_name)[1].lower()
    if ext != ".pdf":
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF files are accepted.")

    # 2. Validate content type header
    if file.content_type and file.content_type.lower() != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid MIME type. Must be application/pdf.")

    # 3. Sanitize filename and prevent collisions
    clean_base = re.sub(r"[^a-zA-Z0-9_\-]", "_", os.path.splitext(original_name)[0])[:40]
    safe_filename = f"{clean_base}_{secrets.token_hex(4)}.pdf"
    destination_path = os.path.join(RESEARCH_PAPER_DIR, safe_filename)

    # 4. Stream write with max size validation (50 MB limit)
    MAX_SIZE = 50 * 1024 * 1024  # 50 MB
    total_written = 0
    try:
        with open(destination_path, "wb") as out_f:
            while chunk := await file.read(64 * 1024):  # 64 KB chunks
                total_written += len(chunk)
                if total_written > MAX_SIZE:
                    out_f.close()
                    if os.path.exists(destination_path):
                        os.remove(destination_path)
                    raise HTTPException(status_code=400, detail="File too large. Maximum allowed size is 50MB.")
                out_f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(destination_path):
            os.remove(destination_path)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    relative_path = f"research paper/{safe_filename}"
    return {
        "success": True,
        "file": relative_path,
        "filename": safe_filename,
        "sizeBytes": total_written
    }
