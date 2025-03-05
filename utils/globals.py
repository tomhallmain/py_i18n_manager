from enum import Enum
import os

from utils.config import config


class Globals:
    HOME = os.path.expanduser("~")
    DEFAULT_WORKFLOW = config.dict["default_workflow"]
    SKIP_CONFIRMATIONS = config.dict["skip_confirmations"]

class WorkflowType(Enum):
    AUDIT = "audit"
    OVERWRITE_PO_FILES = "overwrite_po_files"
    OVERWRITE_MO_FILES = "overwrite_mo_files"

class Language(Enum):
    PYTHON = "Python"
