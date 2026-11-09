"""Archiva las reuniones nuevas y (opcional) reentrena el modelo.

Uso:
    python scripts/archivar.py              # solo archivar
    python scripts/archivar.py --entrenar   # archivar + reentrenar

Lo ejecuta cada semana la tarea de GitHub Actions
(``.github/workflows/archivar.yml``); también se puede correr a mano.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.archivo import sincronizar  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("archivar")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrenar", action="store_true", help="reentrenar el modelo")
    args = parser.parse_args()

    resumen = sincronizar()
    logger.info("Archivo: %s", resumen)

    if args.entrenar:
        from src import laboratorio
        from src.modelo import entrenar_desde_archivo

        modelo = entrenar_desde_archivo()
        logger.info(
            "Modelo reentrenado con %d carreras: %s",
            modelo.n_carreras, {k: round(v, 3) for k, v in modelo.pesos.items()},
        )
        resultado = laboratorio.evaluar_archivo()
        laboratorio.guardar(resultado)
        t = resultado["totales"]
        if t["carreras"]:
            logger.info(
                "Laboratorio: %d carreras · 1er pick %.0f%% (forma %.0f%%, azar %.0f%%)",
                t["carreras"], 100 * t["nuevo_1"] / t["carreras"],
                100 * t["actual_1"] / t["carreras"], 100 * t["azar_1"] / t["carreras"],
            )
    return 1 if resumen["errores"] and not resumen["nuevas"] else 0


if __name__ == "__main__":
    sys.exit(main())
