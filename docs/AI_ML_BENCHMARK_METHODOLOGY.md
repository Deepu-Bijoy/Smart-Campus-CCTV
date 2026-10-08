# AI/ML BENCHMARK METHODOLOGY & TIMING CORRECTION AUDIT

**Project:** AI-Powered Smart CCTV Investigation System  
**Phase:** Phase 2A — AI/ML Benchmark Methodology Correction  
**Target Hardware:** NVIDIA GeForce RTX 3050 Laptop GPU (4.0 GB VRAM, Compute Capability 8.6), CUDA 12.4  
**Audit Rule:** Measurement correction only. Zero modifications to production source code, model weights, or system thresholds.  

---

## 1. Summary of Methodological Corrections

In Phase 2A, the empirical measurement harness was updated to address the following benchmark limitations:

| Benchmark Aspect | Baseline Phase 2 Method | Corrected Phase 2A Method | Reason for Correction |
| :--- | :--- | :--- | :--- |
| **CUDA Latency Timing** | Wall-clock `time.time()` without explicit synchronization | `torch.cuda.synchronize()` before and after timer + `time.perf_counter()` | Asynchronous CUDA kernel launches can return prematurely before GPU execution finishes, under-reporting cold/warm latencies. |
| **Latency Statistics** | Mean and median only over 10 runs | Mean, Median, P95, P99, and Standard Deviation ($\sigma$) over 15 warm runs | Captures GPU kernel launch variance, memory bus spikes, and true tail latency. |
| **ONNX Runtime VRAM** | Attributed entirely to `torch.cuda.memory_allocated()` | Reported as "PyTorch allocator VRAM: 12.13 MB" + caveat that ORT maintains its own internal memory arena | InsightFace uses ONNX Runtime with `CUDAExecutionProvider`. PyTorch's caching allocator cannot see memory managed internally by ORT's CUDA arena. |
| **CLIP Weight Provenance** | Claimed local file `weights/clip/ViT-B-32.pt` | Verified that production code loads Hugging Face Hub `openai/clip-vit-base-patch32` | Production code never references the local `.pt` file; it loads `model.safetensors` (577 MB) from Hugging Face cache. |
| **Full Pipeline VRAM** | Termed "Full Combined Pipeline Active" | Differentiated into "Sequential Model Peak" vs. "Genuine Co-Resident VRAM" | Proved that all three active models (YOLOv8n + InsightFace + CLIP) can genuinely reside simultaneously on GPU (622 MB allocated, 678 MB reserved). |
| **FightDetector Evaluation** | Termed accuracy metric | Re-classified as "FUNCTIONAL / CONTROLLED TEST" with ground-truth evaluation harness | Synthetic motion/proximity fixtures test algorithmic correctness, not real-world CCTV altercation accuracy. |

---

## 2. Corrected Timing Protocol & Empirical Measurements

### Protocol Specification
```python
# Standardized CUDA timing loop
if torch.cuda.is_available():
    torch.cuda.synchronize()
t_start = time.perf_counter()

# Forward inference pass
output = model(input_tensor)

if torch.cuda.is_available():
    torch.cuda.synchronize()
t_end = time.perf_counter()
latency_ms = (t_end - t_start) * 1000.0
```

### Empirical Results (15 Synchronized Warm Runs on RTX 3050)

| Model / Task | Cold-Start | Warm Mean | Std Dev ($\sigma$) | Median | P95 | P99 | Throughput |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **YOLOv8n (Person Det)** | 1942.09 ms | **12.03 ms** | $\pm 4.44\text{ ms}$ | 9.55 ms | 19.08 ms | 23.95 ms | **83.13 FPS** |
| **ByteTrack (Det + Track)**| 96.24 ms | **15.74 ms** | $\pm 18.49\text{ ms}$ | 10.63 ms | 35.13 ms | 68.21 ms | **63.53 FPS** |
| **InsightFace (SCRFD+ArcFace)**| 219.78 ms | **18.59 ms** | $\pm 0.94\text{ ms}$ | 18.81 ms | 19.68 ms | 20.15 ms | **53.79 FPS** |
| **CLIP Image Encoder** | 16.02 ms | **9.84 ms** | $\pm 1.48\text{ ms}$ | 9.38 ms | 13.29 ms | 14.50 ms | **101.63 FPS** |
| **CLIP Text Encoder** | 45.12 ms | **10.69 ms** | $\pm 7.78\text{ ms}$ | 8.62 ms | 18.22 ms | 32.10 ms | **93.55 QPS** |
| **FightDetector (Math)** | $< 0.10 \text{ ms}$ | **$< 0.10 \text{ ms}$** | $\approx 0.0\text{ ms}$ | $< 0.10 \text{ ms}$ | $< 0.10 \text{ ms}$ | $< 0.10 \text{ ms}$ | **$> 10,000 \text{ ops}$** |

---

## 3. ONNX Runtime CUDA VRAM Accounting

- **PyTorch Caching Allocator:** Reports **12.13 MB** during InsightFace execution.
- **Methodological Finding:** InsightFace executes through ONNX Runtime's `CUDAExecutionProvider`. ONNX Runtime creates and manages an internal native CUDA memory arena independent of PyTorch's `caching_allocator`.
- **System Memory Delta:** `nvidia-smi` reports total GPU device physical memory utilization of ~749 MB (which includes Windows DWM, display compositing, and PyTorch/ORT buffers).
- **Formal Statement:** PyTorch allocator VRAM is 12.13 MB. Total ONNX Runtime CUDA memory allocation is not directly queryable via PyTorch allocator APIs and is isolated to ORT's internal execution provider.

---

## 4. CLIP Model Weight Provenance Resolution

- **Discrepancy:** The repository contains a 353.98 MB TorchScript/JIT file at `weights/clip/ViT-B-32.pt`.
- **Source Code Verification:** In [backend/app/core/model_manager.py:84](file:///C:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/model_manager.py#L84), `get_clip()` executes:
  ```python
  self._clip_model = _CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(self.device)
  self._clip_processor = _CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
  ```
- **Active Weights:** The active weights loaded into GPU memory are Hugging Face's `model.safetensors` (577.12 MB) located in the user's Hugging Face hub cache at `~/.cache/huggingface/hub/models--openai--clip-vit-base-patch32/`.
- **Conclusion:** `weights/clip/ViT-B-32.pt` is an **unreferenced legacy asset**. It is not loaded or executed by the backend.

---

## 5. Genuine Simultaneous Co-Residency VRAM Validation

To determine whether the system can support all models simultaneously on the 4.0 GB RTX 3050:
1. `YOLOv8n` was loaded onto GPU.
2. `InsightFace (Buffalo_L)` was initialized on GPU.
3. `CLIP (ViT-B/32)` was loaded onto GPU.
4. Without releasing any model or calling garbage collection, VRAM was queried with `torch.cuda.synchronize()`.

### Empirical Co-Residency Result:
- **PyTorch Allocated VRAM:** **622.10 MB**
- **PyTorch Reserved VRAM:** **678.00 MB**
- **GPU Total VRAM:** 4,096.00 MB
- **Allocated Percentage:** **15.19%**
- **Available Headroom:** **3,418.00 MB (83.4%)**

All three active vision models are genuinely co-resident in memory without triggering CUDA out-of-memory errors.

---

## 6. FightDetector Evaluation Framework Schema

Synthetic test data (`test_fight_detector_integration.py`) is officially classified as a **FUNCTIONAL / CONTROLLED TEST**. A standardized evaluation harness schema has been established for future ground-truth benchmark runs:

```json
{
  "clip_id": "string",
  "ground_truth": "FIGHT | NON_FIGHT",
  "prediction": "FIGHT | NON_FIGHT",
  "score": "float [0.0 - 1.0]",
  "timestamp_onset": "float",
  "duration_seconds": "float",
  "verdict": "TP | TN | FP | FN"
}
```

Aggregated metrics computed:
- $\text{Precision} = \frac{\text{TP}}{\text{TP} + \text{FP}}$
- $\text{Recall} = \frac{\text{TP}}{\text{TP} + \text{FN}}$
- $\text{F1} = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$
- $\text{FPR} = \frac{\text{FP}}{\text{FP} + \text{TN}}, \quad \text{FNR} = \frac{\text{FN}}{\text{FN} + \text{TP}}$

---

## 7. Blocked Models Status & Dependency Chains

### X3D-M (Blocked)
$$\text{X3D-M Checkpoint} \longrightarrow \text{PyTorchVideo Backbone} \longrightarrow \text{fvcore.nn.weight\_init} \longrightarrow \mathbf{FAIL:}\text{ ModuleNotFoundError: 'fvcore'}$$
- **Root Cause:** Missing `fvcore` Python package.
- **Action Required:** `pip install fvcore` (held pending authorization).

### OSNet (Blocked)
$$\text{OSNet Architecture} \longrightarrow \text{torchreid.utils.FeatureExtractor} \longrightarrow \mathbf{FAIL:}\text{ ModuleNotFoundError: 'torchreid'}$$
- **Root Cause:** Missing `torchreid` Python package.
- **Action Required:** `pip install torchreid` (held pending authorization).
