"""Install each built distribution and run synthetic tests outside the checkout."""

import os
from pathlib import Path
import subprocess
import tempfile
import venv


ROOT = Path(__file__).resolve().parents[1]


def main():
    wheels = list((ROOT / "dist").glob("*.whl"))
    sources = list((ROOT / "dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit("Build exactly one wheel and one sdist in dist/ first")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    for artifact in wheels + sources:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            venv.EnvBuilder(with_pip=True).create(target / "venv")
            python = target / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            subprocess.run([str(python), "-m", "pip", "install", "--quiet", str(artifact)],
                           cwd=target, env=environment, check=True)
            subprocess.run([str(python), "-c", """
from pathlib import Path
import sys
import fileresponse.http
assert Path(fileresponse.http.__file__).is_relative_to(Path(sys.prefix))
"""], cwd=target, env=environment, check=True)
            subprocess.run([str(python), "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"],
                           cwd=target, env=environment, check=True)
        print(f"Installed package tests passed: {artifact.name}", flush=True)


if __name__ == "__main__":
    main()
