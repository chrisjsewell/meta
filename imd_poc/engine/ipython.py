from contextlib import contextmanager
from typing import List, Type, Union

import attr
from attr.validators import in_, instance_of
from nbconvert.preprocessors.execute import (
    ExecutePreprocessor,
    CellExecutionComplete,
    Empty,
)
import panflute as pf
import yaml

from .base import BaseEngine, EngineConfigInterface
from imd_poc.utils import mapping_to_dict

@attr.s(kw_only=True)
class IPythonConfig(EngineConfigInterface):

    kernel_name: str = attr.ib()
    shutdown_kernel: str = attr.ib(
        "graceful",
        in_(["graceful", "immediate"]),
        metadata={
            "help": (
                "If `graceful` (default), then the kernel is given time to clean up after executing all cells, "
                "e.g., to execute its `atexit` hooks. If `immediate`, then the kernel is signalled to immediately terminate."
            )
        },
    )
    store_widget_state: bool = attr.ib(
        True,
        instance_of(bool),
        metadata={
            "help": (
                "If `True` (default), then the state of the Jupyter widgets, "
                "created at the kernel, will be stored in the metadata of the notebook."
            )
        },
    )
    raise_on_iopub_timeout: bool = attr.ib(
        False,
        instance_of(bool),
        metadata={
            "help": (
                "If `False` (default), then the kernel will continue waiting for iopub messages, "
                "until it receives a kernel idle message, or until a timeout occurs, "
                "at which point the currently executing cell will be skipped. "
                "If `True`, then an error will be raised after the first timeout. "
                "This option generally does not need to be used, "
                "but may be useful in contexts where there is the possibility of executing notebooks with memory-consuming infinite loops."
            )
        },
    )

class IPythonEngine(BaseEngine):
    """A class, runs a programming kernel."""

    @classmethod
    def config_class(cls) -> Type[IPythonConfig]:
        return IPythonConfig

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._kernel = None

    def start(self, **kwargs):
        """Start the engine."""
        options = IPythonConfig(**kwargs)
        self._kernel = SourceExecuter()
        self._kernel.start_kernel()

    def stop(self):
        """Stop the engine."""
        if self._kernel is not None:
            self._kernel.stop_kernel()
        self._kernel = None

    def run_code(self, source_code: str) -> List[dict]:
        """Run some source code and return a predefined data structure for outputs."""
        if self._kernel is None:
            raise RuntimeError("the execution kernel has not been started")
        exec_reply, outputs = self._kernel.run_cell(source_code)
        # TODO how to handle exec_reply?
        return outputs


class SourceExecuter(ExecutePreprocessor):
    """This is a first stab at an executor that runs directly on source code."""

    def start_kernel(self):
        self._display_id_map = {}
        self.widget_state = {}
        self.widget_buffers = {}
        self.km, self.kc = self.start_new_kernel(cwd=None)
        return self.km, self.kc

    def stop_kernel(self):
        self.kc.stop_channels()
        self.km.shutdown_kernel(now=self.shutdown_kernel == "immediate")
        delattr(self, "km")
        delattr(self, "kc")

    def run_cell(self, source, cell_index=None):
        parent_msg_id = self.kc.execute(source)
        self.log.debug("Executing cell:\n%s", source)
        exec_reply = self._wait_for_reply(parent_msg_id)
        outputs = []
        self.clear_before_next_output = False

        while True:
            try:
                msg = self.kc.iopub_channel.get_msg(timeout=self.iopub_timeout)
            except Empty:
                self.log.warning("Timeout waiting for IOPub output")
                if self.raise_on_iopub_timeout:
                    raise RuntimeError("Timeout waiting for IOPub output")
                else:
                    break
            if msg["parent_header"].get("msg_id") != parent_msg_id:
                # not an output from our execution
                continue
            # Will raise CellExecutionComplete when completed
            try:
                self.process_message(msg, outputs, cell_index)
            except CellExecutionComplete:
                break

        return exec_reply, outputs

    def process_message(self, msg, outputs, cell_index):
        msg_type = msg["msg_type"]
        self.log.debug("msg_type: %s", msg_type)
        content = msg["content"]
        self.log.debug("content: %s", content)
        display_id = content.get("transient", {}).get("display_id", None)
        if display_id and msg_type in {
            "execute_result",
            "display_data",
            "update_display_data",
        }:
            self._update_display_id(display_id, msg)
        if msg_type == "status":
            if content["execution_state"] == "idle":
                raise CellExecutionComplete()
        elif msg_type.startswith("comm"):
            self.handle_comm_msg(outputs, msg, cell_index)
        # Check for remaining messages we don't process
        elif msg_type not in ["execute_input", "update_display_data"]:
            # Assign output as our processed "result"
            return self.output(outputs, msg, display_id, cell_index)
