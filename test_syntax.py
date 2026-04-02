import ast
import sys

try:
    with open('main.py', 'r', encoding='utf-8') as f:
        source = f.read()
    
    # Try to parse
    ast.parse(source)
    print("✓ Python syntax is valid")
    sys.exit(0)
except SyntaxError as e:
    print(f"✗ Syntax error at line {e.lineno}:")
    print(f"  Message: {e.msg}")
    if e.text:
        print(f"  Code: {e.text.strip()[:80]}")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
