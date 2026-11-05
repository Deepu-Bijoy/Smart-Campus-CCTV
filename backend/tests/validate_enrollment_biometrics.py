import os
import sys
import json
import sqlite3
import numpy as np

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings

def test_step_2_enrollment_embeddings():
    print("=== Step 2: Validating Enrollment Embeddings ===")
    db_path = os.path.join(settings.STORAGE_DIR, "cctv.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, student_id, embedding, model_version, quality_score FROM student_face_embeddings")
    rows = c.fetchall()
    print(f"Total enrolled embeddings found in SQLite: {len(rows)}")
    
    assert len(rows) > 0, "No enrolled embeddings found!"
    
    norms = []
    dims = []
    student_ids = set()
    model_versions = set()
    
    for emb_id, s_id, emb_json, model_ver, qual in rows:
        student_ids.add(s_id)
        model_versions.add(model_ver)
        if isinstance(emb_json, str):
            vec = np.array(json.loads(emb_json), dtype=np.float32)
        elif isinstance(emb_json, (bytes, bytearray)):
            vec = np.frombuffer(emb_json, dtype=np.float32)
        else:
            vec = np.array(emb_json, dtype=np.float32)
            
        dims.append(len(vec))
        norm = np.linalg.norm(vec)
        norms.append(norm)
        assert len(vec) == 512, f"Embedding {emb_id} dim is {len(vec)}, expected 512"
        assert not np.isnan(norm) and not np.isinf(norm), f"Embedding {emb_id} has invalid norm"
        assert norm > 0.001, f"Embedding {emb_id} is zero-norm"
        assert 0.99 <= norm <= 1.01, f"Embedding {emb_id} norm {norm:.4f} not unit normalized"
    
    print(f"Validated {len(rows)} embeddings across {len(student_ids)} students.")
    print(f"Model versions: {model_versions}")
    print(f"All embeddings are 512-dim unit vectors (mean norm: {np.mean(norms):.4f}, min norm: {np.min(norms):.4f}, max norm: {np.max(norms):.4f}).")

    # Verify student identity linkages
    c.execute("SELECT s.id, s.name, s.university_roll_number, COUNT(fe.id) FROM students s JOIN student_face_embeddings fe ON s.id = fe.student_id GROUP BY s.id")
    students = c.fetchall()
    for s_id, s_name, s_roll, cnt in students:
        print(f"  Student: {s_name} (Roll: {s_roll}) -> {cnt} embedding(s)")
    
    conn.close()
    return True

if __name__ == "__main__":
    test_step_2_enrollment_embeddings()
