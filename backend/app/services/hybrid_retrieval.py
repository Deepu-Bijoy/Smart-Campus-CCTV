import uuid
import logging
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.services.query_parser import QueryParser
from app.services.ranking import HybridRanker
from app.services.vector_store import QdrantVectorStore
from app.pipeline.embedder import CLIPEmbedder
from app.models.video import Video
from app.models.track import PersonReid

logger = logging.getLogger(__name__)

class HybridRetrievalEngine:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.parser = QueryParser()
        self.ranker = HybridRanker()
        self.vector_store = QdrantVectorStore()
        self.embedder = CLIPEmbedder()

    async def search(
        self,
        query: str,
        video_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        min_confidence: float = 0.4,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Executes the Adaptive Hybrid Retrieval search across Qdrant and PostgreSQL.
        """
        logger.info(f"Hybrid retrieval search started. Query: '{query}'")
        
        parsed_query = self.parser.parse(query)
        target_class = parsed_query["object_class"]
        intent = parsed_query["intent"]
        
        semantic_matches = self.vector_store.search_by_text(
            text_query=query,
            embedder=self.embedder,
            limit=100,
            video_id=video_id,
            camera_id=camera_id,
            object_class=target_class,
            start_time=start_time,
            end_time=end_time
        )
        
        if not semantic_matches:
            logger.info("No semantic matches returned from Qdrant.")
            return []
            
        video_ids = list(set(res["payload"]["video_id"] for res in semantic_matches))
        video_start_times = {}
        for v_id in video_ids:
            res = await self.db.execute(select(Video).filter(Video.id == uuid.UUID(v_id)))
            v_obj = res.scalars().first()
            if v_obj:
                video_start_times[v_id] = v_obj.created_at
                
        reid_prototype = None
        if target_class == "person" and len(semantic_matches) > 0:
            top_person_points = [
                res for res in semantic_matches 
                if res["payload"]["object_class"] == "person"
            ][:3]
            
            prototype_vectors = []
            for p in top_person_points:
                t_id = p["payload"]["track_id"]
                stmt = select(PersonReid.embedding).filter(
                    PersonReid.track_id == uuid.UUID(t_id),
                    PersonReid.timestamp_seconds == p["payload"]["timestamp"]
                )
                r_res = await self.db.execute(stmt)
                emb = r_res.scalars().first()
                if emb:
                    prototype_vectors.append(np.array(emb))
                    
            if prototype_vectors:
                avg_vec = np.mean(prototype_vectors, axis=0)
                reid_prototype = avg_vec / np.linalg.norm(avg_vec)
                logger.info("Generated OSNet visual Re-ID prototype for person retrieval query.")

        weights = self.ranker.determine_weights(intent, target_class or "unknown")
        
        ranked_results = []
        for match in semantic_matches:
            payload = match["payload"]
            score_semantic = match["score"]
            
            conf = payload.get("confidence", 1.0)
            if conf < min_confidence:
                continue
                
            track_uuid = uuid.UUID(payload["track_id"])
            vid_id_str = payload["video_id"]
            
            score_temporal = 1.0
            if parsed_query["temporal_constraints"] and vid_id_str in video_start_times:
                score_temporal = self.ranker.calculate_temporal_score(
                    event_time_offset=payload["timestamp"],
                    video_start_time=video_start_times[vid_id_str],
                    constraint=parsed_query["temporal_constraints"]
                )
                
            filter_args = {
                "camera_id": camera_id,
                "object_class": target_class
            }
            score_metadata = self.ranker.calculate_metadata_score(payload, filter_args)
            
            score_identity = 0.0
            if target_class == "person" and reid_prototype is not None:
                stmt = select(PersonReid.embedding).filter(PersonReid.track_id == track_uuid)
                r_res = await self.db.execute(stmt)
                track_embeddings = r_res.scalars().all()
                
                if track_embeddings:
                    similarities = []
                    for emb in track_embeddings:
                        emb_arr = np.array(emb)
                        sim = np.dot(emb_arr, reid_prototype)
                        similarities.append(sim)
                    score_identity = float(max(similarities))
            
            hybrid_score = (
                weights["semantic"] * score_semantic +
                weights["identity"] * score_identity +
                weights["temporal"] * score_temporal +
                weights["metadata"] * score_metadata
            )
            
            ranked_results.append({
                "track_id": track_uuid,
                "video_id": uuid.UUID(vid_id_str),
                "camera_id": payload.get("camera_id", "cam_1"),
                "timestamp": payload["timestamp"],
                "confidence": conf,
                "hybrid_score": hybrid_score,
                "semantic_score": float(score_semantic),
                "identity_score": float(score_identity),
                "temporal_score": float(score_temporal),
                "metadata_score": float(score_metadata)
            })

        ranked_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        top_results = ranked_results[:top_k]
        
        logger.info(f"Hybrid search finished. Returned {len(top_results)} ranked candidates.")
        return top_results
