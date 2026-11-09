"""Módulo 10 — Modelo entrenado (logit condicional / Harville generalizado).

Cada caballo ``i`` de una carrera tiene un vector de características
``x_i`` (estandarizadas dentro de la carrera) y una fuerza
``s_i = exp(w · x_i)``. La probabilidad de ganar es la de Harville:

    P(i gana) = exp(w · x_i) / Σ_j exp(w · x_j)

Los pesos ``w`` se aprenden maximizando la verosimilitud de los
ganadores reales del archivo histórico (método de Newton con
regularización L2). Solo se usa información **anterior** a cada
carrera: el historial que trae la gaceta y las estadísticas de jinetes
y entrenadores calculadas con fechas estrictamente previas.

Características (todas "más alto = mejor"):
- ``forma``: log de la fuerza por forma (victorias del año + cuerpos).
- ``tiempo``: segundos perdidos frente al ganador (media últimas 3), negado.
- ``llegada``: puesto de llegada medio en las últimas 4, negado.
- ``jinete`` / ``entrenador``: tasa de victorias suavizada previa.
- ``distancia``: diferencia con la distancia más parecida corrida, negada.
- ``descanso``: log(1 + días desde su última carrera).
- ``debut``: 1 si no tiene actuaciones previas.
- ``kilos``: kilos de hoy − kilos de su última carrera, negado.
- ``puesto``: puesto de salida relativo (1 = por dentro), negado.
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.harville_model import form_strength

logger = logging.getLogger(__name__)

MODELO_PATH = Path(__file__).resolve().parent.parent / "data" / "modelo.json"
CARACTERISTICAS = (
    "forma", "tiempo", "llegada", "jinete", "entrenador",
    "distancia", "descanso", "debut", "kilos", "puesto",
)
# Punto de partida del entrenamiento (prior): forma + tiempos + jinete.
# Elegido con el laboratorio sobre 86 carreras (sep-nov 2026); con tan
# pocos datos la mejora frente al modelo de forma es pequeña y debe
# revalidarse a medida que crezca el archivo.
PESOS_PREVIOS = {"forma": 0.5, "tiempo": 0.3, "jinete": 0.15}
L2_DEFECTO = 10.0
NOMBRES = {
    "forma": "Forma del año",
    "tiempo": "Tiempo vs. ganador",
    "llegada": "Llegadas recientes",
    "jinete": "Efectividad del jinete",
    "entrenador": "Efectividad del entrenador",
    "distancia": "Conoce la distancia",
    "descanso": "Días de descanso",
    "debut": "Debutante",
    "kilos": "Cambio de kilos",
    "puesto": "Puesto de salida",
}


# ------------------------------------------------------------------ utilidades


def _num(texto: Any) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", str(texto or ""))
    return float(match.group().replace(",", ".")) if match else None


def tiempo_a_segundos(texto: Any) -> float | None:
    """Convierte tiempos venezolanos en quintos: ``"74.3"`` = 74 s + 3/5."""
    match = re.fullmatch(r"\s*(\d+)(?:[.,](\d))?\s*", str(texto or ""))
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2) or 0) / 5


def normalizar_nombre(nombre: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.\-,]", " ", str(nombre or "").upper())).strip()


def _fecha(texto: Any) -> date | None:
    try:
        return date.fromisoformat(str(texto)[:10])
    except ValueError:
        return None


# ------------------------------------------------- estadísticas de personas


class EstadisticasPersonas:
    """Victorias/montas de jinetes y entrenadores consultables por fecha.

    ``tasa(tipo, nombre, antes_de)`` usa solo eventos con fecha
    estrictamente anterior, para no filtrar el resultado a predecir.
    """

    def __init__(self) -> None:
        self._eventos: dict[tuple[str, str], list[tuple[date, int]]] = {}
        self._vistos: set[tuple[str, str, str]] = set()
        self._indice: dict[tuple[str, str], tuple[list[date], list[int]]] | None = None

    def agregar(self, tipo: str, nombre: Any, fecha: date | None, gano: bool, clave: str) -> None:
        nombre = normalizar_nombre(nombre)
        if not nombre or fecha is None or (tipo, nombre, clave) in self._vistos:
            return
        self._vistos.add((tipo, nombre, clave))
        self._eventos.setdefault((tipo, nombre), []).append((fecha, int(gano)))
        self._indice = None

    def _construir(self) -> None:
        self._indice = {}
        for llave, eventos in self._eventos.items():
            eventos.sort()
            fechas = [f for f, _ in eventos]
            acumulado = list(np.cumsum([g for _, g in eventos]))
            self._indice[llave] = (fechas, acumulado)

    def tasa(self, tipo: str, nombre: Any, antes_de: date) -> float | None:
        """Tasa de victorias suavizada ``(v + 1) / (n + 10)`` o ``None``."""
        if self._indice is None:
            self._construir()
        datos = self._indice.get((tipo, normalizar_nombre(nombre)))
        if not datos:
            return None
        fechas, acumulado = datos
        n = bisect.bisect_left(fechas, antes_de)
        if n == 0:
            return None
        return (acumulado[n - 1] + 1) / (n + 10)

    def agregar_registros(self, registros: list[dict[str, Any]]) -> None:
        """Añade resultados e historiales de una reunión (sin duplicar
        actuaciones ya vistas: clave = caballo + fecha)."""
        for r in registros:
            fecha = _fecha(r.get("date"))
            if r.get("finish_position") and fecha:
                clave = f"{r['horse_name']}|{fecha}"
                self.agregar("jinete", r.get("jockey"), fecha, r["finish_position"] == 1, clave)
                self.agregar("entrenador", r.get("trainer"), fecha, r["finish_position"] == 1, clave)
            for h in r.get("history") or []:
                fh = _fecha(h.get("Fecha"))
                if h.get("Llegada") and fh:
                    self.agregar(
                        "jinete", h.get("Jinete"), fh, h["Llegada"] == 1, f"{r['horse_name']}|{fh}"
                    )

    @classmethod
    def desde_registros(cls, reuniones_registros: list[list[dict[str, Any]]]) -> "EstadisticasPersonas":
        """Construye las estadísticas a partir de registros de varias reuniones."""
        stats = cls()
        for registros in reuniones_registros:
            stats.agregar_registros(registros)
        return stats


# ------------------------------------------------------------ características


def caracteristicas(
    caballo: dict[str, Any], tamano: int, stats: EstadisticasPersonas | None
) -> dict[str, float | None]:
    """Características crudas de un caballo (``None`` = sin dato)."""
    fecha = _fecha(caballo.get("date")) or date.today()
    historial = [h for h in caballo.get("history") or [] if (_fecha(h.get("Fecha")) or fecha) < fecha]
    historial.sort(key=lambda h: h.get("Fecha") or "")

    fuerza = form_strength(caballo.get("year_wins"), caballo.get("year_starts"), caballo.get("lengths_behind"))
    perdidas = [
        tiempo_a_segundos(h.get("Tiempo")) - tiempo_a_segundos(h.get("Tiempo ganador"))
        for h in historial
        if tiempo_a_segundos(h.get("Tiempo")) is not None
        and tiempo_a_segundos(h.get("Tiempo ganador")) is not None
    ]
    llegadas = [h["Llegada"] for h in historial if h.get("Llegada")]
    distancias = [_num(h.get("Dist.")) for h in historial if _num(h.get("Dist."))]
    ultima = _fecha(historial[-1].get("Fecha")) if historial else None
    kilos_previos = _num(historial[-1].get("Kg")) if historial else None
    puesto = caballo.get("post_position")

    return {
        "forma": math.log(fuerza) if fuerza else None,
        "tiempo": -statistics.mean(perdidas[-3:]) if perdidas else None,
        "llegada": -statistics.mean(llegadas[-4:]) if llegadas else None,
        "jinete": stats.tasa("jinete", caballo.get("jockey"), fecha) if stats else None,
        "entrenador": stats.tasa("entrenador", caballo.get("trainer"), fecha) if stats else None,
        "distancia": (
            -min(abs(d - caballo["distance"]) for d in distancias) / 100
            if distancias and caballo.get("distance") else None
        ),
        "descanso": math.log1p((fecha - ultima).days) if ultima else None,
        "debut": 0.0 if historial else 1.0,
        "kilos": (
            -(caballo["weight"] - kilos_previos)
            if caballo.get("weight") and kilos_previos else None
        ),
        "puesto": -(puesto / tamano) if puesto and tamano else None,
    }


def matriz_carrera(caballos: list[dict[str, Any]], stats: EstadisticasPersonas | None) -> np.ndarray:
    """Matriz (caballos × características) estandarizada dentro de la carrera.

    Los datos faltantes quedan en 0 (= promedio de la carrera).
    """
    crudas = [caracteristicas(c, len(caballos), stats) for c in caballos]
    columnas = []
    for nombre in CARACTERISTICAS:
        valores = [f[nombre] for f in crudas]
        conocidos = [v for v in valores if v is not None]
        if len(conocidos) < 2:
            columnas.append([0.0] * len(valores))
            continue
        media = statistics.mean(conocidos)
        desv = statistics.pstdev(conocidos) or 1.0
        columnas.append([0.0 if v is None else (v - media) / desv for v in valores])
    return np.array(columnas, dtype=float).T


def _softmax(u: np.ndarray) -> np.ndarray:
    e = np.exp(u - u.max())
    return e / e.sum()


# --------------------------------------------------------------------- modelo


@dataclass
class Modelo:
    """Pesos del logit condicional y metadatos del entrenamiento."""

    pesos: dict[str, float]
    n_carreras: int = 0
    entrenado: str = ""
    hasta: str = ""  # fecha ISO de la reunión más reciente usada al entrenar
    caracteristicas: tuple[str, ...] = field(default=CARACTERISTICAS)

    def vector(self) -> np.ndarray:
        return np.array([self.pesos.get(c, 0.0) for c in CARACTERISTICAS])

    def guardar(self, ruta: str | Path = MODELO_PATH) -> None:
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        Path(ruta).write_text(
            json.dumps(
                {"pesos": self.pesos, "n_carreras": self.n_carreras,
                 "entrenado": self.entrenado, "hasta": self.hasta},
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def cargar(cls, ruta: str | Path = MODELO_PATH) -> "Modelo | None":
        try:
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return cls(pesos=datos["pesos"], n_carreras=datos.get("n_carreras", 0),
                   entrenado=datos.get("entrenado", ""), hasta=datos.get("hasta", ""))


def carreras_entrenables(registros: list[dict[str, Any]]) -> list[tuple[list[dict], int]]:
    """``[(caballos, índice_del_ganador)]`` de las carreras con ganador único."""
    carreras: dict[Any, list[dict]] = {}
    for r in registros:
        carreras.setdefault(r.get("race_number"), []).append(r)
    salida = []
    for caballos in carreras.values():
        ganadores = [i for i, c in enumerate(caballos) if c.get("finish_position") == 1]
        if len(ganadores) == 1 and len(caballos) >= 2:
            salida.append((caballos, ganadores[0]))
    return salida


def _prior(previo: dict[str, float] | None) -> np.ndarray:
    previo = PESOS_PREVIOS if previo is None else previo
    return np.array([previo.get(c, 0.0) for c in CARACTERISTICAS])


def entrenar(
    ejemplos: list[tuple[np.ndarray, int]],
    l2: float = L2_DEFECTO,
    iteraciones: int = 25,
    previo: dict[str, float] | None = None,
) -> np.ndarray:
    """Ajusta ``w`` por Newton-Raphson maximizando la log-verosimilitud
    de los ganadores con penalización ``l2 · ||w − w₀||²``.

    ``w₀`` (``PESOS_PREVIOS``) parte del modelo de forma original: con
    pocos datos el modelo se parece a él y se aleja a medida que el
    archivo histórico crece.
    """
    k = len(CARACTERISTICAS)
    w0 = _prior(previo)
    w = w0.copy()
    for _ in range(iteraciones):
        grad = -2 * l2 * (w - w0)
        hess = -2 * l2 * np.eye(k)
        for x, ganador in ejemplos:
            p = _softmax(x @ w)
            media = p @ x
            grad += x[ganador] - media
            hess -= (x * p[:, None]).T @ x - np.outer(media, media)
        paso = np.linalg.solve(hess, grad)
        w -= paso
        if np.abs(paso).max() < 1e-6:
            break
    return w


def preparar_ejemplos(
    reuniones_registros: list[list[dict[str, Any]]], stats: EstadisticasPersonas
) -> list[tuple[np.ndarray, int]]:
    return [
        (matriz_carrera(caballos, stats), ganador)
        for registros in reuniones_registros
        for caballos, ganador in carreras_entrenables(registros)
    ]


def ajustar(reuniones_registros: list[list[dict[str, Any]]], l2: float = L2_DEFECTO) -> Modelo:
    """Entrena un ``Modelo`` con todas las carreras corridas dadas."""
    stats = EstadisticasPersonas.desde_registros(reuniones_registros)
    ejemplos = preparar_ejemplos(reuniones_registros, stats)
    w = entrenar(ejemplos, l2=l2) if ejemplos else _prior(None)
    fechas = [r.get("date") for regs in reuniones_registros for r in regs if r.get("date")]
    return Modelo(
        pesos={c: float(v) for c, v in zip(CARACTERISTICAS, w)},
        n_carreras=len(ejemplos),
        entrenado=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        hasta=max(fechas) if fechas else "",
    )


def entrenar_desde_archivo(ruta: str | Path = MODELO_PATH) -> Modelo:
    """Reentrena con todo el archivo histórico y guarda los pesos."""
    from src.archivo import cargar_todas
    from src.gaceta_web import meeting_to_records

    reuniones = [meeting_to_records(d) for d in cargar_todas()]
    modelo = ajustar(reuniones)
    modelo.guardar(ruta)
    return modelo


# ------------------------------------------------------------------ predictor


class Predictor:
    """Modelo + estadísticas de personas listas para predecir."""

    def __init__(self, modelo: Modelo, stats: EstadisticasPersonas) -> None:
        self.modelo = modelo
        self.stats = stats

    def incorporar(self, registros: list[dict[str, Any]]) -> None:
        """Añade a las estadísticas el historial de la reunión que se analiza
        (las consultas siguen usando solo fechas anteriores)."""
        self.stats.agregar_registros(registros)

    def aplica(self, caballos: list[dict[str, Any]]) -> bool:
        """El modelo necesita datos de la gaceta web (historial/estadística)."""
        return any("history" in c or c.get("year_starts") is not None for c in caballos)

    def probabilidades(self, caballos: list[dict[str, Any]]) -> list[float]:
        x = matriz_carrera(caballos, self.stats)
        return list(_softmax(x @ self.modelo.vector()))

    def explicar(self, caballos: list[dict[str, Any]], indice: int) -> list[tuple[str, float]]:
        """Aporte de cada característica a la fuerza del caballo ``indice``
        (positivo = a favor), ordenado por importancia."""
        x = matriz_carrera(caballos, self.stats)[indice]
        aportes = [(NOMBRES[c], float(v * self.modelo.pesos.get(c, 0.0)))
                   for c, v in zip(CARACTERISTICAS, x)]
        return sorted((a for a in aportes if abs(a[1]) > 0.01), key=lambda a: -abs(a[1]))

    @classmethod
    def desde_archivo(cls, ruta_modelo: str | Path = MODELO_PATH) -> "Predictor | None":
        from src.archivo import cargar_todas
        from src.gaceta_web import meeting_to_records

        modelo = Modelo.cargar(ruta_modelo)
        if modelo is None:
            return None
        stats = EstadisticasPersonas.desde_registros(
            [meeting_to_records(d) for d in cargar_todas()]
        )
        return cls(modelo, stats)
