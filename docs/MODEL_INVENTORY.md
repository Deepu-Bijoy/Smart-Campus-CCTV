# MODEL INVENTORY & SPECIFICATION REGISTRY (CORRECTED)

**Project:** AI-Powered Smart CCTV Investigation System  
**Hardware Platform:** NVIDIA GeForce RTX 3050 Laptop GPU (4.0 GB VRAM), CUDA 12.4  
**Software Platform:** Python 3.11.15, PyTorch 2.6.0+cu124, ONNX Runtime 1.21.0 (CUDA Provider)  
**Audit Phase:** Phase 2A — AI/ML Benchmark Methodology Correction  

---

## 1. Complete Model & Component Inventory

| Model / Component | Framework / Source | Active Weight Location | Active Weight Checksum (SHA-256) | Input Format & Dimension | Output Dimension & Representation | Execution Engine | Runtime Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| **YOLOv8n** | Ultralytics / PyTorch | `backend/yolov8n.pt` (6.55 MB) | `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36` | `(3, 640, 640)` BGR uint8 | $N \times 6$ `[x1, y1, x2, y2, conf, class]` | PyTorch (CUDA:0) | **VERIFIED** |
| **ByteTrack** | ByteTrack / Custom | `app/pipeline/bytetrack_custom.yaml` | `971c22144b2f15e8be6dfc5625bf9921473216c52a0a38e8ec4e1f8680e611fc` | Frame + YOLO Detections | $M \times 5$ `[x1, y1, x2, y2, tracker_id]` | Python / Kalman (CPU) | **VERIFIED** |
| **SCRFD (Det 10G)** | InsightFace / ONNX | `backend/storage/models/insightface/models/buffalo_l/det_10g.onnx` (16.92 MB) | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` | `(3, 640, 640)` BGR uint8 | 5 facial landmarks, Bounding boxes, Score | ONNX Runtime (CUDA) | **VERIFIED** |
| **ArcFace (w600k_r50)** | InsightFace / ONNX | `backend/storage/models/insightface/models/buffalo_l/w600k_r50.onnx` (174.38 MB) | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` | `(3, 112, 112)` Aligned crop | $1 \times 512$ L2-normalized float32 embedding | ONNX Runtime (CUDA) | **VERIFIED** |
| **OSNet (`osnet_x1_0`)** | Torchreid / PyTorch | Model Zoo (`osnet_x1_0`, ~8.8 MB) | Dynamically loaded via `torchreid` | `(3, 256, 128)` RGB uint8 | $1 \times 512$ L2-normalized float32 embedding | PyTorch (CUDA:0) | **BLOCKED** |
| **CLIP ViT-B/32** | OpenAI / HuggingFace | `~/.cache/huggingface/hub/.../model.safetensors` (577.12 MB)<br>*(Note: `weights/clip/ViT-B-32.pt` is unreferenced)* | HuggingFace revision `3d74acf9a28c` | Visual: `(3, 224, 224)`<br>Text: 77 tokens | $1 \times 512$ L2-normalized float32 embedding | PyTorch (CUDA:0) | **VERIFIED** |
| **FightDetector** | Custom Event Engine | `app/event_engine/event_engine.py:29` | In-code mathematical heuristics | Tracks + Timestamps + CLIP Score | Scalar altercation score $[0, 1]$ + breakdown | Python Math (CPU) | **VERIFIED** |
| **X3D-M** | PyTorchVideo / PyTorch | `backend/storage/models/x3d/final_x3d_realtime.pt` (12.27 MB) | `e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349` | `(3, 16, 224, 224)` 16-frame clip | Binary logit / Softmax probability $[0, 1]$ | PyTorchVideo (CUDA:0) | **BLOCKED** |

---

## 2. Weight Provenance Resolution (CLIP)

- **Local Weight File:** `weights/clip/ViT-B-32.pt` (353.98 MB, SHA-256 `40d365715913c9da...`).
- **Code Inspection:** Verified that `backend/app/core/model_manager.py:84` and `backend/app/pipeline/embedder.py:13` call `CLIPModel.from_pretrained("openai/clip-vit-base-patch32")`.
- **Finding:** The local file in `weights/clip/` is **never loaded** by the backend. The executed weights are the Hugging Face `model.safetensors` file cached in the user's home directory.

---

## 3. Genuine Co-Resident VRAM Breakdown

Measured with all active models instantiated simultaneously in memory on `cuda:0`:

- **YOLOv8n + InsightFace + CLIP Co-Resident PyTorch Allocated:** **622.10 MB**
- **PyTorch Reserved Memory Pool:** **678.00 MB**
- **ONNX Runtime CUDA Note:** InsightFace executes via ONNX Runtime's internal CUDA allocator; PyTorch reports 12.13 MB for tensor bridges, while ORT manages its internal execution memory outside PyTorch.
- **Total Physical GPU Headroom:** **3,418.00 MB (83.4%)** remaining on the 4.0 GB RTX 3050.
