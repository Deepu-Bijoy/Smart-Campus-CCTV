# End-to-End Testing & Verification Guide

This guide provides a comprehensive checklist to verify that all modules of the **Smart Campus CCTV Surveillance & Investigation System** are functioning correctly.

---

## Verification Checklist

| Test # | Verification Step | Expected Behavior | Status |
|---|---|---|---|
| **Test 1** | Start the system components | Backend server (Uvicorn), Frontend server (Vite), and Qdrant database are active without errors. | `[ ] PASS / FAIL` |
| **Test 2** | Authenticate as Operator | Logging in with `operator@smartcampus.com` succeeds, and redirects to Dashboard. | `[ ] PASS / FAIL` |
| **Test 3** | Add a Camera | Adding a camera (e.g. `Camera-NorthGate`) saves it successfully. | `[ ] PASS / FAIL` |
| **Test 4** | Add a Student profile | Uploading student info (e.g. Deepu Bijoy, Roll: CS22B045, S8 CSE A) saves the registry entry. | `[ ] PASS / FAIL` |
| **Test 5** | Enroll face embedding | Uploading the student enrollment photos computes SCRFD/ArcFace features and saves to Qdrant. | `[ ] PASS / FAIL` |
| **Test 6** | Upload CCTV video | Uploading a test MP4 video associated with the camera queues the processing. | `[ ] PASS / FAIL` |
| **Test 7** | Wait for AI pipeline processing | Progress bar moves through Validation ➔ Processing ➔ Embeddings ➔ Completed. | `[ ] PASS / FAIL` |
| **Test 8** | Verify person tracks | The "Surveillance Feeds" details show detected tracks, bounding boxes, and timestamp logs. | `[ ] PASS / FAIL` |
| **Test 9** | Verify Qdrant index count | The vector count in Qdrant `cctv_embeddings` collection is greater than 0. | `[ ] PASS / FAIL` |
| **Test 10**| Search for "person" | Running a semantic query for `"person"` returns valid track matches. | `[ ] PASS / FAIL` |
| **Test 11**| Search by clothing description | Running a semantic query for clothing (e.g. `"blue shirt"`) filters results accordingly. | `[ ] PASS / FAIL` |
| **Test 12**| Search student by name | Searching for the enrolled student's name returns tracks containing their profile. | `[ ] PASS / FAIL` |
| **Test 13**| Verify student identification | ArcFace face similarity score is matched against the enrolled profile (similarity > 0.60). | `[ ] PASS / FAIL` |
| **Test 14**| Anomaly/security event query | Querying for a zone crossing returns the trespass timeline item. | `[ ] PASS / FAIL` |
| **Test 15**| Verify explanation details | Match breakdown matches camera source, timestamp offset, student roll, and explainable reasons. | `[ ] PASS / FAIL` |

---

## Detailed Testing Instructions

### Step 1: Add Camera & Configure Virtual Zone
1. Log in to the Frontend Dashboard at `http://localhost:5173`.
2. Go to **Camera Management** ➔ Click **Add Camera**.
3. Fill details: Name: `Camera-NorthGate`, Building: `Main Gate`, Floor: `1`.
4. Click on the camera card, go to the virtual zone configuration tab, and draw a polygon line representing the boundary wall/fence. Save the zone.

### Step 2: Enroll Student Face
1. Go to the **Student Directory** ➔ Click **Enroll Student**.
2. Fill: Name: `Deepu Bijoy`, Roll: `CS22B045`, Department: `CSE`, Class: `S8 CSE A`.
3. Upload 3 profile pictures (e.g. front face, side face, masked). Click **Process Enrollment**.
4. Check that the console logs show `Face found?: yes` and `Embedding created?: yes` with dimension 512.

### Step 3: Ingest Video & Validate Matches
1. Go to **Upload Feed** ➔ Select your camera `Camera-NorthGate`.
2. Drag and drop a test MP4 video containing people walking or crossing lines. Click **Process Video**.
3. Wait for the processing progress card to reach `100% (Completed)`.
4. Go to **Semantic Search**, type: `"person jumping over the fence"` or `"Who crossed the gate?"`.
5. Verify that the explanation card loads showing:
   - **Camera**: `Camera-NorthGate`
   - **Confidence Match**: `High`
   - **Student Identity**: `Deepu Bijoy`
   - **Frame Snapshot**: A JPEG crop of the subject.
