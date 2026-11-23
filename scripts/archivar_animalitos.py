"""Archiva los sorteos de animalitos de los días terminados.

Uso:
    python scripts/archivar_animalitos.py                  # todas las loterías
    python scripts/archivar_animalitos.py lotto-activo     # solo una
    python scripts/archivar_animalitos.py --dias 30        # ventana más corta

Guarda ``data/animalitos/<slug>.json.gz`` (versionado en git) para que
la app cargue meses de historial sin pedir nada a la red. Lo ejecuta
cada día la tarea ``.github/workflows/animalitos.yml``; la primera vez
descarga ~6 meses por lotería (1 petición/segundo), luego solo el día
anterior.
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
logger = logging.getLogger("archivar_animalitos")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("loterias", nargs="*", help="slugs (por defecto, todas)")
    parser.add_argument("--dias", type=int, default=animalitos.DIAS_ARCHIVO)
    args = parser.parse_args()

    fallidas = 0
    for slug in args.loterias or list(animalitos.LOTERIAS):
        try:
            res = animalitos.actualizar_archivo(slug, args.dias)
        except animalitos.AnimalitosError as exc:
            logger.error("%s: %s", slug, exc)
            fallidas += 1
            continue
        logger.info(
            "%s: %d días nuevos, %d errores, %d días archivados",
            slug, res["nuevos"], res["errores"], res["dias"],
        )
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
