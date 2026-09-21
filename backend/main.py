import os
import smtplib
from email.message import EmailMessage
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, constr
from dotenv import load_dotenv

# Load environment variables from .env file (should not be checked in)
load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ContactForm(BaseModel):
    fullName: constr(min_length=1, strip_whitespace=True)
    phone: constr(min_length=1, strip_whitespace=True)
    email: EmailStr
    message: constr(min_length=1, strip_whitespace=True)

class DownloadRequest(BaseModel):
    email: EmailStr
    paperTitle: str
    paperFile: str

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

    # Try attaching the file from research paper directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, req.paperFile)

    if os.path.exists(file_path):
        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
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

