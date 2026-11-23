import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    files = list(root.glob("*.py"))
    for directory in ("routers", "services", "utils", "tests"):
        files.extend((root / directory).rglob("*.py"))
    errors = []
    for path in sorted(files):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            errors.append(str(error))
    if errors:
        for error in errors:
            print(f"Syntax error: {error}")
        return 1
    print(f"Python syntax is valid ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
