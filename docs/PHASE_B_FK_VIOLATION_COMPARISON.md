# Phase B — Database Foreign-Key Violation Comparison Report

**Audit Date:** 2026-10-09  
**Execution Context:** Strictly Read-Only Database Integrity & Foreign-Key Audit  
**Target Databases:**
1. **Safety Backup (Pre-Phase B):** `backend/storage/cctv.db.backup_phase_b_safety`
2. **Current Database (Post-Phase B):** `backend/storage/cctv.db`

---

## 1. Executive Summary

A comprehensive, strictly read-only comparative analysis was performed between the pre-Phase B safety backup (`cctv.db.backup_phase_b_safety`) and the active production database (`cctv.db`). Both databases were queried via SQLite URI read-only connections (`mode=ro`) without altering any data, schemas, or foreign-key pragma configurations.

### Summary Comparison Table

| Metric | Pre-Phase B Safety Backup (`cctv.db.backup_phase_b_safety`) | Post-Phase B Current Database (`cctv.db`) | Difference / Delta |
| :--- | :--- | :--- | :--- |
| **`PRAGMA integrity_check`** | `ok` | `ok` | 0 errors |
| **Total Foreign-Key Violations** | **60** | **60** | **0 net change** |
| **Violations Introduced by Phase B** | N/A | **0** | None |
| **Pre-Existing Violations Resolved** | N/A | **0** | Preserved (untampered) |
| **Matching Rowids & PKs** | 60 | 60 | 100% Identical |

### Key Findings
1. **Zero New Violations:** Phase B changes (UUID normalization script and non-blocking asynchronous task execution) introduced **0** foreign-key violations and **0** integrity errors.
2. **Identical Violation Footprint:** All 60 violations detected in `cctv.db` are **exact 1:1 duplicates** of the 60 violations existing in the pre-Phase B safety backup created prior to migration execution.
3. **Core Entities Untouched:**
   - `student_recognition_events`: **0** violations in backup, **0** in current database.
   - `tracks`: **0** violations in backup, **0** in current database.
   - `reports`: **0** violations in backup, **0** in current database.
   - `students`: **0** violations in backup, **0** in current database.

---

## 2. Low-Level Database Integrity & Pragma Checks

### 2.1 Pre-Phase B Safety Backup (`cctv.db.backup_phase_b_safety`)
- **`PRAGMA integrity_check`:** `['ok']` (Page structure, B-trees, indices, and freelists are completely healthy).
- **`PRAGMA foreign_key_check` Result Count:** **60** rows.

### 2.2 Current Database (`cctv.db`)
- **`PRAGMA integrity_check`:** `['ok']` (Page structure, B-trees, indices, and freelists are completely healthy).
- **`PRAGMA foreign_key_check` Result Count:** **60** rows.

---

## 3. Grouped Violation Analysis & Entity Categorization

Violations in both databases are grouped across 4 child tables into 5 foreign-key constraint groups:

| Group # | Child Table | Referenced Parent Table | FK Index | Foreign-Key Definition (`from -> to`) | Violation Count | Entity Domain Affected |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `notification_preferences` | `users` | `0` | `user_id -> id` | 1 | Notifications, User References |
| **2** | `videos` | `users` | `0` | `uploaded_by -> id` | 35 | Videos, User References |
| **3** | `student_face_embeddings` | `student_photos` | `0` | `photo_id -> id` | 6 | Students, Face Recognition Data |
| **4** | `student_face_embeddings` | `students` | `1` | `student_id -> id` | 6 | Students, Face Recognition Data |
| **5** | `notifications` | `users` | `0` | `user_id -> id` | 12 | Notifications, User References |
| **Total** | | | | | **60** | |

### Domain Inventory & Classification Breakdown

1. **Videos:**
   - **Involved:** Yes. 35 records in the `videos` table reference non-existent `users.id` values in `uploaded_by`.
2. **Students:**
   - **Involved:** Yes. 6 rows in `student_face_embeddings` reference non-existent `students.id` values, and 6 rows reference non-existent `student_photos.id` values.
3. **Student Recognition Events (`student_recognition_events`):**
   - **Involved:** **No**. 0 foreign-key violations exist in either database. The foreign-key error observed during video processing was an insertion-time failure caused by UUID format mismatch, not an existing orphan in the table.
4. **Tracks (`tracks`):**
   - **Involved:** **No**. 0 foreign-key violations exist in either database.
5. **Reports (`reports`):**
   - **Involved:** **No**. 0 foreign-key violations exist in either database.
6. **Notifications (`notifications` & `notification_preferences`):**
   - **Involved:** Yes. 12 rows in `notifications` and 1 row in `notification_preferences` reference non-existent `users.id` values.
7. **User References (`users`):**
   - **Involved:** Yes. 48 of the 60 total violations (80%) stem from dangling foreign keys referencing deleted or test user IDs.

---

## 4. Comprehensive List of Violating Row Identifiers

The violating rows below are **identical** between `cctv.db.backup_phase_b_safety` and `cctv.db`.

### Group 1: `notification_preferences` -> `users` (FK Index 0, `user_id -> id`)
- **Total Rows:** 1
- **Constraint Index:** `0`
- **Violating Row Details:**
  - `rowid`: `1` | Child Primary Key (`id`): `d5b1693e11c6439e88adabd0c6975fe8` | Violating `user_id`: `39a43b1330fa4741abe031dd552bd44a`

---

### Group 2: `videos` -> `users` (FK Index 0, `uploaded_by -> id`)
- **Total Rows:** 35
- **Constraint Index:** `0`
- **Violating Row Details:**

| `rowid` | Video Primary Key (`id`) | Violating `uploaded_by` (Missing User ID) |
| :--- | :--- | :--- |
| `1` | `c5e83fa66ad242bbaaa42281a8bf9767` | `0e4e750b8a98433787db7c323d1d1c63` |
| `2` | `67abd78e27194479be99e4bc92b88bcd` | `0e4e750b8a98433787db7c323d1d1c63` |
| `3` | `aa7c5aa708b34d13819239613068d0ee` | `0e4e750b8a98433787db7c323d1d1c63` |
| `4` | `b9c4ff081f0c47d88d72985c25024736` | `0e4e750b8a98433787db7c323d1d1c63` |
| `5` | `188f2db2499c430786bfd677d707b81f` | `0e4e750b8a98433787db7c323d1d1c63` |
| `6` | `5c116c061d234fa59c2011eb88e17038` | `0e4e750b8a98433787db7c323d1d1c63` |
| `7` | `fb97eed6ec204749acbf2c78c1c0c3fa` | `0e4e750b8a98433787db7c323d1d1c63` |
| `8` | `a9d70cf698224608ae4d64d25da56057` | `0e4e750b8a98433787db7c323d1d1c63` |
| `9` | `3f34d431e162417aa2bf6ae12aea8f2f` | `0e4e750b8a98433787db7c323d1d1c63` |
| `10` | `11a301bebf1345d7b3b49390c1afab65` | `0e4e750b8a98433787db7c323d1d1c63` |
| `12` | `18eaa02abd294fb2a1dea170e111684a` | `0e4e750b8a98433787db7c323d1d1c63` |
| `13` | `d6b467329eeb4f928b215de689835127` | `0e4e750b8a98433787db7c323d1d1c63` |
| `14` | `862ad9f5ddee44e297449e32691531b1` | `0e4e750b8a98433787db7c323d1d1c63` |
| `15` | `c73a643664e24a1aaf68b5dca1f5b966` | `0e4e750b8a98433787db7c323d1d1c63` |
| `16` | `137f6e5272a64c6c917138211aa9f166` | `0e4e750b8a98433787db7c323d1d1c63` |
| `17` | `128b5fef1e9845559c5657cb85707ffc` | `0e4e750b8a98433787db7c323d1d1c63` |
| `18` | `f827953bb9bc401d98f144ee6bc83d20` | `46e13105cc264460b1af7aec508257e7` |
| `19` | `c8e15d7e37494d9bad3d3e735c221cc8` | `0e4e750b8a98433787db7c323d1d1c63` |
| `20` | `6d5ae462bb754aaf8c2b3f9b55792333` | `0e4e750b8a98433787db7c323d1d1c63` |
| `21` | `8d06a440f93d4906994714597bda9aa8` | `0e4e750b8a98433787db7c323d1d1c63` |
| `22` | `9076fdf4b7e04ff69e005578a2e4eff7` | `23087cdef8ca481597690516754d6921` |
| `23` | `f1c4f3fff6164e189bfe7893b523f30d` | `23087cdef8ca481597690516754d6921` |
| `24` | `1a7b04d1664f4abcb582df2d71e2f4c1` | `23087cdef8ca481597690516754d6921` |
| `25` | `673cc45bcdfb453685705e67616624f8` | `23087cdef8ca481597690516754d6921` |
| `26` | `25188ec9ffe843a6aca8be7d024eec62` | `23087cdef8ca481597690516754d6921` |
| `27` | `180d2ee88ebe455f9dc28ec30e725d2d` | `23087cdef8ca481597690516754d6921` |
| `28` | `d1ca6645c28041e7811687e6bfa19a40` | `23087cdef8ca481597690516754d6921` |
| `29` | `43533ac4da234477953da20124ff8298` | `23087cdef8ca481597690516754d6921` |
| `30` | `e04f7ecc580e463e84ac67a24e963e83` | `23087cdef8ca481597690516754d6921` |
| `31` | `a6418a59d9d04f7284b67cda606d4741` | `e1f2a3b4c5d678901234567890abcdef` |
| `32` | `d5c9ebc6dae040608fea9c2de9cb3e10` | `23087cdef8ca481597690516754d6921` |
| `33` | `f460e5391ace4f91997065f405fc1c07` | `23087cdef8ca481597690516754d6921` |
| `34` | `4b9ca1d723eb48f782a5969cf4523473` | `e7c1ba3e1e4c4a539fa2080d02e4bbea` |
| `35` | `3a35f4f1b73c4f62bec7817b9417c369` | `96a7f943e62b49bdbf00e8f3e7a1ff0c` |
| `36` | `33e48417c5194bd99b2cb024d13ca56f` | `23087cdef8ca481597690516754d6921` |

---

### Group 3: `student_face_embeddings` -> `student_photos` (FK Index 0, `photo_id -> id`)
- **Total Rows:** 6
- **Constraint Index:** `0`
- **Violating Row Details:**

| `rowid` | Embedding Primary Key (`id`) | Violating `photo_id` (Missing Photo ID) |
| :--- | :--- | :--- |
| `8` | `7c932f4fa7c94173a72d0d33ba3d9908` | `8079bd108a23418cbc446eafe8cf5523` |
| `9` | `b691349bc8e54eed8fb018ac90c4bc33` | `532295fc5add45c987a6e8ba93d0d711` |
| `10` | `257bec6eb8c54599b2d4dfd9063fd3ea` | `5efa9961eb0f41fdbb3d1852ebf49297` |
| `11` | `5016d8fe24814cc786f4aadce7ba77f6` | `e8d2587f97a04d4d8de3ecfc635405dc` |
| `12` | `83111a770dfb47b0abe84972ed99672e` | `1e1580efb8d5406a9c8e2af79fb1dd33` |
| `13` | `6c4ef3204ad443318572bcc0e2d3d5a8` | `68b5925a7a894543a1529edbc97e5880` |

---

### Group 4: `student_face_embeddings` -> `students` (FK Index 1, `student_id -> id`)
- **Total Rows:** 6
- **Constraint Index:** `1`
- **Violating Row Details:**

| `rowid` | Embedding Primary Key (`id`) | Violating `student_id` (Missing Student ID) |
| :--- | :--- | :--- |
| `8` | `7c932f4fa7c94173a72d0d33ba3d9908` | `d13c2b564ee24417be164bc6581ad54d` |
| `9` | `b691349bc8e54eed8fb018ac90c4bc33` | `d13c2b564ee24417be164bc6581ad54d` |
| `10` | `257bec6eb8c54599b2d4dfd9063fd3ea` | `d13c2b564ee24417be164bc6581ad54d` |
| `11` | `5016d8fe24814cc786f4aadce7ba77f6` | `f426f144891245c5b7592ad744e6bdee` |
| `12` | `83111a770dfb47b0abe84972ed99672e` | `f426f144891245c5b7592ad744e6bdee` |
| `13` | `6c4ef3204ad443318572bcc0e2d3d5a8` | `f426f144891245c5b7592ad744e6bdee` |

---

### Group 5: `notifications` -> `users` (FK Index 0, `user_id -> id`)
- **Total Rows:** 12
- **Constraint Index:** `0`
- **Violating Row Details:**

| `rowid` | Notification Primary Key (`id`) | Violating `user_id` (Missing User ID) |
| :--- | :--- | :--- |
| `1` | `7aac1b9af5f9469b9176ff4eaaef6d62` | `0e4e750b8a98433787db7c323d1d1c63` |
| `2` | `c0763340e6a5480a898fb4252a114511` | `46e13105cc264460b1af7aec508257e7` |
| `3` | `f14af047e0e546ff86688fadf3df5ad1` | `23087cdef8ca481597690516754d6921` |
| `4` | `2fd240d5bbaa4fd3898bb95982e0bf66` | `0e4e750b8a98433787db7c323d1d1c63` |
| `5` | `e4d1f14950854656af9359ffe627e64e` | `46e13105cc264460b1af7aec508257e7` |
| `6` | `01b1d3fc5a5949b7b3453c4e298aa3d2` | `23087cdef8ca481597690516754d6921` |
| `7` | `b6acf6b4f366460e92574d639bb8e2a1` | `0e4e750b8a98433787db7c323d1d1c63` |
| `8` | `92e797805d434051a3ed4f87331f5088` | `46e13105cc264460b1af7aec508257e7` |
| `9` | `ffece2f86d26443da0053a45d5aa5685` | `23087cdef8ca481597690516754d6921` |
| `10` | `ae23c373a96b4aa9850645a9cf62e2fd` | `0e4e750b8a98433787db7c323d1d1c63` |
| `11` | `c65385b5b48647b4bb474775c8128078` | `46e13105cc264460b1af7aec508257e7` |
| `12` | `c78c576cf2be41ad91eadd4a89a185c1` | `23087cdef8ca481597690516754d6921` |

---

## 5. Comparative Evaluation: Pre-Phase B vs. Post-Phase B

1. **Which violations existed BEFORE Phase B?**
   - **All 60 violations** listed above existed prior to Phase B. They are present in `cctv.db.backup_phase_b_safety` with identical rowids, primary keys, and invalid parent foreign-key references.
   - Origin: These records were created during previous development and testing phases (e.g., test users and test students created during Phase 6 and Phase 8 test scripts that were later dropped or deleted without cascading deletes when foreign keys were temporarily disabled or during non-cascading raw queries).

2. **Which violations appeared AFTER Phase B?**
   - **Zero (0).** No new violations appeared in `backend/storage/cctv.db`.
   - The Phase B UUID normalization script safely transformed hyphenated UUIDs to compact 32-character hex representations exclusively where matching records existed, maintaining foreign-key validity without orphan generation.

3. **Status of Key Entities:**
   - `student_recognition_events`: 0 violations in backup, 0 in current database.
   - `students`: 0 violations in backup, 0 in current database.
   - `tracks`: 0 violations in backup, 0 in current database.
   - `reports`: 0 violations in backup, 0 in current database.
   - `cameras`: 0 violations in backup, 0 in current database.

---

## 6. Audit Conclusion & Compliance Note

- **Database Integrity Status:** Clean (`PRAGMA integrity_check` = `ok` on both databases).
- **Phase B Safety:** Verified 100% safe. No foreign-key corruption, broken relationships, or new orphan records were introduced.
- **Strict Read-Only Compliance:** In accordance with audit requirements, no records were deleted, repaired, or modified; foreign-key enforcement was not tampered with; and no schema changes or video reprocessing tasks were triggered.
