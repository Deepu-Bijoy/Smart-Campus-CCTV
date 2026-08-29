import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.core.config import settings

logger = logging.getLogger(__name__)

class QdrantVectorStore:
    _in_memory_client = None

    def __init__(self):
        import os
        is_test = os.environ.get("TEST_DATABASE_URI") is not None
        if is_test:
            if QdrantVectorStore._in_memory_client is None:
                QdrantVectorStore._in_memory_client = QdrantClient(":memory:")
            self.client = QdrantVectorStore._in_memory_client
            logger.info("Initializing transient isolated memory-only QdrantClient for testing.")
        elif settings.QDRANT_IN_MEMORY:
            if QdrantVectorStore._in_memory_client is None:
                # To make QdrantClient shared and persistent across processes,
                # we specify path to store SQLite/Qdrant databases on disk
                db_path = os.path.join(settings.STORAGE_DIR, "qdrant_db")
                os.makedirs(db_path, exist_ok=True)
                QdrantVectorStore._in_memory_client = QdrantClient(path=db_path)
            self.client = QdrantVectorStore._in_memory_client
            logger.info("Initializing shared local persistent QdrantClient.")
        else:
            self.client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                api_key=settings.QDRANT_API_KEY if settings.QDRANT_API_KEY else None
            )
        self.collection_name = "cctv_embeddings"
        self.face_collection_name = "student_face_embeddings"
        self._ensure_collection_exists()

    def _ensure_collection_exists(self) -> None:
        try:
            collections = self.client.get_collections().collections
            
            # Ensure CCTV collection exists
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=512,  # CLIP ViT-B/32 output dimensionality
                        distance=models.Distance.COSINE
                    )
                )
                logger.info(f"Created Qdrant collection: {self.collection_name}")
                
            # Ensure Student Face collection exists
            face_exists = any(c.name == self.face_collection_name for c in collections)
            if not face_exists:
                self.client.create_collection(
                    collection_name=self.face_collection_name,
                    vectors_config=models.VectorParams(
                        size=512,  # ArcFace Buffalo_L output dimensionality
                        distance=models.Distance.COSINE
                    )
                )
                logger.info(f"Created Qdrant collection: {self.face_collection_name}")
        except Exception as e:
            logger.error(f"Error ensuring Qdrant collections exist: {str(e)}")

    def upsert_vectors(self, points: List[Dict[str, Any]]) -> None:
        """
        Inserts vectors and payloads into Qdrant.
        Each point in 'points' should contain:
        - 'id': UUID or string
        - 'vector': List[float] (512d)
        - 'payload': Dict containing:
            - track_id: string
            - video_id: string
            - timestamp: float
            - object_class: string
            - camera_id: string
            - crop_path: string
        """
        # Stage 8: Print details of upsert_vectors
        print(f"Stage 8: upsert_vectors() called")
        print(f"  Number of points received: {len(points)}")
        print(f"  Collection name: {self.collection_name}")
        client_type = type(self.client).__name__
        print(f"  Client type: {client_type}")
        print(f"  Memory or persistent: {'Persistent (path-based)' if settings.QDRANT_IN_MEMORY else 'Remote Server'}")

        qdrant_points = []
        for p in points:
            qdrant_points.append(
                models.PointStruct(
                    id=str(p["id"]),
                    vector=p["vector"],
                    payload=p["payload"]
                )
            )
            
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=qdrant_points
            )
            logger.info(f"Upserted {len(qdrant_points)} points to Qdrant.")
            
            # Immediately query count inside the same process
            count_res = self.client.count(
                collection_name=self.collection_name,
                exact=True
            )
            print(f"  Count inside upsert_vectors(): {count_res.count}")
        except Exception as e:
            print(f"  Exception in upsert_vectors: {str(e)}")
            import traceback
            traceback.print_exc()
            logger.error(f"Failed to upsert points to Qdrant: {str(e)}")
            raise e

    def _build_filter(
        self,
        video_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        track_id: Optional[str] = None,
        object_class: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> Optional[models.Filter]:
        must_conditions = []
        
        if video_id:
            must_conditions.append(
                models.FieldCondition(
                    key="video_id",
                    match=models.MatchValue(value=str(video_id))
                )
            )
        if camera_id:
            must_conditions.append(
                models.FieldCondition(
                    key="camera_id",
                    match=models.MatchValue(value=camera_id)
                )
            )
        if track_id:
            must_conditions.append(
                models.FieldCondition(
                    key="track_id",
                    match=models.MatchValue(value=str(track_id))
                )
            )
        if object_class:
            must_conditions.append(
                models.FieldCondition(
                    key="object_class",
                    match=models.MatchValue(value=object_class)
                )
            )
            
        if start_time is not None or end_time is not None:
            range_cond = {}
            if start_time is not None:
                range_cond["gte"] = start_time
            if end_time is not None:
                range_cond["lte"] = end_time
                
            must_conditions.append(
                models.FieldCondition(
                    key="timestamp",
                    range=models.Range(**range_cond)
                )
            )
            
        return models.Filter(must=must_conditions) if must_conditions else None

    def search_by_embedding(
        self,
        embedding: List[float],
        limit: int = 20,
        video_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        track_id: Optional[str] = None,
        object_class: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        qdrant_filter = self._build_filter(
            video_id=video_id,
            camera_id=camera_id,
            track_id=track_id,
            object_class=object_class,
            start_time=start_time,
            end_time=end_time
        )
        
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=embedding,
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True
            )
            
            formatted = []
            for res in response.points:
                formatted.append({
                    "id": res.id,
                    "score": res.score,
                    "payload": res.payload
                })
            return formatted
        except Exception as e:
            logger.error(f"Qdrant search failed: {str(e)}")
            return []

    def search_by_text(
        self,
        text_query: str,
        embedder: Any,
        limit: int = 20,
        video_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        object_class: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        embedding = embedder.get_text_embedding(text_query)
        if not embedding:
            return []
            
        return self.search_by_embedding(
            embedding=embedding,
            limit=limit,
            video_id=video_id,
            camera_id=camera_id,
            object_class=object_class,
            start_time=start_time,
            end_time=end_time
        )

    def upsert_face_embedding(
        self,
        embedding_id: Any,
        vector: List[float],
        payload: Dict[str, Any]
    ) -> None:
        try:
            import uuid
            self.client.upsert(
                collection_name=self.face_collection_name,
                points=[
                    models.PointStruct(
                        id=str(embedding_id),
                        vector=vector,
                        payload={k: str(v) if isinstance(v, uuid.UUID) else v for k, v in payload.items()}
                    )
                ]
            )
            logger.info(f"Upserted student face embedding {embedding_id} to Qdrant.")
        except Exception as e:
            logger.error(f"Failed to upsert student face embedding to Qdrant: {str(e)}")
            raise e

    def delete_face_embeddings_by_student(self, student_id: Any) -> None:
        """
        Delete all face embeddings associated with a student from Qdrant.
        """
        try:
            self.client.delete(
                collection_name=self.face_collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="student_id",
                                match=models.MatchValue(value=str(student_id))
                            )
                        ]
                    )
                )
            )
            logger.info(f"Deleted face embeddings in Qdrant for student {student_id}")
        except Exception as e:
            logger.error(f"Failed to delete Qdrant points for student {student_id}: {str(e)}")

    def delete_face_embedding_by_photo(self, photo_id: Any) -> None:
        """
        Delete specific face embedding associated with a photo from Qdrant.
        """
        try:
            self.client.delete(
                collection_name=self.face_collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="photo_id",
                                match=models.MatchValue(value=str(photo_id))
                            )
                        ]
                    )
                )
            )
            logger.info(f"Deleted face embedding in Qdrant for photo {photo_id}")
        except Exception as e:
            logger.error(f"Failed to delete Qdrant point for photo {photo_id}: {str(e)}")

    def delete_vectors_by_video_id(self, video_id: Any) -> None:
        """
        Delete all CCTV vectors associated with a video from Qdrant.
        """
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="video_id",
                                match=models.MatchValue(value=str(video_id))
                            )
                        ]
                    )
                )
            )
            logger.info(f"Deleted CCTV vectors in Qdrant for video {video_id}")
        except Exception as e:
            logger.error(f"Failed to delete Qdrant points for video {video_id}: {str(e)}")
            raise e

    def delete_face_embedding(self, student_id: Any) -> None:
        """
        Delete all face embeddings associated with a student from Qdrant.
        """
        self.delete_face_embeddings_by_student(student_id)

# Singleton instance
vector_store = QdrantVectorStore()
