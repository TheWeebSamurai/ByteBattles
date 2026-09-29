import asyncio
import io
import time
import zipfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.app.routes import auth, problems, submissions, users
from api.app.schemas.problems import ProblemUpdate
from api.app.schemas.user import BootstrapAdminRequest, TokenPayload
from api.app.utils import oauth2
from shared.core.database import Base
from shared.models import Category, Problem, TestCase, User, UserType, Difficulty, Language


class TestAdminAndProblemRoutes(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.admin = User(
            username="admin_user",
            email="admin@example.com",
            password_hash="hash",
            user_type=UserType.ADMIN,
        )
        self.regular = User(
            username="first_user",
            email="first@example.com",
            password_hash="hash",
            user_type=UserType.USER,
        )
        self.candidate = User(
            username="candidate",
            email="candidate@example.com",
            password_hash="hash",
            user_type=UserType.USER,
        )
        self.category = Category(name="Arrays", slug="arrays")
        self.problem = Problem(
            id="PRB001",
            title="Original title",
            difficulty=Difficulty.EASY,
            description="Description",
            constraints=["1 <= n <= 10"],
            input_desc="Input",
            output_desc="Output",
            sample_io={"input": "1", "output": "1"},
            memory_limit_mb=64,
            time_limit_sec=1,
            visibility=True,
            tags=[self.category],
        )
        self.old_case = TestCase(
            problem_id="PRB001",
            input_key="problems/PRB001/old-input",
            output_key="problems/PRB001/old-output",
        )
        self.problem.testcases.append(self.old_case)
        self.db.add_all([self.admin, self.regular, self.candidate, self.category, self.problem])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_bootstrap_promotes_only_once_and_uses_advisory_lock(self):
        self.db.delete(self.admin)
        self.db.commit()
        lock_calls = []
        execute = self.db.execute

        def execute_with_lock(statement, *args, **kwargs):
            if "pg_advisory_xact_lock" in str(statement):
                lock_calls.append(statement)
                return None
            return execute(statement, *args, **kwargs)

        self.db.execute = execute_with_lock
        with patch.object(auth, "BOOTSTRAP_ADMIN_SECRET", "test-secret"):
            promoted = auth.bootstrap_first_admin(
                BootstrapAdminRequest(username="first_user"), "test-secret", self.db
            )
            self.assertEqual(promoted["user_type"], UserType.ADMIN)
            self.assertEqual(len(lock_calls), 1)
            self.db.rollback()

            with self.assertRaises(HTTPException) as error:
                auth.bootstrap_first_admin(
                    BootstrapAdminRequest(username="candidate"), "test-secret", self.db
                )

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(lock_calls), 2)
        self.db.rollback()

    def test_bootstrap_requires_configured_valid_secret(self):
        request = BootstrapAdminRequest(username="first_user")
        with patch.object(auth, "BOOTSTRAP_ADMIN_SECRET", None):
            with self.assertRaises(HTTPException) as error:
                auth.bootstrap_first_admin(request, "test-secret", self.db)
        self.assertEqual(error.exception.status_code, 503)

        with patch.object(auth, "BOOTSTRAP_ADMIN_SECRET", "test-secret"):
            with self.assertRaises(HTTPException) as error:
                auth.bootstrap_first_admin(request, "wrong-secret", self.db)
        self.assertEqual(error.exception.status_code, 403)

    def test_admin_can_promote_user_and_promotion_is_idempotent(self):
        promoted = users.promote_user("candidate", self.admin, self.db)
        self.assertEqual(promoted["user_type"], UserType.ADMIN)
        promoted_again = users.promote_user("candidate", self.admin, self.db)
        self.assertEqual(promoted_again["user_type"], UserType.ADMIN)

    def test_promotion_returns_not_found_for_unknown_user(self):
        with self.assertRaises(HTTPException) as error:
            users.promote_user("missing", self.admin, self.db)
        self.assertEqual(error.exception.status_code, 404)

    def test_admin_dependency_rejects_regular_user(self):
        with self.assertRaises(HTTPException) as error:
            oauth2.get_current_admin(self.regular)
        self.assertEqual(error.exception.status_code, 403)

    def test_refresh_token_uses_configured_days_not_access_minutes(self):
        started_at = time.time()
        with patch.object(oauth2, "ACCESS_TOKEN_EXPIRE_MINUTES", 2), patch.object(
            oauth2, "REFRESH_TOKEN_EXPIRE_DAYS", 7
        ):
            token = oauth2.create_refresh_token(TokenPayload(sub=123))

        claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
        )
        self.assertEqual(claims["type"], "refresh")
        self.assertAlmostEqual(claims["exp"] - started_at, 7 * 24 * 60 * 60, delta=2)

    def test_admin_can_create_tag_and_duplicate_is_conflict(self):
        tag = problems.create_tag(
            problems.TagCreate(name="Graphs", slug="graphs"), self.admin, self.db
        )
        self.assertEqual(tag, {"name": "Graphs", "slug": "graphs"})
        self.assertIsNotNone(
            self.db.query(Category).filter(Category.slug == "graphs").first()
        )

        with self.assertRaises(HTTPException) as error:
            problems.create_tag(
                problems.TagCreate(name="Graphs", slug="graphs-2"), self.admin, self.db
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_problem_patch_changes_only_supplied_fields(self):
        result = problems.update_problem(
            "PRB001",
            ProblemUpdate(title="Updated", visibility=False, tags=["arrays"]),
            self.admin,
            self.db,
        )
        self.assertEqual(result["title"], "Updated")
        self.assertFalse(result["visibility"])
        self.assertEqual(result["description"], "Description")
        self.assertEqual(result["constraints"], ["1 <= n <= 10"])

    def test_problem_patch_rejects_unknown_tags_and_null_required_fields(self):
        with self.assertRaises(HTTPException) as error:
            problems.update_problem(
                "PRB001", ProblemUpdate(tags=["missing"]), self.admin, self.db
            )
        self.assertEqual(error.exception.status_code, 400)
        self.db.rollback()

        with self.assertRaises(ValueError):
            ProblemUpdate(title=None)

    def test_problem_search_filters_and_returns_pagination_metadata(self):
        matching_problems = [
            Problem(
                id=f"PAG00{index}",
                title=f"Sorting challenge {index}",
                difficulty=Difficulty.EASY,
                description="Description",
                constraints=[],
                input_desc="Input",
                output_desc="Output",
                sample_io={"input": "", "output": ""},
                memory_limit_mb=64,
                time_limit_sec=1,
                visibility=True,
                tags=[self.category],
            )
            for index in range(6)
        ]
        self.db.add_all(matching_problems)
        self.db.commit()

        first_page = problems.get_problems(
            page=1,
            limit=5,
            difficulty=Difficulty.EASY,
            tag="arrays",
            title="SORTING",
            db=self.db,
            current_user=None,
        )
        second_page = problems.get_problems(
            page=2,
            limit=5,
            difficulty=Difficulty.EASY,
            tag="arrays",
            title="SORTING",
            db=self.db,
            current_user=None,
        )

        self.assertEqual(first_page["total"], 6)
        self.assertEqual(first_page["page"], 1)
        self.assertEqual(first_page["limit"], 5)
        self.assertTrue(first_page["has_more"])
        self.assertEqual([item["id"] for item in first_page["items"]], [f"PAG00{i}" for i in range(5)])
        self.assertEqual([item["id"] for item in second_page["items"]], ["PAG005"])
        self.assertFalse(second_page["has_more"])

    def test_rate_limited_submission_returns_429_and_retry_after(self):
        request = type("SubmissionRequest", (), {
            "problem_id": "PRB001",
            "code": "int main() { return 0; }",
            "language": Language.C,
        })()
        with patch.object(submissions, "check_submission_rate_limit", return_value=17):
            with self.assertRaises(HTTPException) as error:
                submissions.create_submission(request, self.regular, self.db)

        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(error.exception.headers["Retry-After"], "17")

    def test_testcase_zip_replacement_commits_then_deletes_old_objects(self):
        storage = FakeStorage()
        with patch.object(problems, "get_storage_testcases", return_value=storage):
            response = asyncio.run(problems.replace_problem_testcases(
                "PRB001", FakeUpload(make_testcase_zip()), self.admin, self.db
            ))

        self.assertEqual(response, {"problem_id": "PRB001", "testcases": 1})
        cases = self.db.query(TestCase).filter(TestCase.problem_id == "PRB001").all()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].input_key, "new-object-1")
        self.assertEqual(cases[0].output_key, "new-object-2")
        self.assertCountEqual(storage.deleted, [
            "problems/PRB001/old-input",
            "problems/PRB001/old-output",
        ])

    def test_failed_testcase_upload_keeps_old_rows_and_cleans_new_objects(self):
        storage = FakeStorage(fail_on_upload=2)
        with patch.object(problems, "get_storage_testcases", return_value=storage):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(problems.replace_problem_testcases(
                    "PRB001", FakeUpload(make_testcase_zip()), self.admin, self.db
                ))

        self.assertEqual(error.exception.status_code, 500)
        cases = self.db.query(TestCase).filter(TestCase.problem_id == "PRB001").all()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].input_key, "problems/PRB001/old-input")
        self.assertEqual(storage.deleted, ["new-object-1"])

    def test_failed_testcase_commit_keeps_old_rows_and_cleans_new_objects(self):
        storage = FakeStorage()
        with patch.object(problems, "get_storage_testcases", return_value=storage):
            with patch.object(self.db, "commit", side_effect=RuntimeError("simulated commit failure")):
                with self.assertRaises(HTTPException) as error:
                    asyncio.run(problems.replace_problem_testcases(
                        "PRB001", FakeUpload(make_testcase_zip()), self.admin, self.db
                    ))

        self.assertEqual(error.exception.status_code, 500)
        self.db.expire_all()
        cases = self.db.query(TestCase).filter(TestCase.problem_id == "PRB001").all()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].input_key, "problems/PRB001/old-input")
        self.assertCountEqual(storage.deleted, ["new-object-1", "new-object-2"])

    def test_invalid_testcase_zip_does_not_change_existing_cases(self):
        with patch.object(problems, "get_storage_testcases", return_value=FakeStorage()):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(problems.replace_problem_testcases(
                    "PRB001", FakeUpload(b"not a zip"), self.admin, self.db
                ))
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.query(TestCase).filter(TestCase.problem_id == "PRB001").count(), 1)

    def test_mismatched_testcase_filenames_do_not_change_existing_cases(self):
        with patch.object(problems, "get_storage_testcases", return_value=FakeStorage()):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(problems.replace_problem_testcases(
                    "PRB001", FakeUpload(make_mismatched_testcase_zip()), self.admin, self.db
                ))
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(self.db.query(TestCase).filter(TestCase.problem_id == "PRB001").count(), 1)


class FakeUpload:
    filename = "cases.zip"

    def __init__(self, contents):
        self.contents = contents

    async def read(self):
        return self.contents


class FakeStorage:
    def __init__(self, fail_on_upload=None):
        self.fail_on_upload = fail_on_upload
        self.uploaded = []
        self.deleted = []

    def upload_bytes(self, problem_id, filename, data):
        if self.fail_on_upload == len(self.uploaded) + 1:
            raise RuntimeError("simulated storage failure")
        object_key = f"new-object-{len(self.uploaded) + 1}"
        self.uploaded.append((object_key, problem_id, filename, data))
        return object_key

    def delete_file(self, object_key):
        self.deleted.append(object_key)


def make_testcase_zip():
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("cases/inputs/1.txt", "input")
        archive.writestr("cases/outputs/1.txt", "output")
    return archive_bytes.getvalue()


def make_mismatched_testcase_zip():
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("cases/inputs/1.txt", "input")
        archive.writestr("cases/outputs/2.txt", "output")
    return archive_bytes.getvalue()


if __name__ == "__main__":
    unittest.main()