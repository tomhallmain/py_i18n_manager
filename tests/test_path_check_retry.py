"""Retry behavior of Utils.isdir_with_retry / isfile_with_retry / exists_with_retry.

The filesystem, the external-drive detection and ``time.sleep`` are all mocked, so no test
touches a real drive or actually waits.
"""

import os
from unittest.mock import call, patch

import pytest

from utils.utils import DEFAULT_PATH_CHECK_MAX_RETRIES, DEFAULT_PATH_CHECK_RETRY_DELAY, Utils

DRIVE_ROOT = "E:\\"
PATH = "E:\\project\\locale"

# (wrapper, os.path predicate it checks with, check name used in the retry log message)
WRAPPERS = [
    pytest.param(Utils.isdir_with_retry, "isdir", "Directory check", id="isdir"),
    pytest.param(Utils.isfile_with_retry, "isfile", "File check", id="isfile"),
    pytest.param(Utils.exists_with_retry, "exists", "Path existence check", id="exists"),
]


def _drive_root(root):
    return patch.object(Utils, "_get_external_drive_root", return_value=root)


@pytest.mark.parametrize("wrapper, predicate, description", WRAPPERS)
class TestRetryLoop:
    def test_local_path_is_checked_once_without_sleep(self, wrapper, predicate, description):
        with _drive_root(None), patch.object(os.path, predicate, return_value=False) as check, \
                patch("utils.utils.time.sleep") as sleep:
            assert wrapper(PATH) is False

        check.assert_called_once_with(PATH)
        sleep.assert_not_called()

    def test_external_path_retries_and_never_sleeps_after_last_attempt(
        self, wrapper, predicate, description
    ):
        with _drive_root(DRIVE_ROOT), \
                patch.object(os.path, predicate, return_value=False) as check, \
                patch("utils.utils.time.sleep") as sleep:
            assert wrapper(PATH, max_retries=2, retry_delay=0.5, wake_drive=False) is False

        assert check.call_args_list == [call(PATH)] * 3
        assert sleep.call_args_list == [call(0.5)] * 2

    def test_external_path_stops_at_first_success(self, wrapper, predicate, description):
        with _drive_root(DRIVE_ROOT), \
                patch.object(os.path, predicate, side_effect=[False, True]) as check, \
                patch("utils.utils.time.sleep") as sleep:
            assert wrapper(PATH, wake_drive=False) is True

        assert check.call_count == 2
        sleep.assert_called_once_with(DEFAULT_PATH_CHECK_RETRY_DELAY)

    def test_defaults_come_from_module_constants(self, wrapper, predicate, description):
        with _drive_root(DRIVE_ROOT), \
                patch.object(os.path, predicate, return_value=False) as check, \
                patch("utils.utils.time.sleep") as sleep:
            wrapper(PATH, wake_drive=False)

        assert check.call_count == DEFAULT_PATH_CHECK_MAX_RETRIES + 1
        assert sleep.call_args_list == [
            call(DEFAULT_PATH_CHECK_RETRY_DELAY)
        ] * DEFAULT_PATH_CHECK_MAX_RETRIES

    def test_retry_log_names_the_check(self, wrapper, predicate, description):
        with _drive_root(DRIVE_ROOT), patch.object(os.path, predicate, return_value=False), \
                patch("utils.utils.time.sleep"), patch("utils.utils.logger") as logger:
            wrapper(PATH, max_retries=1, wake_drive=False)

        logger.debug.assert_called_once()
        message = logger.debug.call_args.args[0]
        assert message.startswith(f"{description} failed for '{PATH}'")
        assert "(attempt 1/1)" in message


class TestWakeProbe:
    def test_probe_runs_once_before_first_attempt(self):
        with _drive_root(DRIVE_ROOT), patch.object(os.path, "isdir", return_value=False), \
                patch.object(os.path, "exists", return_value=False) as exists, \
                patch("utils.utils.time.sleep"):
            Utils.isdir_with_retry(PATH, max_retries=2)

        exists.assert_called_once_with(DRIVE_ROOT)

    def test_no_probe_when_wake_drive_is_false(self):
        with _drive_root(DRIVE_ROOT), patch.object(os.path, "isdir", return_value=False), \
                patch.object(os.path, "exists") as exists, patch("utils.utils.time.sleep"):
            Utils.isdir_with_retry(PATH, max_retries=2, wake_drive=False)

        exists.assert_not_called()

    def test_no_probe_for_local_path(self):
        with _drive_root(None), patch.object(os.path, "isdir", return_value=True), \
                patch.object(os.path, "exists") as exists:
            assert Utils.isdir_with_retry(PATH) is True

        exists.assert_not_called()

    def test_probe_oserror_is_ignored(self):
        with _drive_root(DRIVE_ROOT), patch.object(os.path, "isdir", return_value=True), \
                patch.object(os.path, "exists", side_effect=OSError("drive asleep")):
            assert Utils.isdir_with_retry(PATH) is True

    def test_exists_probe_precedes_path_checks(self):
        # exists_with_retry uses os.path.exists both for the probe and for the check itself.
        with _drive_root(DRIVE_ROOT), \
                patch.object(os.path, "exists", side_effect=[True, False, True]) as exists, \
                patch("utils.utils.time.sleep") as sleep:
            assert Utils.exists_with_retry(PATH) is True

        assert exists.call_args_list == [call(DRIVE_ROOT), call(PATH), call(PATH)]
        sleep.assert_called_once()
