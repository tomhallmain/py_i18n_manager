import unittest
from pathlib import Path

from utils.globals import ProjectType
from utils.project_detector import ProjectDetector


class TestProjectDetector(unittest.TestCase):
    def setUp(self):
        self.assets_root = Path(__file__).parent / "assets" / "project_detection"

    def test_detects_python_project_from_indicator(self):
        path = self.assets_root / "python_indicator"
        self.assertEqual(ProjectDetector.detect_project_type(str(path)), ProjectType.PYTHON)

    def test_detects_ruby_project_from_indicator(self):
        path = self.assets_root / "ruby_indicator"
        self.assertEqual(ProjectDetector.detect_project_type(str(path)), ProjectType.RUBY)

    def test_detects_java_project_from_indicator(self):
        path = self.assets_root / "java_indicator"
        self.assertEqual(ProjectDetector.detect_project_type(str(path)), ProjectType.JAVA)

    def test_detects_javascript_project_from_indicator(self):
        path = self.assets_root / "javascript_indicator"
        self.assertEqual(
            ProjectDetector.detect_project_type(str(path)), ProjectType.JAVASCRIPT
        )

    def test_detects_rails_project_from_structure(self):
        path = self.assets_root / "rails_structure_indicator"
        self.assertEqual(ProjectDetector.detect_project_type(str(path)), ProjectType.RUBY)

    def test_prefers_python_when_python_and_ruby_indicators_both_present(self):
        path = self.assets_root / "mixed_python_ruby"
        self.assertEqual(ProjectDetector.detect_project_type(str(path)), ProjectType.PYTHON)

    def test_returns_none_for_unknown_structure(self):
        path = self.assets_root / "unknown_indicator"
        self.assertIsNone(ProjectDetector.detect_project_type(str(path)))

    def test_returns_none_for_nonexistent_directory(self):
        path = self.assets_root / "does_not_exist"
        self.assertIsNone(ProjectDetector.detect_project_type(str(path)))


if __name__ == "__main__":
    unittest.main()
