"""Registra las predicciones de animalitos del día (antes de los sorteos).

Lo corre ``.github/workflows/animalitos.yml`` de madrugada, después de
archivar los sorteos del día anterior: para cada lotería guarda en
``data/animalitos/predicciones.json`` lo que cada estrategia elegiría
hoy usando solo días anteriores. ``animalitos.evaluar_registro`` cruza
ese registro con lo que salió de verdad — es el seguimiento honesto
día a día de cada método.

Uso:
    python scripts/registrar_predicciones.py                # todas
    python scripts/registrar_predicciones.py lotto-activo   # solo una
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import animalitos  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("registrar_predicciones")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("loterias", nargs="*", help="slugs (por defecto, todas)")
    args = parser.parse_args()

    fallidas = 0
    for slug in args.loterias or list(animalitos.LOTERIAS):
        try:
            pred = animalitos.registrar_predicciones(slug)
        except animalitos.AnimalitosError as exc:
            logger.error("%s: %s", slug, exc)
            fallidas += 1
            continue
        logger.info(
            "%s: %d estrategias registradas (%s)",
            slug, len(pred),
            "; ".join(f"{e}={len(v)}" for e, v in pred.items()),
        )
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
