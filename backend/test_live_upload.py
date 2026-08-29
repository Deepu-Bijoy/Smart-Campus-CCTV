import requests
import time
import os
import uuid

BACKEND_URL = "http://127.0.0.1:8000"

def test_e2e_live_upload():
    # 1. Signup / Login to get access token
    email = f"operator_{uuid.uuid4().hex[:6]}@smartcampus.com"
    password = "password123"
    fullname = "CCTV Operator"
    
    print(f"Signing up new operator: {email}...")
    signup_res = requests.post(f"{BACKEND_URL}/api/v1/auth/signup", json={
        "email": email,
        "password": password,
        "full_name": fullname,
        "is_active": True
    })
    
    if signup_res.status_code == 201:
        print("Signup successful.")
    else:
        print(f"Signup returned status {signup_res.status_code}: {signup_res.text}")
        
    print("Logging in...")
    login_res = requests.post(f"{BACKEND_URL}/api/v1/auth/login", data={
        "username": email,
        "password": password
    })
    if login_res.status_code != 200:
        print(f"Login failed: {login_res.text}")
        return
        
    token_data = login_res.json()
    token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("Login successful. Token obtained.")

    # Get Qdrant count BEFORE upload
    # Wait, we can get this from a database/qdrant query directly or we can get count via python Qdrant client
    from qdrant_client import QdrantClient
    # Check settings or default values for Qdrant client
    # Since QDRANT_IN_MEMORY=True on the server, we cannot access uvicorn's in-memory Qdrant database directly.
    # But wait! Does the backend have a health check or other way?
    # No, but wait, the client count query in the task says:
    # "Immediately after insertion execute: client.count(collection_name='cctv_embeddings', exact=True)"
    # That client count check is executed INSIDE the backend uvicorn process itself!
    # Because we added Stage 9 prints inside `orchestrator.py`, the live count will be printed in the uvicorn logs.
    # We can inspect the logs of uvicorn command!
    
    # 2. Upload video
    video_file = r"storage/128b5fef-1e98-4555-9c56-57cb85707ffc.mp4"
    if not os.path.exists(video_file):
        print(f"Video file not found: {video_file}")
        return
        
    print(f"Uploading video {video_file} to backend...")
    with open(video_file, "rb") as f:
        files = {"file": (os.path.basename(video_file), f, "video/mp4")}
        upload_res = requests.post(f"{BACKEND_URL}/api/v1/videos/upload", headers=headers, files=files)
        
    if upload_res.status_code != 201:
        print(f"Upload failed: {upload_res.text}")
        return
        
    video_data = upload_res.json()
    video_id = video_data["id"]
    print(f"Video uploaded successfully. Video ID: {video_id}")
    
    # 3. Poll status
    print("Waiting for video processing to complete...")
    for _ in range(60):
        status_res = requests.get(f"{BACKEND_URL}/api/v1/videos/{video_id}/status", headers=headers)
        if status_res.status_code != 200:
            print(f"Failed to check status: {status_res.text}")
            break
        status_data = status_res.json()
        print(f"Current stage: {status_data['stage']} | Progress: {status_data['progress']}% | Status: {status_data['status']}")
        if status_data["status"] in ["completed", "failed"]:
            break
        time.sleep(3)
        
    # 4. Perform searches
    print("\nRunning search explain queries...")
    queries = ["person", "person in black shirt", "person near gate", "student"]
    for q in queries:
        print(f"\nSearching for: '{q}'")
        search_res = requests.post(f"{BACKEND_URL}/api/v1/search/explain", headers=headers, json={
            "query": q,
            "top_k": 5
        })
        if search_res.status_code == 200:
            res_data = search_res.json()
            print(f"Found {len(res_data['results'])} matches.")
            for idx, r in enumerate(res_data['results']):
                print(f"Match {idx+1}: Track ID: {r['track_id']} | Hybrid Score: {r['hybrid_score']:.4f}")
                print(f"  Confidence: {r['explain_confidence']} | Explanations: {r['explanation']}")
        else:
            print(f"Search failed for '{q}': {search_res.text}")

if __name__ == "__main__":
    test_e2e_live_upload()
