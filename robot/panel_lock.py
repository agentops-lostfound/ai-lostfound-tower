"""Process-lifetime advisory lock. Prevent duplicate panels before robot attach."""
from pathlib import Path


class PanelLock:
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.stream=path.open('a+b')
        self.stream.seek(0)
        if path.stat().st_size==0:self.stream.write(b'0');self.stream.flush()
        self.stream.seek(0)
        try:
            import os
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError('A control panel is already running. Use the existing window or close it first.') from None

    def close(self):
        self.stream.close()
