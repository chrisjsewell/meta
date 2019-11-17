from abc import ABC, abstractmethod
from typing import List, Type

import attr
from attr.validators import instance_of, in_


@attr.s(kw_only=True)
class EngineConfigInterface:
    # The following configuration option should be handled outside the engine:
    # force_raise_errors
    # allow_errors
    # interrupt_on_timeout

    startup_timeout: int = attr.ib(
        60,
        instance_of(int),
        metadata={
            "help": (
                "The time to wait (in seconds) for the kernel to start. "
                "If kernel startup takes longer, a RuntimeError is raised."
            )
        },
    )
    timeout: int = attr.ib(
        30,
        instance_of(int),
        metadata={
            "help": (
                "The time to wait (in seconds) for output from executions. "
                "If a cell execution takes longer, an exception TimeoutError is raised. "
                "`None` or `-1` will disable the timeout."
            )
        },
    )
    # formerly iopub_timeout
    output_timeout: int = attr.ib(
        4,
        instance_of(int),
        metadata={
            "help": (
                "The time to wait (in seconds) for output. "
                "This generally doesn't need to be set, but on some slow networks (such as CI systems) "
                "the default timeout might not be long enough to get all messages."
            )
        },
    )


class BaseEngine(ABC):
    """An abstract class, to define an engine which runs a programming kernel."""

    @classmethod
    def config_class(cls) -> Type[EngineConfigInterface]:
        return EngineConfigInterface

    @abstractmethod
    def start(self, **kwargs):
        """Start the engine."""
        pass

    @abstractmethod
    def stop(self):
        """Stop the engine."""
        pass

    @abstractmethod
    def run_code(self, source_code: str) -> List[dict]:
        """Run some source code and return a predefined data structure for outputs.
        
        At the moment the format is that of the ipython_kernel outputs.
        """
        pass

