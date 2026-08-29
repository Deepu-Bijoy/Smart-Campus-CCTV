# AI Model Configuration & Setup Guide

The system uses four distinct deep learning architectures to process CCTV feeds, track subjects, extract semantic embeddings, and identify faces. 

Here is the setup, download details, caching directories, and GPU configurations for each model.

---

## 1. Summary of Model Configurations

| Model | Architecture / Backbone | Framework | Default Weight File / ID | Auto-Downloader Library | Cache Destination |
|---|---|---|---|---|---|
| **Object Detection** | YOLOv8 (Nano) | PyTorch / Ultralytics | `yolov8n.pt` | `ultralytics` | `backend/yolov8n.pt` (or current CWD) |
| **Semantic Embeddings** | CLIP (ViT-B/32) | PyTorch / Transformers | `openai/clip-vit-base-patch32` | `huggingface_hub` | `~/.cache/huggingface/hub` |
| **Person Re-ID** | OSNet | PyTorch / Torchreid | `osnet_x1_0` | `torchreid` | `~/.cache/torch/hub/checkpoints/osnet_x1_0_imagenet.pth` |
| **Face Recognition** | ArcFace | ONNX / InsightFace | `buffalo_l` | `insightface` | `backend/storage/models/insightface/models/buffalo_l/` |

---

## 2. Detailed Model Setup

### A. YOLOv8 (Person Detection)
- **Purpose**: Detects bounding boxes for persons, vehicles, bags, and items.
- **Initialization**: Handled in `app/pipeline/detector.py`.
- **Weight Setup**: The default model is `yolov8n.pt` (YOLOv8 Nano). When `YOLO("yolov8n.pt")` is executed, the library checks the current working directory (`backend/`) for the file. If missing, Ultralytics downloads it directly from `https://github.com/ultralytics/assets/releases`.
- **Action**: A copy of `yolov8n.pt` is located in the `backend/` folder of this project.

### B. CLIP (Semantic Video Search)
- **Purpose**: Creates multimodal embeddings of visual crops to support natural-language querying.
- **Initialization**: Handled in `app/pipeline/embedder.py`.
- **Weight Setup**: Hugging Face's `transformers` library loads `openai/clip-vit-base-patch32` and downloads config, tokenizer, and weight tensor files.
- **Caching Location**: Cached under `C:\Users\<username>\.cache\huggingface\hub\models--openai--clip-vit-base-patch32`.

### C. OSNet (Person Re-Identification)
- **Purpose**: Extracts appearance feature vectors from person crops to compute similarity across disjoint camera fields.
- **Initialization**: Handled in `app/pipeline/reid.py`.
- **Weight Setup**: `torchreid` downloads `osnet_x1_0` weights from its model zoo link during first execution of `FeatureExtractor(model_name="osnet_x1_0")`.
- **Caching Location**: Cached under `C:\Users\<username>\.cache\torch\hub\checkpoints\osnet_x1_0_imagenet_256x128_amsgrad_ep150_stp80_lr0.0015_temp_cool_people.pth`.

### D. InsightFace / ArcFace (Student Identification)
- **Purpose**: Identifies faces extracted from tracked person trajectories against the enrolled student face vector registry.
- **Initialization**: Handled in `app/core/model_manager.py` (root set to `storage/models/insightface`).
- **Weight Setup**: If face model is not present, `insightface` downloads the `buffalo_l.zip` package containing detection (SCRFD) and recognition (ArcFace) ONNX files, and extracts them into the model root.
- **Model Path**: `backend/storage/models/insightface/models/buffalo_l/`.
- **Weight Verification**: Check that `det_10g.onnx`, `w600k_r50.onnx`, and `genderage.onnx` are located under this subfolder.

---

## 3. GPU vs. CPU Execution

### CUDA Acceleration (Highly Recommended)
All models check `torch.cuda.is_available()` at startup:
- If `True`, the models load tensors into GPU memory (`cuda`), converting weight networks to FP16 half-precision for maximum throughput.
- Face detector and recognizer bindings require the GPU-compiled version of ONNX Runtime (`onnxruntime-gpu`) to run detection models on CUDA.

### CPU Fallback
- If CUDA is not available or drivers are missing, the system gracefully prints a warning and initializes all execution steps on the host CPU.
- Processing speeds will be slower on CPU, so we recommend uploading short (5-10 seconds) video clips for local verification.
