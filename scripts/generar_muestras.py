"""Genera datos de ejemplo sintéticos (no reales) en ``data/``.

Uso:  python scripts/generar_muestras.py

Crea:
- data/samples/gaveta_ejemplo.pdf  -- gaveta sintética de 2 carreras.
- data/enrichment/historial_ejemplo.csv -- historial sintético.
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tests.conftest import crear_pdf_gaveta  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HISTORIAL = [
    {"horse": "Relampago", "rating": "88", "starts": "12", "wins": "4", "last_finish": "2"},
    {"horse": "Trueno", "rating": "79", "starts": "8", "wins": "2", "last_finish": "1"},
    {"horse": "Cometa", "rating": "70", "starts": "3", "wins": "1", "last_finish": "4"},
    {"horse": "Vendaval", "rating": "82", "starts": "10", "wins": "0", "last_finish": "3"},
    {"horse": "Brisa", "rating": "91", "starts": "6", "wins": "5", "last_finish": "1"},
]


def main() -> None:
    samples = RAIZ / "data" / "samples"
    enrichment = RAIZ / "data" / "enrichment"
    samples.mkdir(parents=True, exist_ok=True)
    enrichment.mkdir(parents=True, exist_ok=True)

    pdf = crear_pdf_gaveta(samples / "gaveta_ejemplo.pdf")
    logger.info("PDF de ejemplo generado: %s", pdf)

    csv_path = enrichment / "historial_ejemplo.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(HISTORIAL[0]))
        writer.writeheader()
        writer.writerows(HISTORIAL)
    logger.info("CSV de ejemplo generado: %s", csv_path)


if __name__ == "__main__":
    main()
