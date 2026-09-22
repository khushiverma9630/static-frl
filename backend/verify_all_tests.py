import os
import json
import urllib.request
import urllib.error

FRONTEND_URL = "http://localhost:5500"
BACKEND_URL = "http://127.0.0.1:8000"

print("==================================================")
print("RUNNING COMPREHENSIVE AUTOMATED VERIFICATION")
print("==================================================")

# TEST 1: Open public website
try:
    res = urllib.request.urlopen(f"{FRONTEND_URL}/")
    assert res.status == 200
    html = res.read().decode("utf-8")
    assert "Frontier Research Lab" in html
    assert "The Frontier Research Series" in html
    print("TEST 1 PASSED: Public website loads successfully (HTTP 200).")
except Exception as e:
    print("TEST 1 FAILED:", e)
    exit(1)

# TEST 2: Stealth trigger in footer
assert 'id="adminTrigger"' in html
assert 'class="admin-stealth-trigger"' in html
assert 'href="/admin"' in html
print("TEST 2 PASSED: Stealth admin trigger exists in bottom-right corner of footer linking to /admin.")

# TEST 3 & 4: Admin Login (Valid & Invalid Credentials)
# Invalid login
invalid_body = json.dumps({"username": "wrong_user", "password": "wrong_password"}).encode()
req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/login",
    data=invalid_body,
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    urllib.request.urlopen(req)
    print("TEST 4 FAILED: Invalid login did not return error.")
    exit(1)
except urllib.error.HTTPError as e:
    assert e.code == 401
    print("TEST 4 PASSED: Invalid credentials correctly rejected with HTTP 401.")

# Valid login
valid_body = json.dumps({"username": "upload_research_paper", "password": "Upload_Research_Paper"}).encode()
req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/login",
    data=valid_body,
    headers={"Content-Type": "application/json"},
    method="POST"
)
res = urllib.request.urlopen(req)
assert res.status == 200
login_data = json.loads(res.read().decode("utf-8"))
token = login_data.get("token")
assert token is not None and len(token) > 20
print(f"TEST 3 PASSED: Valid admin credentials accepted. Secure token issued: {token[:12]}...")

# Check Auth endpoint with token
req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/check-auth",
    headers={"Authorization": f"Bearer {token}"}
)
res = urllib.request.urlopen(req)
assert res.status == 200
auth_check = json.loads(res.read().decode("utf-8"))
assert auth_check.get("authenticated") is True
print("AUTH CHECK PASSED: Token verified by backend.")

# TEST 5: Upload PDF & Create Research Paper
pdf_source = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "research paper", "AAR-WP-2026-21_Working_Paper.pdf"))
with open(pdf_source, "rb") as f:
    pdf_bytes = f.read()

boundary = "----TestBoundary987654321"
multipart_data = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="Autonomous_Agent_Verification_2026.pdf"\r\n'
    f"Content-Type: application/pdf\r\n\r\n"
).encode("utf-8") + pdf_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/upload-pdf",
    data=multipart_data,
    headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Authorization": f"Bearer {token}"
    },
    method="POST"
)
res = urllib.request.urlopen(req)
assert res.status == 200
upload_info = json.loads(res.read().decode("utf-8"))
uploaded_file_path = upload_info.get("file")
assert uploaded_file_path and uploaded_file_path.startswith("research paper/")
print(f"PDF UPLOAD PASSED: Uploaded PDF stored at '{uploaded_file_path}'.")

test_paper = {
    "title": "Autonomous Agent Verification Framework 2026",
    "subtitle": "Runtime Invariants and Verifiable Attestation for Continuous Agentic Pipelines",
    "type": "Research Paper",
    "status": "In review",
    "author": "Dr. Binod Kumar",
    "authorRole": "Founder & Chief AI Officer, AgentsArchitects.ai · AI Research Mentor",
    "authorAffiliation": "Indian Institute of Technology Bombay",
    "labAffiliation": "Frontier Research Series",
    "date": "October 2026",
    "series": "Frontier Research Series",
    "format": "PDF (18 pages)",
    "subjects": ["Agent Verification", "Runtime Invariants", "AI Governance", "cs.CR"],
    "provenance": "Preprints in the Frontier Research Series are reviewed internally and by outside researchers.",
    "abstract": [
        "Paragraph 1: Continuous autonomous agent workflows operating without direct synchronous operator supervision require real-time invariants.",
        "Paragraph 2: We demonstrate verifiable execution traces and runtime state bounds across multi-hop agent handoffs."
    ],
    "file": uploaded_file_path
}

req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/publications",
    data=json.dumps(test_paper).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    },
    method="POST"
)
res = urllib.request.urlopen(req)
assert res.status == 200
created_data = json.loads(res.read().decode("utf-8"))
created_slug = created_data["publication"]["slug"]
print(f"TEST 5 PASSED: Test research paper published with slug '{created_slug}'.")

# TEST 6: Verify new paper appears at the TOP of public list
res = urllib.request.urlopen(f"{BACKEND_URL}/api/publications")
public_pubs = json.loads(res.read().decode("utf-8"))
assert len(public_pubs) == 9
assert public_pubs[0]["slug"] == created_slug
assert public_pubs[0]["title"] == "Autonomous Agent Verification Framework 2026"
print("TEST 6 PASSED: Newly published paper appears at the TOP of the public publications list.")

# TEST 7: Dynamic Publication Detail Page Data
top_paper = public_pubs[0]
assert top_paper["slug"] == created_slug
assert len(top_paper["abstract"]) == 2
assert top_paper["file"] == uploaded_file_path
print(f"TEST 7 PASSED: Detail data for '/publications/{created_slug}' correctly resolved with 2 abstract paragraphs.")

# TEST 8 & 9: Download / Email Endpoint Verification with uploaded PDF
# Verify file on disk exists
real_disk_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", uploaded_file_path))
assert os.path.exists(real_disk_path)
print(f"TEST 8 PASSED: Uploaded file physically exists on disk ({os.path.getsize(real_disk_path)} bytes).")

# Test Download endpoint path verification (dry-run attachment check)
# Download endpoint uses GMAIL credentials if set; we verify path traversal check blocks invalid paths
traversal_payload = json.dumps({
    "email": "researcher@example.com",
    "paperTitle": "Hacked",
    "paperFile": "../../windows/system32/cmd.exe"
}).encode()
req = urllib.request.Request(
    f"{BACKEND_URL}/api/download",
    data=traversal_payload,
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    urllib.request.urlopen(req)
    print("TEST 9 FAILED: Traversal attack not blocked!")
    exit(1)
except urllib.error.HTTPError as e:
    assert e.code == 400
    print("TEST 9 PASSED: Path traversal protection actively verified (HTTP 400).")

# TEST 10: Edit Publication
test_paper["title"] = "Autonomous Agent Verification Framework 2026 (Revised Edition)"
test_paper["status"] = "Published"
req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/publications/{created_slug}",
    data=json.dumps(test_paper).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    },
    method="PUT"
)
res = urllib.request.urlopen(req)
assert res.status == 200
edited_data = json.loads(res.read().decode("utf-8"))
assert edited_data["publication"]["title"] == "Autonomous Agent Verification Framework 2026 (Revised Edition)"
assert edited_data["publication"]["status"] == "Published"

# Verify public list reflects change immediately
res = urllib.request.urlopen(f"{BACKEND_URL}/api/publications")
public_pubs = json.loads(res.read().decode("utf-8"))
assert public_pubs[0]["title"] == "Autonomous Agent Verification Framework 2026 (Revised Edition)"
assert public_pubs[0]["status"] == "Published"
print("TEST 10 PASSED: Edit publication works; public list reflects updated title and status immediately.")

# TEST 11: Delete Publication
req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/publications/{created_slug}",
    headers={"Authorization": f"Bearer {token}"},
    method="DELETE"
)
res = urllib.request.urlopen(req)
assert res.status == 200
delete_info = json.loads(res.read().decode("utf-8"))
assert delete_info.get("success") is True

# Verify public list count returns to 8
res = urllib.request.urlopen(f"{BACKEND_URL}/api/publications")
public_pubs = json.loads(res.read().decode("utf-8"))
assert len(public_pubs) == 8
assert not any(p["slug"] == created_slug for p in public_pubs)
print("TEST 11 PASSED: Publication deleted; removed from public list and total count restored to 8.")

# Clean up uploaded PDF test file
if os.path.exists(real_disk_path):
    os.remove(real_disk_path)
    print("Cleaned up test uploaded PDF file.")

# TEST 12: Persistence check (read publications.json directly from disk)
data_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "publications.json"))
with open(data_file, "r", encoding="utf-8") as f:
    disk_data = json.load(f)
assert len(disk_data) == 8
print("TEST 12 PASSED: Persistence verified; publications.json on disk correctly contains all 8 initial publications.")

# TEST 13 & 14: Logout & Token Invalidation
req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/logout",
    headers={"Authorization": f"Bearer {token}"},
    method="POST"
)
res = urllib.request.urlopen(req)
assert res.status == 200
print("TEST 13 PASSED: Admin logout executed successfully.")

# Attempt to call protected endpoint with invalidated token
req = urllib.request.Request(
    f"{BACKEND_URL}/api/admin/check-auth",
    headers={"Authorization": f"Bearer {token}"}
)
try:
    urllib.request.urlopen(req)
    print("TEST 14 FAILED: Invalidated token was accepted!")
    exit(1)
except urllib.error.HTTPError as e:
    assert e.code == 401
    print("TEST 14 PASSED: Expired/invalidated session correctly returns HTTP 401 Unauthorized.")

# TEST 15: Public visitor view has no visible Admin button
assert "admin-stealth-trigger" in html
# Check that no visible text says "Admin" in normal navigation
import re
nav_links = re.findall(r'<nav aria-label="Primary">.*?</nav>', html, re.DOTALL)
assert "Admin" not in nav_links[0]
print("TEST 15 PASSED: Navigation bar is clean with no visible Admin button for normal visitors.")

print("==================================================")
print("ALL 15 TESTS SUCCESSFULLY PASSED!")
print("==================================================")
