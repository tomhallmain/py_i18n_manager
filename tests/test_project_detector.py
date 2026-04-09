from pathlib import Path

import pytest

from utils.globals import ProjectType
from utils.project_detector import ProjectDetector

ASSETS = Path(__file__).parent / "assets" / "project_detection"


def test_detects_python_project_from_indicator():
    assert ProjectDetector.detect_project_type(str(ASSETS / "python_indicator")) == ProjectType.PYTHON


def test_detects_ruby_project_from_indicator():
    assert ProjectDetector.detect_project_type(str(ASSETS / "ruby_indicator")) == ProjectType.RUBY


def test_detects_java_project_from_indicator():
    assert ProjectDetector.detect_project_type(str(ASSETS / "java_indicator")) == ProjectType.JAVA


def test_detects_javascript_project_from_indicator():
    assert ProjectDetector.detect_project_type(str(ASSETS / "javascript_indicator")) == ProjectType.JAVASCRIPT


def test_detects_rails_project_from_structure():
    assert ProjectDetector.detect_project_type(str(ASSETS / "rails_structure_indicator")) == ProjectType.RUBY


def test_prefers_python_when_python_and_ruby_indicators_both_present():
    assert ProjectDetector.detect_project_type(str(ASSETS / "mixed_python_ruby")) == ProjectType.PYTHON


def test_returns_none_for_unknown_structure():
    assert ProjectDetector.detect_project_type(str(ASSETS / "unknown_indicator")) is None


def test_returns_none_for_nonexistent_directory():
    assert ProjectDetector.detect_project_type(str(ASSETS / "does_not_exist")) is None
