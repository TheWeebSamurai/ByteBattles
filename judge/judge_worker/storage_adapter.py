from config import SUBMISSION_BUCKET, TESTCASE_BUCKET
from shared.core import get_storage_submission_code, get_storage_testcases

class StorageAdapter:
    def read_submission_code(self, object_key: str) -> bytes:
        return get_storage_submission_code().get_file(object_key)

    def read_testcase_input(self, object_key: str) -> bytes:
        return get_storage_testcases().get_file(object_key)

    def read_testcase_output(self, object_key: str) -> bytes:
        return get_storage_testcases().get_file(object_key)