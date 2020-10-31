import threading
from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum, auto
from queue import PriorityQueue
from typing import Any, Tuple, TypeVar, Union

from cmdq.base import (
    Command,
    CommandHandle,
    CommandProcessor,
    CommandProcessorHandle,
    Tags,
    logevent,
)

T = TypeVar("T")
U = TypeVar("U")
V = TypeVar("V")


class _Control(Enum):
    BREAK = auto()


class _ControlCommandHandle(CommandHandle[_Control, None]):
    pass


_Entry = Union[
    Tuple[CommandHandle[T, Any], Command[T, U, Any]], Tuple[CommandHandle[_Control, None], Any]
]


class Processor(CommandProcessor[T, U]):
    def __init__(self, name: str, cxt: U):
        self._name = name
        self._cxt = cxt
        self._entry = 1
        self._q: PriorityQueue[_Entry] = PriorityQueue()
        self._qevent = threading.Event()
        self._qexecutor = ThreadPoolExecutor(thread_name_prefix=name)
        self._qtask = self._qexecutor.submit(self._consume)

    def start(self) -> None:
        logevent("START", self)
        self._qevent.set()

    def pause(self) -> None:
        self._qevent.clear()

    def paused(self) -> bool:
        return not self._qevent.is_set()

    def join(self) -> None:
        logevent("JOIN", f"""{self} +{self._q.qsize()}+""")
        self._q.join()
        logevent("----", self)

    def halt(self) -> None:
        logevent("HALT", self)
        hcmd = _ControlCommandHandle(0, 0, _Control.BREAK)
        self._q.put((hcmd, _Control.BREAK))
        if self.paused():
            self.start()

        self._qexecutor.shutdown(wait=True)
        logevent("XXXX", self)

    def send(self, cmd: Command[T, U, V], pri: int = 50, tags: Tags = ()) -> CommandHandle[T, V]:
        hcmd = cmd.get_handle(pri, self._entry, tags, self._name)
        self._entry += 1
        self._q.put((hcmd, cmd))
        logevent("RCVD", hcmd)
        return hcmd

    def _consume(self) -> None:
        while self._qevent.wait():
            hcmd, cmd = self._q.get(block=True, timeout=None)

            if isinstance(cmd, _Control):
                logevent("CTRL", f"""{self} {cmd}""")
                if cmd == _Control.BREAK:
                    break

            logevent("EXEC", hcmd)
            try:
                cmd(hcmd, self._cxt)
            except Exception as ex:
                logevent("ERRR", hcmd, ex.__cause__)
            finally:
                logevent("DONE", f"""{hcmd} +{self._q.qsize()}+""")
                self._q.task_done()

    def __repr__(self) -> str:
        return f"""<Processor '{self._name}' total_entries={self._entry - 1} at {id(self)}>"""


class ProcessorHandle(CommandProcessorHandle[T, U]):
    @classmethod
    def factory(cls, cxt: U) -> CommandProcessor[T, U]:
        return Processor("Cmd", cxt)
