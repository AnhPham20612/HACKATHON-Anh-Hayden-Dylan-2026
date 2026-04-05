from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os, uuid, fitz, docx, re, json
import google.generativeai as genai
from pydantic import BaseModel

# Import your teammate's database manager
from databaseFile import DataBaseManager, initialize_database

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── Gemini setup ─────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDbstkTxl3vAsgDkwMlmFUhFGipACn1HDw")
genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = genai.GenerativeModel("gemini-3-flash-preview")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Initialize the PostgreSQL database on startup
@app.on_event("startup")
def startup():
    initialize_database()
    db.seed_demo_data()  # ensures IDs 1/1 exist for demo use

db = DataBaseManager()

# ── Serve frontend ───────────────────────────────────────────
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/")
def serve_login():
    return FileResponse("Login.html")

@app.get("/app")
def serve_app():
    return FileResponse("PacificCheck.html")


# ── Text Extraction ─────────────────────────────────────────
def extract_text(path: str, filename: str) -> str:
    ext = filename.split(".")[-1].lower()
    if ext == "pdf":
        return " ".join(p.get_text() for p in fitz.open(path))
    elif ext == "docx":
        return " ".join(p.text for p in docx.Document(path).paragraphs)
    else:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()


# ── Gemini Similarity Check ──────────────────────────────────
def gemini_compare(new_text: str, past_text: str) -> dict:
    """
    Ask Gemini to compare two submissions and return a similarity score,
    risk level, and the most suspicious flagged passage.
    """
    prompt = f"""
You are an academic plagiarism detection assistant. Compare the two student submissions below and analyze them for plagiarism, paraphrasing, and idea-level similarity.

Return ONLY a JSON object with exactly these fields:
{{
  "similarity_score": <integer 0-100>,
  "reasoning": "<one sentence explaining the score>",
  "flagged_passage": "<the most suspicious sentence or phrase from Submission A, or empty string if none>"
}}

Rules:
- similarity_score 0-19 = clearly original work
- similarity_score 20-69 = moderate overlap, possible paraphrasing
- similarity_score 70-100 = high similarity, likely plagiarism
- Consider direct copying, paraphrasing, and reordered sentences all as plagiarism
- Do not include any text outside the JSON object

--- SUBMISSION A (new) ---
{new_text[:4000]}

--- SUBMISSION B (existing) ---
{past_text[:4000]}
"""
    try:
        response = GEMINI_MODEL.generate_content(prompt)
        raw = response.text.strip()
        # Strip markdown code fences if Gemini wraps the JSON
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        result = json.loads(raw)
        return {
            "similarity_score": float(result.get("similarity_score", 0)),
            "reasoning":        result.get("reasoning", ""),
            "flagged_passage":  result.get("flagged_passage", "")
        }
    except Exception as e:
        print(f"Gemini error: {e}")
        return {"similarity_score": 0.0, "reasoning": "Analysis failed.", "flagged_passage": ""}


def check_plagiarism(new_text: str, assignment_id: int):
    """
    Compare new submission against all past submissions using Gemini.
    """
    past_submissions = db.get_all_submissions_for_assignment(assignment_id)

    results = []
    for sub in past_submissions:
        analysis = gemini_compare(new_text, sub["content"])
        score = round(analysis["similarity_score"], 1)

        if score >= 20:  # only surface meaningful matches
            results.append({
                "matched_submission_id": sub["submission_id"],
                "matched_student":       f"{sub['first_name']} {sub['last_name']}",
                "matched_file":          sub.get("file_name", "N/A"),
                "similarity_score":      score,
                "reasoning":             analysis["reasoning"],
                "preview":               analysis["flagged_passage"] or sub["content"][:300]
            })

    return sorted(results, key=lambda x: -x["similarity_score"])


# ── Login Route ──────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/login")
def login(body: LoginRequest):
    """
    Basic login endpoint.
    TODO: Replace with real password hashing + session/JWT logic.
    """
    if not body.email.lower().endswith("@u.pacific.edu"):
        raise HTTPException(status_code=403, detail="Only @u.pacific.edu emails are allowed.")

    # Placeholder — always succeeds for valid UOP emails
    # In production: look up user in DB, verify hashed password
    return {"success": True, "email": body.email}


# ── Submit Route ─────────────────────────────────────────────
@app.post("/submit")
async def submit(
    file: UploadFile = File(...),
    assignment_id: int = Form(...),
    student_id: int = Form(...)         # pass this from your login session
):
    """
    Accept a file submission, extract text, check plagiarism,
    and store everything in PostgreSQL via DataBaseManager.
    """
    sub_uuid = str(uuid.uuid4())
    filepath = f"{UPLOAD_DIR}/{sub_uuid}_{file.filename}"

    # Save uploaded file to disk
    content_bytes = await file.read()
    with open(filepath, "wb") as f:
        f.write(content_bytes)

    # Extract plain text from the file
    text = extract_text(filepath, file.filename)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from file.")

    # Check against existing submissions BEFORE saving this one
    matches = check_plagiarism(text, assignment_id)
    overall_score = max((m["similarity_score"] for m in matches), default=0.0)

    # Guard: make sure the student and assignment IDs actually exist in the DB
    if not db.ensure_student_exists(student_id):
        raise HTTPException(status_code=404, detail=f"Student ID {student_id} not found. Please create the student record first.")
    if not db.ensure_assignment_exists(assignment_id):
        raise HTTPException(status_code=404, detail=f"Assignment ID {assignment_id} not found. Please create the assignment record first.")

    # Save the new submission to PostgreSQL
    submission_id = db.add_submission(
        student_id=student_id,
        assignment_id=assignment_id,
        content=text,
        file_name=file.filename,
        file_path=filepath
    )

    # Save the plagiarism check result
    check_id = db.create_plagiarism_check(
        submission_id=submission_id,
        similarity_score=overall_score
    )

    # Save each individual match
    for match in matches:
        db.add_similarity_match(
            check_id=check_id,
            original_submission_id=match["matched_submission_id"],
            similarity_score=match["similarity_score"],
            matched_snippet=match["preview"],
            match_location=match.get("reasoning", "")
        )

    return JSONResponse({
        "submission_id":   submission_id,
        "filename":        file.filename,
        "matches_found":   len(matches),
        "results":         matches,
        "overall_score":   overall_score,
        "overall_risk":    (
            "HIGH"   if overall_score >= 70 else
            "MEDIUM" if overall_score >= 20 else
            "CLEAN"
        )
    })


# ── Get Submissions for an Assignment ────────────────────────
@app.get("/submissions/{assignment_id}")
def get_submissions(assignment_id: int):
    """Return all submissions for a given assignment."""
    subs = db.get_all_submissions_for_assignment(assignment_id)
    return [
        {
            "submission_id": s["submission_id"],
            "student":       f"{s['first_name']} {s['last_name']}",
            "uop_id":        s["uop_id"],
            "file_name":     s.get("file_name"),
            "submitted_at":  str(s["submission_date"])
        }
        for s in subs
    ]


# ── Get Plagiarism Report for a Submission ───────────────────
@app.get("/report/{submission_id}")
def get_report(submission_id: int):
    """Return the plagiarism report for a specific submission."""
    report = db.get_plagiarism_report(submission_id)
    if not report:
        raise HTTPException(status_code=404, detail="No report found for this submission.")
    return report
