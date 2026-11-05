import logging
import uuid
import numpy as np
from typing import Dict, Any, Optional
from app.core.config import settings
from app.pipeline.face_engine import FaceEnrollmentEngine
from app.services.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

class StudentIdentifier:
    def __init__(self):
        self.face_engine = FaceEnrollmentEngine()
        self.vector_store = QdrantVectorStore()

    async def identify_face_in_crop(self, crop_path: str) -> Optional[Dict[str, Any]]:
        import os
        filename = os.path.basename(crop_path)
        track_id = filename.split("_")[0] if "_" in filename else "unknown"
        
        # Run quality gates face analysis
        res = self.face_engine.process_photo(crop_path, is_cctv=True)
        
        print("========== FACE DETECTION ==========")
        print(f"Track ID: {track_id}")
        if not res["success"]:
            print("Face found?: no")
            print(f"Reason: {res.get('error', 'Face not visible or failed quality gates')}")
            print("Bounding box: None")
            print("Confidence: None")
            print()
            print("========== FACE EMBEDDING ==========")
            print(f"Track ID: {track_id}")
            print("Embedding created?: no")
            print("Embedding dimension: None")
            print("Embedding norm: None")
            print()
            return None
            
        print("Face found?: yes")
        print(f"Bounding box: {res.get('bbox')}")
        print(f"Confidence: {res.get('quality_score'):.4f}")
        print()
        
        embedding = res["embedding"]
        emb_norm = float(np.linalg.norm(embedding))
        
        print("========== FACE EMBEDDING ==========")
        print(f"Track ID: {track_id}")
        print("Embedding created?: yes")
        print(f"Embedding dimension: {len(embedding)}")
        print(f"Embedding norm: {emb_norm:.6f}")
        print()
        
        try:
            # Query Qdrant for top-5 closest face embeddings
            response = self.vector_store.client.query_points(
                collection_name=self.vector_store.face_collection_name,
                query=embedding,
                limit=5,
                with_payload=True
            )
            results = response.points
            
            # Fetch total vectors
            total_vectors = 0
            try:
                coll_info = self.vector_store.client.get_collection(self.vector_store.face_collection_name)
                total_vectors = coll_info.points_count
            except Exception:
                pass
                
            top_5_matches = [r.id for r in results]
            similarity_scores = [float(r.score) for r in results]
            student_ids_returned = [r.payload.get("student_id") for r in results]
            
            print("========== QDRANT ==========")
            print(f"Collection used: {self.vector_store.face_collection_name}")
            print(f"Total vectors: {total_vectors}")
            print(f"Top 5 matches: {top_5_matches}")
            print(f"Similarity scores: {[f'{s:.4f}' for s in similarity_scores]}")
            print(f"Student IDs returned: {student_ids_returned}")
            print()
            
            best_match = results[0] if results else None
            student_id = best_match.payload.get("student_id") if best_match else None
            highest_similarity = similarity_scores[0] if similarity_scores else 0.0
            second_similarity = 0.0
            second_student_id = None
            if len(results) > 1:
                for r_idx in range(1, len(results)):
                    cand_sid = results[r_idx].payload.get("student_id")
                    if cand_sid and str(cand_sid) != str(student_id):
                        second_student_id = cand_sid
                        second_similarity = similarity_scores[r_idx]
                        break

            # Fallback to database student face embeddings if Qdrant returned no matches or below threshold
            if not best_match or highest_similarity < settings.RECOGNITION_MEDIUM_THRESHOLD:
                try:
                    import json
                    import time
                    from app.db.session import SessionLocal
                    from sqlalchemy import text

                    # Check or refresh in-memory cache (TTL: 60s)
                    now_t = time.time()
                    if (
                        not hasattr(StudentIdentifier, "_cached_db_embeddings")
                        or StudentIdentifier._cached_db_embeddings is None
                        or (now_t - getattr(StudentIdentifier, "_cached_db_embeddings_ts", 0.0) > 60.0)
                    ):
                        async with SessionLocal() as db_session:
                            db_res = await db_session.execute(text("SELECT student_id, embedding FROM student_face_embeddings"))
                            rows = db_res.fetchall()
                            cached_vectors = []
                            for sid, raw_emb in rows:
                                if not raw_emb:
                                    continue
                                db_vec = np.array(json.loads(raw_emb) if isinstance(raw_emb, str) else raw_emb, dtype=np.float32)
                                norm = np.linalg.norm(db_vec)
                                if norm > 0:
                                    db_vec = db_vec / norm
                                cached_vectors.append((sid, db_vec))
                            StudentIdentifier._cached_db_embeddings = cached_vectors
                            StudentIdentifier._cached_db_embeddings_ts = now_t

                    best_db_sim = 0.0
                    best_db_sid = None
                    second_db_sim = 0.0
                    second_db_sid = None
                    for sid, db_vec in StudentIdentifier._cached_db_embeddings:
                        sim = float(np.dot(embedding, db_vec))
                        if sim > best_db_sim:
                            if best_db_sid and str(best_db_sid) != str(sid):
                                second_db_sim = best_db_sim
                                second_db_sid = best_db_sid
                            best_db_sim = sim
                            best_db_sid = sid
                        elif sim > second_db_sim and (not best_db_sid or str(sid) != str(best_db_sid)):
                            second_db_sim = sim
                            second_db_sid = sid

                    if best_db_sid and best_db_sim > highest_similarity:
                        highest_similarity = best_db_sim
                        student_id = best_db_sid
                        second_similarity = second_db_sim
                        second_student_id = second_db_sid
                        print(f"[RECOGNITION FALLBACK] DB fallback matched student {student_id} with similarity {highest_similarity:.4f}")
                except Exception as dbe:
                    logger.warning(f"[RECOGNITION FALLBACK] DB query fallback error: {dbe}")

            print("========== MATCH ==========")
            print(f"Recognition threshold: {settings.RECOGNITION_MEDIUM_THRESHOLD}")
            print(f"Highest similarity: {highest_similarity:.4f}")
            
            if not student_id or highest_similarity < settings.RECOGNITION_MEDIUM_THRESHOLD:
                print("Accepted or rejected: Rejected")
                print(f"Reason: Highest similarity {highest_similarity:.4f} is below configured recognition threshold {settings.RECOGNITION_MEDIUM_THRESHOLD}")
                print()
                return None

            # Ambiguity Rejection: If two distinct enrolled students are within 0.05 of each other, reject
            if second_student_id and str(second_student_id) != str(student_id) and second_similarity >= settings.RECOGNITION_MEDIUM_THRESHOLD:
                if (highest_similarity - second_similarity) < 0.05:
                    print("Accepted or rejected: Rejected")
                    print(f"Reason: Ambiguous match between student {student_id} ({highest_similarity:.4f}) and {second_student_id} ({second_similarity:.4f})")
                    print()
                    return None
                
                
            confidence = "high" if highest_similarity >= settings.RECOGNITION_HIGH_THRESHOLD else "medium"
            print("Accepted or rejected: Accepted")
            print(f"Reason: Similarity score {highest_similarity:.4f} is above or equal to threshold {settings.RECOGNITION_MEDIUM_THRESHOLD}")
            print()
            return {
                "success": True,
                "student_id": uuid.UUID(str(student_id)),
                "similarity_score": highest_similarity,
                "confidence": confidence
            }
                
        except Exception as e:
            logger.error(f"[RECOGNITION AUDIT] Student face matching query failed: {str(e)}")
            return None
