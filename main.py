from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sqlite3, os, uuid, fitz, docx
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np, json

DATABASE_URL = (
    "postgresql://neondb_owner:npg_AEQ8r5tXDhdg@"
    "ep-cool-bread-a8pe8h2p-pooler.eastus2.azure.neon.tech/"
    "neondb?sslmode=require&channel_binding=require"
)

app = FastAPI()
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sqlite3, os, uuid, fitz, docx
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np, json

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MODEL = SentenceTransformer('all-MiniLM-L6-v2')
DB    = "submissions.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── DB Setup ────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id TEXT PRIMARY KEY,
        filename TEXT,
        assignment TEXT,
        raw_text TEXT,
        embedding TEXT   -- stored as JSON array
    )""")
    con.commit(); con.close()

init_db()

# ── Text Extraction ─────────────────────────────────────────
def extract_text(path: str, filename: str) -> str:
    ext = filename.split(".")[-1].lower()
    if ext == "pdf":
        return " ".join(p.get_text() for p in fitz.open(path))
    elif ext == "docx":
        return " ".join(p.text for p in docx.Document(path).paragraphs)
    else:  # .txt, .py, etc.
        return open(path).read()

# ── Core Similarity Check ────────────────────────────────────
def check_plagiarism(new_text: str, assignment: str):
    new_emb = MODEL.encode([new_text])[0]

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT id, filename, raw_text, embedding FROM submissions WHERE assignment=?",
        (assignment,)
    ).fetchall()
    con.close()

    results = []
    for row in rows:
        past_emb = np.array(json.loads(row[3]))
        score = float(cosine_similarity([new_emb], [past_emb])[0][0])
        if score > 0.75:  # threshold — tune this
            results.append({
                "matched_file": row[1],
                "similarity_score": round(score * 100, 1),
                "preview": row[2][:300]  # first 300 chars
            })

    return sorted(results, key=lambda x: -x["similarity_score"])

# ── Routes ───────────────────────────────────────────────────
@app.post("/submit")
async def submit(
    file: UploadFile = File(...),
    assignment: str  = Form(...)
):
    sub_id   = str(uuid.uuid4())
    filepath = f"{UPLOAD_DIR}/{sub_id}_{file.filename}"

    # Save file
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # Extract text + embed
    text      = extract_text(filepath, file.filename)
    embedding = MODEL.encode([text])[0].tolist()

    # Check against past submissions BEFORE saving
    matches = check_plagiarism(text, assignment)

    # Save new submission to DB
    con = sqlite3.connect(DB)
    con.execute(
        "INSERT INTO submissions VALUES (?,?,?,?,?)",
        (sub_id, file.filename, assignment, text, json.dumps(embedding))
    )
    con.commit(); con.close()

    return JSONResponse({
        "submission_id":   sub_id,
        "filename":        file.filename,
        "matches_found":   len(matches),
        "results":         matches,
        "overall_risk":    "HIGH" if any(m["similarity_score"] > 90 for m in matches)
                           else "MEDIUM" if matches else "CLEAN"
    })

@app.get("/submissions")
def get_submissions(assignment: str = None):
    con = sqlite3.connect(DB)
    q   = "SELECT id, filename, assignment FROM submissions"
    rows = con.execute(q + (" WHERE assignment=?" if assignment else ""),
                       (assignment,) if assignment else ()).fetchall()
    con.close()
    return [{"id": r[0], "filename": r[1], "assignment": r[2]} for r in rows]
