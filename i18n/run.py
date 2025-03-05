from copy import deepcopy
import time
import traceback

from i18n.i18n_manager import I18NManager
from utils.globals import Globals # must import first

prompt_list = [
]


class Run:
    def __init__(self, args, progress_callback=None):
        self.id = str(time.time())
        self.is_complete = False
        self.args = args
        self.editing = False
        self.progress_callback = progress_callback

    def is_infinite(self):
        return self.args.total == -1

    def run(self, config):
        if config.validate():
            I18NManager(config.directory).manage_translations(config)

        self.last_config = deepcopy(config)

    def do_workflow(self, workflow):
        config = Config(workflow)

        try:
            self.run(config)
        except KeyboardInterrupt:
            pass

    def load_and_run(self):
        if self.args.auto_run:
            print("Auto-run mode set.")

        workflow_tags = self.args.redo_files.split(",") if self.args.redo_files else self.args.workflow_tag.split(",")
        for workflow_tag in workflow_tags:
            if self.is_cancelled:
                break
            workflow = WorkflowPrompt.setup_workflow(workflow_tag)
            try:
                self.do_workflow(workflow)
            except Exception as e:
                print(e)
                traceback.print_exc()

    def execute(self):
        self.is_complete = False
        self.is_cancelled = False
        Globals.SKIP_CONFIRMATIONS = self.args.auto_run
        self.load_and_run()
        self.is_complete = True

    def cancel(self):
        print("Canceling...")
        self.is_cancelled = True
        # TODO send cancel/delete call to ComfyUI for all previously started prompts

def main(args):
    run = Run(args)
    run.execute()
