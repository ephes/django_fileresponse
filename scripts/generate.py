"""Regenerate nbdev exports in a disposable copy, optionally checking for drift."""

import argparse
from configparser import ConfigParser
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import nbformat


ROOT = Path(__file__).resolve().parents[1]


def generate(check=False, docs=False):
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        shutil.copytree(ROOT / "nbs", target / "nbs")
        # Old nb_black outputs contain JavaScript that nbconvert gives random
        # element IDs. Discard only that transient output in the disposable copy.
        for path in (target / "nbs").glob("*.ipynb"):
            notebook = nbformat.read(path, as_version=4)
            for cell in notebook.cells:
                if cell.cell_type == "code":
                    cell.outputs = [output for output in cell.outputs
                                    if "application/javascript" not in output.get("data", {})]
            nbformat.write(notebook, path)
        shutil.copy(ROOT / "settings.ini", target)
        (target / "fileresponse").mkdir()
        # These metadata files are maintained by the original nbdev toolchain.
        for name in ("__init__.py", "_nbdev.py"):
            shutil.copy(ROOT / "fileresponse" / name, target / "fileresponse")
        subprocess.run(
            [sys.executable, "-c", "from nbdev.export import notebook2script; notebook2script('*.ipynb')"],
            cwd=target / "nbs", check=True,
        )
        generated = [p.relative_to(target) for p in (target / "fileresponse").glob("*.py")
                     if p.name not in {"__init__.py", "_nbdev.py"}]
        # README conversion never executes notebook cells.
        subprocess.run(
            [sys.executable, "-c", "from nbdev.export2html import make_readme; make_readme()"],
            cwd=target, check=True,
        )
        generated.append(Path("README.md"))
        if docs:
            config = ConfigParser()
            config.read(target / "settings.ini")
            # The import name differs from the distribution/site name. Resolve
            # the interpolated site URL before changing the import name.
            baseurl = config["DEFAULT"]["doc_baseurl"]
            config["DEFAULT"]["lib_name"] = "fileresponse"
            config["DEFAULT"]["doc_baseurl"] = baseurl
            with (target / "settings.ini").open("w") as stream:
                config.write(stream)
            (target / "docs").mkdir(exist_ok=True)
            # Execute only nbdev's import/show_doc cells in API notebooks.
            # Demonstration notebooks (MinIO, downloads, sample project) are excluded.
            subprocess.run([sys.executable, "-c", """
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
from nbdev.export import find_default_export, read_nb
from nbdev.export2html import convert_nb
for path in sorted(Path('nbs').glob('*.ipynb')):
    if find_default_export(read_nb(path)['cells']):
        convert_nb(path)
convert_nb('nbs/index.ipynb', execute=False)
"""], cwd=target, check=True)
            generated.extend(p.relative_to(target) for p in (target / "docs").glob("*.html"))
        drift = []
        for relative in generated:
            contents = (target / relative).read_bytes()
            destination = ROOT / relative
            if check:
                if not destination.exists() or destination.read_bytes() != contents:
                    drift.append(str(relative))
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents)
        if drift:
            raise SystemExit("Generated files differ: " + ", ".join(sorted(drift)))
        print(f"{'Checked' if check else 'Generated'} {len(generated)} files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--docs", action="store_true", help="also render API HTML (requires a Jupyter kernel)")
    args = parser.parse_args()
    generate(check=args.check, docs=args.docs)
