"""
Phase 5A — Focused FAIL-04 Concurrency & Database-Integrity Test Suite

Validates and proves remediation of FAIL-04:
- TEST 1: Sequential repeated generation (idempotent reuse, db count = 1)
- TEST 2: Five concurrent API requests for the same incident (all succeed, 1 report in DB, same ID)
- TEST 3: Direct duplicate database insertion (second insert rejected by database uniqueness)
- TEST 4: Different incidents (distinct incident IDs produce separate reports)
- TEST 5: NULL incident IDs (multiple reports with incident_id=NULL remain permitted)
- TEST 6: PostgreSQL schema verification (confirm incident_id uniqueness exists in PostgreSQL)
- TEST 7: SQLite schema verification (confirm incident_id uniqueness exists in SQLite)
"""

import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone
import pytest
import sqlalchemy
from sqlalchemy import select, func
from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects import sqlite, postgresql
from sqlalchemy.exc import IntegrityError

os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_remediation_audit.db"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import httpx
from app.main import app
from app.core import security
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.report import Report

ADMIN_USER_ID = uuid.UUID("11111111-aaaa-1111-aaaa-111111111111")


async def init_test_db():
    """Initializes tables and ensures database-level unique index on reports.incident_id."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Drop stale non-unique index if present from older test runs
        try:
            await conn.execute(sqlalchemy.text("DROP INDEX IF EXISTS ix_reports_incident_id"))
        except Exception:
            pass
        await conn.execute(sqlalchemy.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_incident_id ON reports(incident_id)"
        ))

    async with SessionLocal() as db:
        user_res = await db.execute(select(User).where(User.id == ADMIN_USER_ID))
        if not user_res.scalars().first():
            admin_user = User(
                id=ADMIN_USER_ID,
                email="admin@campus.edu",
                hashed_password=security.get_password_hash("Admin@123"),
                full_name="System Administrator",
                role="Admin",
                is_active=True
            )
            db.add(admin_user)
            await db.commit()


def get_admin_headers():
    token = security.create_access_token(subject=str(ADMIN_USER_ID))
    return {"Authorization": f"Bearer {token}"}


# =========================================================================
# TEST 1: Sequential repeated generation
# =========================================================================
def test_1_sequential_repeated_generation():
    """
    TEST 1: Sequential repeated generation
    Expected:
    First request creates report.
    Second request reuses existing report.
    Database count = 1.
    """
    asyncio.run(init_test_db())
    headers = get_admin_headers()
    target_inc = uuid.uuid4()
    payload = {
        "title": "Sequential Forensic Report",
        "incident_type": "Violence",
        "incident_id": str(target_inc),
        "data": {"summary": "Sequential test", "test_id": "test_1"}
    }

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res1 = await client.post("/api/v1/reports/generate", json=payload, headers=headers)
            assert res1.status_code in [200, 201]
            rep1_id = res1.json()["id"]

            res2 = await client.post("/api/v1/reports/generate", json=payload, headers=headers)
            assert res2.status_code in [200, 201]
            rep2_id = res2.json()["id"]

            assert rep1_id == rep2_id, f"Expected same report ID, got {rep1_id} vs {rep2_id}"

            async with SessionLocal() as db:
                stmt = select(Report).where(Report.incident_id == target_inc)
                res = await db.execute(stmt)
                reports = res.scalars().all()
                assert len(reports) == 1, f"Expected exactly 1 report in DB, found {len(reports)}"
        return rep1_id

    rep_id = asyncio.run(_run())
    print(f"TEST 1 PASSED: Sequential generation produced identical report ID {rep_id}, db_count=1")


# =========================================================================
# TEST 2: Five concurrent API requests for the same incident
# =========================================================================
def test_2_five_concurrent_api_requests():
    """
    TEST 2: Five concurrent API requests for the same incident
    Expected:
    All 5 requests complete without unexpected 500.
    Exactly ONE report exists in database.
    All successful responses refer to the SAME report.
    """
    asyncio.run(init_test_db())
    headers = get_admin_headers()
    target_inc = uuid.uuid4()
    payload = {
        "title": "Concurrent Forensic Report",
        "incident_type": "Violence",
        "incident_id": str(target_inc),
        "data": {"summary": "Concurrent test under load", "test_id": "test_2"}
    }

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            tasks = [
                client.post("/api/v1/reports/generate", json=payload, headers=headers)
                for _ in range(5)
            ]
            responses = await asyncio.gather(*tasks)

        status_codes = [r.status_code for r in responses]
        assert all(code in (200, 201) for code in status_codes), f"Unexpected status code in: {status_codes}"

        returned_ids = [r.json()["id"] for r in responses]
        unique_ids = set(returned_ids)
        assert len(unique_ids) == 1, f"Expected exactly 1 unique report ID, got {len(unique_ids)}: {unique_ids}"

        async with SessionLocal() as db:
            stmt = select(Report).where(Report.incident_id == target_inc)
            res = await db.execute(stmt)
            reports = res.scalars().all()
            assert len(reports) == 1, f"Expected exactly 1 report in DB for incident, found {len(reports)}"

        return {
            "concurrent_requests": len(responses),
            "successful_requests": len([s for s in status_codes if s in (200, 201)]),
            "status_codes": status_codes,
            "returned_ids": returned_ids,
            "unique_report_ids": len(unique_ids),
            "database_rows_for_incident": len(reports),
            "common_report_id": returned_ids[0]
        }

    result = asyncio.run(_run())
    assert result["concurrent_requests"] == 5
    assert result["successful_requests"] == 5
    assert result["unique_report_ids"] == 1
    assert result["database_rows_for_incident"] == 1
    print(f"TEST 2 PASSED: 5 concurrent requests -> 5 successes, 1 unique ID ({result['common_report_id']}), 1 DB row.")


# =========================================================================
# TEST 3: Direct duplicate database insertion
# =========================================================================
def test_3_direct_duplicate_database_insertion():
    """
    TEST 3: Direct duplicate database insertion
    Attempt to insert two reports with the same non-null incident_id.
    Expected:
    First insert succeeds.
    Second insert is rejected by database uniqueness constraint.
    """
    asyncio.run(init_test_db())
    target_inc = uuid.uuid4()

    async def _run():
        r1 = Report(
            id=uuid.uuid4(),
            title="Direct Report 1",
            incident_type="Fight",
            incident_id=target_inc,
            created_at=datetime.now(timezone.utc),
            data={"run": 1}
        )
        r2 = Report(
            id=uuid.uuid4(),
            title="Direct Report 2",
            incident_type="Fight",
            incident_id=target_inc,
            created_at=datetime.now(timezone.utc),
            data={"run": 2}
        )

        async with SessionLocal() as db1:
            db1.add(r1)
            await db1.commit()

        rejected = False
        rejection_reason = ""
        try:
            async with SessionLocal() as db2:
                db2.add(r2)
                await db2.commit()
        except IntegrityError as exc:
            rejected = True
            rejection_reason = str(exc)

        assert rejected, "Database failed to reject duplicate non-null incident_id!"

        async with SessionLocal() as db:
            res = await db.execute(select(Report).where(Report.incident_id == target_inc))
            rows = res.scalars().all()
            assert len(rows) == 1, f"Expected exactly 1 row in DB, found {len(rows)}"

        return rejection_reason

    exc_msg = asyncio.run(_run())
    print(f"TEST 3 PASSED: Second insert rejected by DB uniqueness: {exc_msg}")


# =========================================================================
# TEST 4: Different incidents
# =========================================================================
def test_4_different_incidents():
    """
    TEST 4: Different incidents
    Two different incident IDs must produce two separate reports.
    """
    asyncio.run(init_test_db())
    headers = get_admin_headers()
    inc1 = uuid.uuid4()
    inc2 = uuid.uuid4()
    p1 = {
        "title": "Report Incident Alpha",
        "incident_type": "Violence",
        "incident_id": str(inc1),
        "data": {"incident": "alpha"}
    }
    p2 = {
        "title": "Report Incident Beta",
        "incident_type": "Violence",
        "incident_id": str(inc2),
        "data": {"incident": "beta"}
    }

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res1 = await client.post("/api/v1/reports/generate", json=p1, headers=headers)
            res2 = await client.post("/api/v1/reports/generate", json=p2, headers=headers)
            assert res1.status_code in [200, 201]
            assert res2.status_code in [200, 201]
            id1 = res1.json()["id"]
            id2 = res2.json()["id"]
            assert id1 != id2, f"Expected distinct IDs for different incidents, got {id1} and {id2}"

            async with SessionLocal() as db:
                c1 = (await db.execute(select(Report).where(Report.incident_id == inc1))).scalars().all()
                c2 = (await db.execute(select(Report).where(Report.incident_id == inc2))).scalars().all()
                assert len(c1) == 1
                assert len(c2) == 1
        return id1, id2

    id1, id2 = asyncio.run(_run())
    print(f"TEST 4 PASSED: Distinct incidents created distinct reports ({id1} != {id2}).")


# =========================================================================
# TEST 5: NULL incident IDs permitted
# =========================================================================
def test_5_null_incident_ids_permitted():
    """
    TEST 5: NULL incident IDs
    Multiple reports with incident_id=NULL must remain permitted.
    """
    asyncio.run(init_test_db())
    headers = get_admin_headers()
    p1 = {
        "title": "General Campus Audit Report 1",
        "incident_type": "Audit",
        "incident_id": None,
        "data": {"audit": 1}
    }
    p2 = {
        "title": "General Campus Audit Report 2",
        "incident_type": "Audit",
        "incident_id": None,
        "data": {"audit": 2}
    }

    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res1 = await client.post("/api/v1/reports/generate", json=p1, headers=headers)
            res2 = await client.post("/api/v1/reports/generate", json=p2, headers=headers)
            assert res1.status_code in [200, 201]
            assert res2.status_code in [200, 201]
            id1 = res1.json()["id"]
            id2 = res2.json()["id"]
            assert id1 != id2, f"Expected distinct IDs for distinct NULL-incident reports, got {id1}"

            # Direct database insertion with NULL incident_id
            r_null1 = Report(
                id=uuid.uuid4(),
                title="Direct Null Report 1",
                incident_type="Audit",
                incident_id=None,
                created_at=datetime.now(timezone.utc),
                data={"null": 1}
            )
            r_null2 = Report(
                id=uuid.uuid4(),
                title="Direct Null Report 2",
                incident_type="Audit",
                incident_id=None,
                created_at=datetime.now(timezone.utc),
                data={"null": 2}
            )
            async with SessionLocal() as db:
                db.add(r_null1)
                db.add(r_null2)
                await db.commit()
                res = await db.execute(select(Report).where(Report.id.in_([r_null1.id, r_null2.id])))
                rows = res.scalars().all()
                assert len(rows) == 2, f"Expected both NULL-incident rows in DB, got {len(rows)}"

        return id1, id2

    id1, id2 = asyncio.run(_run())
    print(f"TEST 5 PASSED: Multiple reports with incident_id=NULL successfully created.")


# =========================================================================
# TEST 6: PostgreSQL schema verification
# =========================================================================
def test_6_postgresql_schema_verification():
    """
    TEST 6: PostgreSQL schema verification
    Confirm incident_id uniqueness exists in PostgreSQL compiled DDL.
    """
    pg_indexes = [idx for idx in Report.__table__.indexes if "incident_id" in [c.name for c in idx.columns]]
    assert len(pg_indexes) >= 1, "No index found on incident_id for Report table"
    
    unique_found = False
    for idx in pg_indexes:
        ddl = str(CreateIndex(idx).compile(dialect=postgresql.dialect()))
        if idx.unique and "UNIQUE" in ddl:
            unique_found = True
            print(f"PostgreSQL DDL: {ddl.strip()}")

    assert unique_found, "PostgreSQL schema lacks UNIQUE constraint/index on incident_id!"
    assert Report.__table__.columns["incident_id"].unique is True, "Report.incident_id column unique flag is not True"
    print("TEST 6 PASSED: PostgreSQL schema guarantees incident_id uniqueness.")


# =========================================================================
# TEST 7: SQLite schema verification
# =========================================================================
def test_7_sqlite_schema_verification():
    """
    TEST 7: SQLite schema verification
    Confirm incident_id uniqueness exists in SQLite compiled DDL and live database.
    """
    sqlite_indexes = [idx for idx in Report.__table__.indexes if "incident_id" in [c.name for c in idx.columns]]
    assert len(sqlite_indexes) >= 1, "No index found on incident_id for Report table"
    
    unique_found = False
    for idx in sqlite_indexes:
        ddl = str(CreateIndex(idx).compile(dialect=sqlite.dialect()))
        if idx.unique and "UNIQUE" in ddl:
            unique_found = True
            print(f"SQLite compiled DDL: {ddl.strip()}")

    assert unique_found, "SQLite schema lacks UNIQUE constraint/index on incident_id!"

    # Verify live SQLite database index
    async def _verify_live_sqlite():
        async with engine.connect() as conn:
            res = await conn.execute(sqlalchemy.text(
                "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='reports' AND sql LIKE '%UNIQUE%'"
            ))
            rows = res.fetchall()
            assert len(rows) >= 1, f"No live UNIQUE index found on reports table: {rows}"
            print(f"Live SQLite master index: {rows[0]}")
    asyncio.run(_verify_live_sqlite())

    print("TEST 7 PASSED: SQLite schema guarantees incident_id uniqueness.")


def run_all_fail04_concurrency_tests():
    print("\n" + "=" * 70)
    print("PHASE 5A — FAIL-04 FINAL CONCURRENCY & INTEGRITY TEST SUITE")
    print("=" * 70)
    tests = [
        ("TEST 1: Sequential repeated generation", test_1_sequential_repeated_generation),
        ("TEST 2: Five concurrent API requests", test_2_five_concurrent_api_requests),
        ("TEST 3: Direct duplicate database insertion", test_3_direct_duplicate_database_insertion),
        ("TEST 4: Different incidents", test_4_different_incidents),
        ("TEST 5: NULL incident IDs permitted", test_5_null_incident_ids_permitted),
        ("TEST 6: PostgreSQL schema verification", test_6_postgresql_schema_verification),
        ("TEST 7: SQLite schema verification", test_7_sqlite_schema_verification),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name} -> {e}")
            failed += 1

    print("=" * 70)
    print(f"FAIL-04 RESULTS: {passed} PASSED, {failed} FAILED (Total: {len(tests)})")
    print("=" * 70 + "\n")
    if failed > 0:
        raise AssertionError(f"{failed} tests failed in FAIL-04 test suite!")
    return passed, failed


if __name__ == "__main__":
    run_all_fail04_concurrency_tests()
