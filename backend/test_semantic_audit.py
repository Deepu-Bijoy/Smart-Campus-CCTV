import sys
import os
import asyncio
import uuid
import numpy as np
from datetime import datetime

# Add backend to path
sys.path.append(r"c:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System\backend")

# Import all SQLAlchemy models to register them
from app.models.user import User
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.video import Video
from app.models.track import Track, Detection, PersonReid
from app.models.recognition import StudentRecognitionEvent
from app.models.event import Event, EventTrack
from app.models.camera import Camera, CameraCalibration, VirtualZone

from app.db.session import SessionLocal
from app.pipeline.frame_processor import FrameProcessor
from app.services.vector_store import QdrantVectorStore
from app.services.hybrid_retrieval import HybridRetrievalEngine

async def audit_semantic_search():
    print("====================================================")
    print("STEP 1: Starting End-to-End Semantic Search Pipeline Audit")
    print("====================================================")
    
    video_id_str = "128b5fef-1e98-4555-9c56-57cb85707ffc"
    video_uuid = uuid.UUID(video_id_str)
    video_path = r"storage/128b5fef-1e98-4555-9c56-57cb85707ffc.mp4"
    
    # Check if file exists
    if not os.path.exists(video_path):
        print(f"Error: Video file {video_path} not found!")
        return

    # Initialize components
    vector_store = QdrantVectorStore()
    
    print("\n--- Cleaning up existing database records for this video ---")
    async with SessionLocal() as db:
        # Delete old detections, person_reids, tracks, and videos
        from sqlalchemy import text
        await db.execute(text("DELETE FROM detections WHERE track_id IN (SELECT id FROM tracks WHERE video_id = :vid)"), {"vid": video_uuid.hex})
        await db.execute(text("DELETE FROM person_reids WHERE video_id = :vid"), {"vid": video_uuid.hex})
        await db.execute(text("DELETE FROM student_recognition_events WHERE video_id = :vid"), {"vid": video_uuid.hex})
        await db.execute(text("DELETE FROM tracks WHERE video_id = :vid"), {"vid": video_uuid.hex})
        await db.execute(text("DELETE FROM videos WHERE id = :vid"), {"vid": video_uuid.hex})
        
        # Add new video record
        video_obj = Video(
            id=video_uuid,
            title="Audit Video 128b5fef",
            filename="128b5fef-1e98-4555-9c56-57cb85707ffc.mp4",
            original_filename="128b5fef-1e98-4555-9c56-57cb85707ffc.mp4",
            file_path=video_path,
            status="processing",
            current_stage="Audit Indexing",
            progress_percentage=0,
            uploaded_by=uuid.UUID('0e4e750b-8a98-4337-87db-7c323d1d1c63')
        )
        db.add(video_obj)
        await db.commit()
        print("Cleared previous data and registered clean video record in database.")

    # STEP 4: Verify Indexing (run FrameProcessor and log details)
    print("\n====================================================")
    print("STEP 4: Run Indexing and Log Detections & CLIP Embeddings")
    print("====================================================")
    
    processor = FrameProcessor(video_uuid, video_path, target_fps=5.0)
    
    # Run frame processing synchronously in executor
    loop = asyncio.get_event_loop()
    print("Running YOLO detection, ByteTrack tracking, and embedding extraction...")
    tracks_list, detections_list, reids_list, clips_list, frames_processed = await loop.run_in_executor(None, processor.process)
    
    print(f"Frames processed: {frames_processed}")
    print(f"Tracks extracted: {len(tracks_list)}")
    print(f"CLIP crops queue count: {len(clips_list)}")

    async with SessionLocal() as db:
        # Save tracks and detections in database
        temp_id_map = {}
        for track_data in tracks_list:
            track_uuid = uuid.uuid4()
            track_obj = Track(
                id=track_uuid,
                video_id=video_uuid,
                object_class=track_data["object_class"],
                tracker_id=track_data["tracker_id"],
                start_time=track_data["start_time"],
                end_time=track_data["end_time"]
            )
            db.add(track_obj)
            temp_id_map[track_data["temp_id"]] = track_uuid
            
        for det_data in detections_list:
            mapped_track_id = temp_id_map.get(det_data["track_temp_id"])
            if not mapped_track_id:
                continue
            det_obj = Detection(
                id=uuid.uuid4(),
                track_id=mapped_track_id,
                frame_number=det_data["frame_number"],
                timestamp_seconds=det_data["timestamp_seconds"],
                bounding_box=det_data["bounding_box"],
                confidence=det_data["confidence"]
            )
            db.add(det_obj)
            
        for reid_data in reids_list:
            mapped_track_id = temp_id_map.get(reid_data["track_temp_id"])
            if not mapped_track_id:
                continue
            reid_obj = PersonReid(
                id=uuid.uuid4(),
                track_id=mapped_track_id,
                video_id=video_uuid,
                embedding=reid_data["embedding"],
                timestamp_seconds=reid_data["timestamp_seconds"],
                crop_path=reid_data["crop_path"],
                camera_id=reid_data["camera_id"]
            )
            db.add(reid_obj)

        await db.commit()

    print("\nPersisting CLIP embeddings to Qdrant...")
    qdrant_points = []
    for clip_data in clips_list:
        mapped_track_id = temp_id_map.get(clip_data["track_temp_id"])
        if not mapped_track_id:
            continue
            
        point_id = uuid.uuid4()
        payload = {
            "track_id": str(mapped_track_id),
            "video_id": str(video_uuid),
            "timestamp": float(clip_data["timestamp_seconds"]),
            "object_class": clip_data["object_class"],
            "camera_id": clip_data["camera_id"],
            "crop_path": clip_data["crop_path"]
        }
        
        qdrant_points.append({
            "id": point_id,
            "vector": clip_data["embedding"],
            "payload": payload
        })
        
        # Extract frame number from path
        try:
            frame_num = os.path.basename(clip_data["crop_path"]).split('_')[-2]
        except Exception:
            frame_num = "unknown"
            
        print(f"Indexing Point: Frame {frame_num} | Track UUID: {mapped_track_id} | Embedding length: {len(clip_data['embedding'])} | Vector Preview: {clip_data['embedding'][:4]}")

    if qdrant_points:
        vector_store.upsert_vectors(qdrant_points)
        print(f"--> Successfully upserted {len(qdrant_points)} vectors to Qdrant collection '{vector_store.collection_name}'!")
    else:
        print("--> No Qdrant points generated for indexing!")

    # STEP 3: Verify Qdrant
    print("\n====================================================")
    print("STEP 3: Verify Qdrant Collections and Contents")
    print("====================================================")
    
    collections = vector_store.client.get_collections().collections
    print(f"Active Qdrant Collections: {[c.name for c in collections]}")
    
    for coll in collections:
        c_info = vector_store.client.get_collection(coll.name)
        print(f"\nCollection Name: {coll.name}")
        print(f"Vector Dimension: {c_info.config.params.vectors.size}")
        print(f"Distance Metric: {c_info.config.params.vectors.distance}")
        print(f"Number of vectors stored: {c_info.points_count}")
        
        # Retrieve first point payload
        response = vector_store.client.scroll(
            collection_name=coll.name,
            limit=1,
            with_payload=True,
            with_vectors=True
        )
        if response[0]:
            first_pt = response[0][0]
            print(f"First Point ID: {first_pt.id}")
            print(f"First Payload: {first_pt.payload}")
            print(f"First Vector preview: {first_pt.vector[:5]}... (dimension {len(first_pt.vector)})")
        else:
            print("No vectors stored in this collection yet.")

    # Retrieve payloads from database and vector stores to list IDs
    print("\nDistinct IDs stored in Database & Qdrant:")
    async with SessionLocal() as db:
        from sqlalchemy import text
        res = await db.execute(text("SELECT DISTINCT identified_student_id FROM tracks WHERE identified_student_id IS NOT NULL"))
        student_ids = [r[0] for r in res.all()]
        res = await db.execute(text("SELECT DISTINCT id FROM videos"))
        video_ids = [str(r[0]) for r in res.all()]
        res = await db.execute(text("SELECT DISTINCT id FROM tracks"))
        track_ids = [str(r[0]) for r in res.all()]
        
        print(f"- Student IDs in Database: {student_ids}")
        print(f"- Video IDs in Database: {video_ids}")
        print(f"- Track IDs in Database: {track_ids[:5]} (showing up to 5)")

    # STEP 5 & 6 & 7: Verify Search and Hybrid Ranking on Test Queries
    print("\n====================================================")
    print("STEPS 5, 6, 7: Execute Test Queries and Verify Scoring")
    print("====================================================")
    
    test_queries = [
        "person",
        "person in black shirt",
        "student",
        "Deepu",
        "Dipz",
        "person near gate"
    ]
    
    async with SessionLocal() as db:
        from sqlalchemy import text
        engine = HybridRetrievalEngine(db)
        for q in test_queries:
            print("\n----------------------------------------------------")
            print(f"Query: '{q}'")
            print("----------------------------------------------------")
            
            # Step 5: Verify text embedding generation
            text_emb = engine.embedder.get_text_embedding(q)
            import numpy as np
            emb_norm = np.linalg.norm(text_emb) if text_emb else 0.0
            print(f"Parsed Query: {engine.parser.parse(q)}")
            print(f"Generated text embedding dimension: {len(text_emb) if text_emb else 0}")
            print(f"Embedding vector preview: {text_emb[:5] if text_emb else []}")
            print(f"Embedding L2 Norm: {emb_norm}")
            
            # Run the search
            results = await engine.search(query=q, top_k=10)
            print(f"Total search matches returned: {len(results)}")
            
            if not results:
                print("No matches returned from search engine.")
                continue
                
            # Step 6: Verify hybrid ranking details
            print("\nTop Results Breakdown:")
            for idx, r in enumerate(results):
                print(f"\nRank {idx+1}: Track ID: {r['track_id']}")
                print(f"  Hybrid Score: {r['hybrid_score']:.4f}")
                print(f"  Scoring Components:")
                # Query face identity score from recognition events
                rec_res = await db.execute(text("SELECT similarity_score FROM student_recognition_events WHERE track_id = :tid ORDER BY similarity_score DESC"), {"tid": str(r["track_id"])})
                rec_row = rec_res.first()
                face_score = float(rec_row[0]) if rec_row else 0.0
                
                print(f"    - Semantic (CLIP) Score: {r['semantic_score']:.4f}")
                print(f"    - Face Identity Score: {face_score:.4f}")
                print(f"    - Appearance (Re-ID) Score: {r['identity_score']:.4f}")
                print(f"    - Temporal Score: {r['temporal_score']:.4f}")
                print(f"    - Metadata Score: {r['metadata_score']:.4f}")
                
                # Fetch payload info from database
                res = await db.execute(text("SELECT object_class, start_time, end_time FROM tracks WHERE id = :tid"), {"tid": str(r["track_id"])})
                track_row = res.first()
                if track_row:
                    print(f"  Track Info: Class={track_row[0]}, Duration={track_row[1]:.2f}s to {track_row[2]:.2f}s")
                    
    print("\n====================================================")
    print("Audit Complete!")
    print("====================================================")

if __name__ == "__main__":
    asyncio.run(audit_semantic_search())
