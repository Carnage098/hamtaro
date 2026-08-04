from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class AlreadyRunningError(RuntimeError):
    """Levée lorsqu'une autre instance utilise déjà le même volume."""


class RuntimeLock:
    """Verrou de processus conservé pendant toute l'exécution du bot."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")

        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                if file.tell() == 0:
                    file.write(b"0")
                    file.flush()
                file.seek(0)
                try:
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise AlreadyRunningError(
                        "Une autre instance Hamtaro utilise déjà ce verrou."
                    ) from error
            else:
                import fcntl

                try:
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise AlreadyRunningError(
                        "Une autre instance Hamtaro utilise déjà ce verrou."
                    ) from error

            file.seek(0)
            file.truncate()
            file.write(str(os.getpid()).encode("ascii"))
            file.flush()
            self._file = file
        except Exception:
            file.close()
            raise

    def release(self) -> None:
        file = self._file
        self._file = None
        if file is None:
            return

        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()

    def __enter__(self) -> "RuntimeLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
