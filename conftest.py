import sys
import os

# Ensure the project root is on sys.path so test imports like `from i18n...` work
# regardless of which directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(__file__))
