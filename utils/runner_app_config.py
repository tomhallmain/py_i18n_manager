from copy import deepcopy
import json

from utils.globals import WorkflowType, Language


class RunnerAppConfig:
    def __init__(self):
        self.language = Language.PYTHON.name
        self.workflow_type = WorkflowType.AUDIT.name
        self.auto_run = True

    def set_from_run_config(self, args):
        self.workflow_type = args.workflow_tag
        self.auto_run = args.auto_run

    @staticmethod
    def from_dict(_dict):
        app_config = RunnerAppConfig()
        app_config.__dict__ = deepcopy(_dict)
        if not hasattr(app_config, 'software_type'):
            app_config.language = Language.PYTHON.name
        return app_config

    def to_dict(self):
        _dict = deepcopy(self.__dict__)
        if not isinstance(self.language, str):
            _dict["software_type"] = self.language.name
        if not isinstance(self.workflow_type, str):
            _dict["workflow_type"] = self.workflow_type.name
        return _dict

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __hash__(self):
        class EnumsEncoder(json.JSONEncoder):
            def default(self, z):
                if isinstance(z, Language) or isinstance(z, WorkflowType) or isinstance(z, Sampler) or isinstance(z, Scheduler):
                    return (str(z.name))
                else:
                    return super().default(z)
        return hash(json.dumps(self, cls=EnumsEncoder, sort_keys=True))
