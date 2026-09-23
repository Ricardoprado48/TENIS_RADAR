"""CLI da Fase 11 (item 17): registra prospectivamente todas as
oportunidades ja classificadas pela Fase 10 que ainda nao foram registradas
para o forward test -- inclusive DESCARTAR (item 4).

Uso:

    python scripts/forward_register.py

Nao calcula stake, nao faz aposta, nao cria interface.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.forward import build  # noqa: E402


def main() -> int:
    result = build.register_day()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
