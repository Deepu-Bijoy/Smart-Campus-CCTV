import os
import sys
import asyncio
import traceback

backend_dir = os.path.abspath("backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
tests_dir = os.path.abspath("backend/tests")
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

from test_array_type_and_session_bugfix import (
    test_custom_type_compilation_all_dialects,
    test_embedding_select_query_execution,
    test_student_embedding_retrieval_and_parsing,
    test_resolve_target_student_valid_student,
    test_resolve_target_student_nonexistent_student,
    test_resolve_target_student_ash,
    test_failure_status_persistence_after_exception,
    test_get_violence_analysis_result_endpoint_regression
)

tests = [
    ("1. Custom type compilation across dialects", test_custom_type_compilation_all_dialects),
    ("2. Embedding SELECT query execution", test_embedding_select_query_execution),
    ("3. Student embedding retrieval and numeric validation", test_student_embedding_retrieval_and_parsing),
    ("4. resolve_target_student() with valid student", test_resolve_target_student_valid_student),
    ("5. resolve_target_student() when no student exists", test_resolve_target_student_nonexistent_student),
    ("6. resolve_target_student() with Ash", test_resolve_target_student_ash),
    ("7. Failure-status persistence after DB exception & session rollback", test_failure_status_persistence_after_exception),
    ("8. Existing violence-analysis endpoint regression", test_get_violence_analysis_result_endpoint_regression)
]

async def main():
    print("=" * 80)
    print("RUNNING FOCUSED REGRESSION TEST SUITE FOR BUGFIX")
    print("=" * 80)
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        print(f"\n[RUNNING] {name}...")
        try:
            await test_fn()
            print(f"[PASSED]  {name}")
            passed += 1
        except Exception as e:
            print(f"[FAILED]  {name}: {e}")
            traceback.print_exc()
            failed += 1
            
    print("\n" + "=" * 80)
    print(f"SUMMARY: {passed} passed, {failed} failed out of {len(tests)} tests.")
    print("=" * 80)
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
