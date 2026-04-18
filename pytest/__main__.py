from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    root = Path.cwd()
    test_files = sorted((root / "tests").glob("test_*.py"))
    failures = 0
    total = 0

    for test_file in test_files:
        module = _load_module(test_file)
        for name, func in sorted(vars(module).items()):
            if not name.startswith("test_") or not callable(func):
                continue
            total += 1
            try:
                _run_test(func)
            except Exception:
                failures += 1
                traceback.print_exc()

    if failures:
        if "-q" not in sys.argv[1:]:
            print(f"{failures} failed, {total - failures} passed")
        return 1

    if "-q" not in sys.argv[1:]:
        print(f"{total} passed")
    return 0


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def _run_test(func):
    signature = inspect.signature(func)
    if not signature.parameters:
        return func()
    kwargs = {}
    temp_dir: TemporaryDirectory[str] | None = None
    if set(signature.parameters) == {"tmp_path"}:
        temp_dir = TemporaryDirectory()
        kwargs["tmp_path"] = Path(temp_dir.name)
    try:
        return func(**kwargs)
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
