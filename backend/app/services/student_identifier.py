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
            
            # Match decision logic
            highest_similarity = similarity_scores[0] if similarity_scores else 0.0
            best_match = results[0] if results else None
            student_id = best_match.payload.get("student_id") if best_match else None
            
            print("========== MATCH ==========")
            print(f"Recognition threshold: {settings.RECOGNITION_MEDIUM_THRESHOLD}")
            print(f"Highest similarity: {highest_similarity:.4f}")
            
            if not best_match:
                print("Accepted or rejected: Rejected")
                print("Reason: Qdrant returned no matches.")
                print()
                return None
                
            if highest_similarity >= settings.RECOGNITION_MEDIUM_THRESHOLD:
                confidence = "high" if highest_similarity >= settings.RECOGNITION_HIGH_THRESHOLD else "medium"
                print("Accepted or rejected: Accepted")
                print(f"Reason: Similarity score {highest_similarity:.4f} is above or equal to threshold {settings.RECOGNITION_MEDIUM_THRESHOLD}")
                print()
                return {
                    "success": True,
                    "student_id": uuid.UUID(student_id) if isinstance(student_id, str) else student_id,
                    "similarity_score": highest_similarity,
                    "confidence": confidence
                }
            else:
                print("Accepted or rejected: Rejected")
                print(f"Reason: Highest similarity {highest_similarity:.4f} is below configured recognition threshold {settings.RECOGNITION_MEDIUM_THRESHOLD}")
                print()
                return None
                
        except Exception as e:
            logger.error(f"[RECOGNITION AUDIT] Qdrant student face matching query failed: {str(e)}")
            return None
