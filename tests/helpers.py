"""Shared test helpers."""


class FakeSettingsManager:
    """In-memory settings manager for tests — no file I/O, no side effects."""

    def __init__(self, saved_type=None, default_locale="en", excluded_msgids=None, ignore_patterns=None):
        self._saved_type = saved_type
        self._default_locale = default_locale
        self._excluded_msgids = excluded_msgids or []
        self._ignore_patterns = ignore_patterns or []

    def get_project_type(self, path):
        return self._saved_type

    def save_project_type(self, path, project_type):
        self._saved_type = project_type

    def get_project_default_locale(self, path):
        return self._default_locale

    def get_quality_review_excluded_msgids(self, path):
        return list(self._excluded_msgids)

    def get_quality_review_script_ignore_patterns(self, path):
        return list(self._ignore_patterns)
