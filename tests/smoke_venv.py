"""Exercise an uninstalled skill in a fresh, pip-free environment and Unicode paths."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def main():
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="paper-shaper-") as directory:
        root = Path(directory) / "中文 project with spaces"
        root.mkdir()
        env = root / "isolated environment"
        venv.EnvBuilder(with_pip=False).create(env)
        python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        skill = root / "installed skill"
        for folder in ["scripts", "config", "references"]:
            shutil.copytree(source / folder, skill / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        script = skill / "scripts/framework.py"
        work = root / "paper work"
        material = root / "结果.txt"
        material.write_text("合成研究材料\r\n", encoding="utf-8-sig")
        calls = [("doctor",), ("init", str(work), "--project-root", str(root)),
                 ("attach", str(work), "--path", str(material), "--material-id", "result", "--start", "1", "--end", "1"),
                 ("packet", str(work)), ("doctor", str(work))]
        for arguments in calls:
            result = subprocess.run([str(python), str(script), *arguments], cwd=str(env),
                                    capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout)
            value = json.loads(result.stdout)
            if arguments[0] == "doctor":
                assert value["ok"] and Path(value["python"]["executable"]).resolve() == python.resolve()
                assert value["python"]["in_virtualenv"] and Path(value["python"]["prefix"]).resolve() == env.resolve()
            if arguments[0] == "packet":
                assert value["materials"][0]["content"] == "1: 合成研究材料"
        research = subprocess.run([str(python), str(skill / "scripts/research_map.py"), "index", "--root", str(root), "--scope", "结果.txt", "--out", str(root / "inventory.json")], cwd=str(env), capture_output=True, text=True, encoding="utf-8")
        if research.returncode:
            raise RuntimeError(research.stderr or research.stdout)
        assert json.loads(research.stdout)["files"] == 1
        print(json.dumps({"venv_smoke": "PASS", "python": sys.version.split()[0],
                          "installed_dependencies": [], "unicode_and_space_paths": True}))


if __name__ == "__main__":
    main()
