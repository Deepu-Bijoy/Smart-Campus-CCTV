import uuid
import logging
import numpy as np
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api import deps
from app.models.user import User
from app.models.track import Track, PersonReid
from app.models.event import Event, EventTrack
from app.schemas.search import (
    SearchRequest,
    SearchResponse,
    ExplainResponse,
    SimilarRequest,
    SimilarResponse,
    EvidenceResponse
)
from app.services.hybrid_retrieval import HybridRetrievalEngine
from app.services.explanation_engine import ExplanationEngine

logger = logging.getLogger(__name__)
router = APIRouter()

def generate_explanation(query: str, res: dict, object_class: str) -> str:
    parts = []
    parts.append(f"Target classified as '{object_class}' matched search query '{query}'.")
    
    semantic = res.get("semantic_score", 0.0)
    if semantic > 0.0:
        parts.append(f"Matched appearance description with a semantic score of {semantic:.3f}.")
        
    identity = res.get("identity_score", 0.0)
    if identity > 0.0:
        parts.append(f"Visual identity matches target person prototype with similarity score of {identity:.3f}.")
        
    temporal = res.get("temporal_score", 1.0)
    if temporal < 1.0:
        parts.append(f"Aligned with temporal constraints with score of {temporal:.3f}.")
    elif temporal == 1.0 and res.get("temporal_score") is not None:
        parts.append("Matched temporal constraints perfectly (score 1.000).")
        
    metadata = res.get("metadata_score", 1.0)
    if metadata < 1.0:
        parts.append(f"Metadata filter match score of {metadata:.3f}.")
        
    parts.append(f"Aggregate hybrid score: {res.get('hybrid_score', 0.0):.3f}.")
    return " ".join(parts)

@router.post("", response_model=SearchResponse, status_code=status.HTTP_200_OK)
async def search_videos(
    request: SearchRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Search indexed video assets using a natural language query and optional metadata filters.
    """
    logger.info(f"User {current_user.id} running hybrid search: '{request.query}'")
    engine = HybridRetrievalEngine(db)
    
    try:
        results = await engine.search(
            query=request.query,
            video_id=str(request.video_id) if request.video_id else None,
            camera_id=request.camera_id,
            start_time=request.start_time,
            end_time=request.end_time,
            top_k=request.top_k
        )
        return {"results": results}
    except Exception as e:
        logger.error(f"Search query failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute search query: {str(e)}"
        )

from typing import Optional

@router.get("/explain", response_model=ExplainResponse, status_code=status.HTTP_200_OK)
async def search_explain_get(
    query: str,
    video_id: Optional[uuid.UUID] = None,
    camera_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    top_k: int = 20,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Search indexed video assets and return detailed scoring explanations for every result candidate (GET).
    """
    req = SearchRequest(
        query=query,
        video_id=video_id,
        camera_id=camera_id,
        start_time=start_time,
        end_time=end_time,
        top_k=top_k
    )
    return await search_explain(req, db, current_user)

@router.post("/explain", response_model=ExplainResponse, status_code=status.HTTP_200_OK)
async def search_explain(
    request: SearchRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Search indexed video assets and return detailed scoring explanations for every result candidate.
    """
    logger.info(f"User {current_user.id} running explain search: '{request.query}'")
    engine = HybridRetrievalEngine(db)
    
    try:
        results = await engine.search(
            query=request.query,
            video_id=str(request.video_id) if request.video_id else None,
            camera_id=request.camera_id,
            start_time=request.start_time,
            end_time=request.end_time,
            top_k=request.top_k
        )
        
        if not results:
            return {"results": []}
            
        parsed_query = engine.parser.parse(request.query)
        target_class = parsed_query["object_class"] or "unknown"
        weights = engine.ranker.determine_weights(parsed_query["intent"], target_class)
        
        explain_results = []
        for r in results:
            exp_data = await ExplanationEngine.explain_result(
                db=db,
                track_id=r["track_id"],
                semantic_score=r["semantic_score"],
                appearance_score=r["identity_score"],
                temporal_score=r["temporal_score"],
                metadata_score=r["metadata_score"],
                weights=weights
            )
            
            explanation = f"Matched because: " + " ".join(exp_data["reasons"])
            explain_results.append({
                "track_id": r["track_id"],
                "video_id": r["video_id"],
                "camera_id": r["camera_id"],
                "timestamp": r["timestamp"],
                "confidence": r["confidence"],
                "hybrid_score": exp_data["final_hybrid_score"],
                "scores": {
                    "semantic": exp_data["semantic_score"],
                    "identity": exp_data["identity_score"],
                    "appearance": exp_data["appearance_score"],
                    "temporal": exp_data["temporal_score"],
                    "zone": exp_data["zone_score"],
                    "metadata": r["metadata_score"]
                },
                "explanation": explanation,
                "reasons": exp_data["reasons"],
                "explain_confidence": exp_data["confidence"]
            })
            
        explain_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return {"results": explain_results}
    except Exception as e:
        logger.error(f"Explain query failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute explain query: {str(e)}"
        )

@router.get("/evidence/{track_id}", response_model=EvidenceResponse, status_code=status.HTTP_200_OK)
async def get_evidence(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve evidence records and confidence rankings linked to a track.
    """
    logger.info(f"Retrieving evidence logs for track: {track_id}")
    
    stmt = (
        select(Event)
        .join(EventTrack, Event.id == EventTrack.event_id)
        .filter(EventTrack.track_id == track_id)
    )
    res = await db.execute(stmt)
    events = res.scalars().all()
    
    results = []
    for ev in events:
        reasons = [
            f"• Crossed Virtual Zone boundary on camera {ev.camera_id}",
            f"• Confirmed event type category: {ev.event_type}"
        ]
        if ev.student_id:
            reasons.append("• Visual match resolved to verified student database profile")
            
        score = 0.90 if ev.confidence == "high" else 0.70
        
        results.append({
            "track_id": track_id,
            "event_id": ev.id,
            "event_type": ev.event_type,
            "confidence": ev.confidence,
            "score": score,
            "reasons": reasons
        })
        
    if not results:
        results.append({
            "track_id": track_id,
            "event_id": None,
            "event_type": None,
            "confidence": "medium",
            "score": 0.50,
            "reasons": ["• Indexed raw CCTV tracking signature log without border trespass events"]
        })
        
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": results}

@router.post("/similar", response_model=SimilarResponse, status_code=status.HTTP_200_OK)
async def search_similar(
    request: SimilarRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve visually similar trajectories (tracks) using visual Re-ID features of the source track.
    """
    logger.info(f"User {current_user.id} fetching tracks similar to track: {request.track_id}")
    
    # 1. Fetch source track and verify existence
    stmt = select(Track).filter(Track.id == request.track_id)
    track_res = await db.execute(stmt)
    source_track = track_res.scalars().first()
    if not source_track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source track with ID {request.track_id} not found."
        )
        
    # 2. Fetch Re-ID vectors for source track
    stmt = select(PersonReid.embedding).filter(PersonReid.track_id == request.track_id)
    reid_res = await db.execute(stmt)
    source_embeddings = reid_res.scalars().all()
    
    if not source_embeddings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Source track {request.track_id} does not contain any visual Re-ID signatures. "
                "Similarity matching is only supported for tracked 'person' objects."
            )
        )
        
    # 3. Calculate query signature (mean of normalized vectors, re-normalized)
    prototype_vectors = [np.array(emb) for emb in source_embeddings]
    avg_vec = np.mean(prototype_vectors, axis=0)
    query_vector = avg_vec / np.linalg.norm(avg_vec)
    
    # 4. Fetch other Re-ID vectors (excluding target track ID)
    stmt = select(PersonReid).filter(PersonReid.track_id != request.track_id)
    all_reids_res = await db.execute(stmt)
    all_reids = all_reids_res.scalars().all()
    
    if not all_reids:
        return {"results": []}
        
    # 5. Compute cosine similarities (dot product) and group by track_id, taking maximum similarity
    similarities = {}
    for r in all_reids:
        target_vector = np.array(r.embedding)
        similarity = float(np.dot(query_vector, target_vector))
        
        # Take the maximum similarity score per track
        if r.track_id not in similarities or similarity > similarities[r.track_id]["similarity"]:
            similarities[r.track_id] = {
                "video_id": r.video_id,
                "similarity": similarity
            }
            
    if not similarities:
        return {"results": []}
        
    # 6. Fetch metadata for matching tracks
    matched_track_ids = list(similarities.keys())
    stmt = select(Track).filter(Track.id.in_(matched_track_ids))
    matched_tracks_res = await db.execute(stmt)
    matched_tracks = matched_tracks_res.scalars().all()
    
    # 7. Map to response structure
    results = []
    for t in matched_tracks:
        sim_data = similarities[t.id]
        results.append({
            "track_id": t.id,
            "video_id": sim_data["video_id"],
            "object_class": t.object_class,
            "similarity_score": sim_data["similarity"],
            "start_time": t.start_time,
            "end_time": t.end_time
        })
        
    # 8. Sort and limit
    results.sort(key=lambda x: x["similarity_score"], reverse=True)
    return {"results": results[:request.top_k]}
