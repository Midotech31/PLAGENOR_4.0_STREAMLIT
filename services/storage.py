import json, os
from threading import Lock

try:
    from filelock import FileLock
    _USE_FILELOCK = True
except ImportError:
    _USE_FILELOCK = False

_thread_lock = Lock()


def _flock(filepath):
    if _USE_FILELOCK:
        return FileLock(filepath + ".lock")
    class _NoLock:
        def __enter__(self): return self
        def __exit__(self, *a): pass
    return _NoLock()


def _ensure(filepath, default):
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)


def read_json(filepath, default=None):
    if default is None:
        default = []
    _ensure(filepath, default)
    with _thread_lock:
        with _flock(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)


def write_json(filepath, data):
    _ensure(filepath, data)
    with _thread_lock:
        with _flock(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)


def read_list(filepath):
    return read_json(filepath, [])

def write_list(filepath, data):
    write_json(filepath, data)

def read_dict(filepath):
    return read_json(filepath, {})

def write_dict(filepath, data):
    write_json(filepath, data)
