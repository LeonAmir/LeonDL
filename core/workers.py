"""Small thread and event primitives for backend workers."""
from __future__ import annotations

import logging
import threading


class _Event:
    def __init__(self):
        self._listeners = []

    def connect(self, callback):
        self._listeners.append(callback)

    def emit(self, *args):
        for callback in tuple(self._listeners):
            try:
                callback(*args)
            except Exception:
                logging.exception("Worker event callback failed")


class Signal:
    def __init__(self, *_types):
        pass

    def __set_name__(self, _owner, name):
        self.name = "__event_" + name

    def __get__(self, instance, _owner=None):
        if instance is None:
            return self
        return instance.__dict__.setdefault(self.name, _Event())


class Worker:
    finished = Signal()

    def __init__(self):
        self._thread = None
        self._interrupted = threading.Event()

    def start(self):
        if self.isRunning():
            return
        def execute():
            try:
                self.run()
            finally:
                self.finished.emit()
        self._interrupted.clear()
        self._thread = threading.Thread(target=execute, daemon=True, name=type(self).__name__)
        self._thread.start()

    def isRunning(self):
        return self._thread is not None and self._thread.is_alive()

    def requestInterruption(self):
        self._interrupted.set()

    def isInterruptionRequested(self):
        return self._interrupted.is_set()

    def wait(self, milliseconds=None):
        if self._thread is not None:
            self._thread.join(None if milliseconds is None else milliseconds / 1000)
        return not self.isRunning()
