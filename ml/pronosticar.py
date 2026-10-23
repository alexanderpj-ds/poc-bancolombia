"""Funcion importable para el modelo pyfunc de MLflow (`PronosticadorPanel('ml.pronosticar:pronosticar', ...)`).

Contrato del lab: `pronosticar(history, dates, *, modelo, contexto=None) -> DataFrame fechas x entidades` (>= 0, sin
NaN).

- Modelos del registro del lab (yml de lab/conf/experimentos: ML global, modelos de Santiago): `MODELS[modelo]`.
- Combinaciones (`familia: combinacion`, con o sin pesos congelados): se calculan aqui miembro a miembro con la
  misma aritmetica que `lab.forecasting.challengers.combination`, para poder pasar el contexto a los miembros.
- Ensambles congelados que no son `combinacion` (ml/conf/ensambles/<modelo>.yml: stacking por bloque y ponderado con
  factor de sesgo): miembros con el registro y la receta congelada (`ml.ensambles`).

Contexto (grupo `contexto`, V4; revision F2, hallazgo F2-02): los ML que lo usan lo reciben igual que en el arnes
(`ml.correr_ml.construir_contexto`: atributos del maestro vigente por entidad y matriz del objetivo hermano), que
`global_ml` corta en cada pseudo-origen. En el modelo registrado viaja como artefactos parquet
(`PronosticadorConContexto`); con `params={'usar_contexto': False}` se obtiene la variante sin contexto. El contexto
empaquetado llega hasta la ultima fecha de los datos al registrar: para historias posteriores hay que re-registrar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from lab.tracking.mlflow_tracking import PronosticadorPanel, a_matriz

ENSAMBLES_CONF = Path(__file__).resolve().parent / "conf" / "ensambles"
BLOQUES = {"bloque1": [1, 7], "bloque2": [8, 15]}
#: Nombres de los artefactos del contexto en el modelo registrado.
ARTEFACTOS = ("contexto_atributos", "contexto_cruzada")


def _yml(modelo: str) -> dict | None:
    from lab.forecasting.registry import EXPERIMENTS_DIR

    ruta = EXPERIMENTS_DIR / f"{modelo}.yml"
    return yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else None


def usa_contexto(modelo: str) -> bool:
    """True si el ML global `modelo` pide el grupo `contexto` (misma regla que `ml.correr_ml.usa_contexto`)."""
    from daas.forecasting import global_ml

    conf = _yml(modelo) or {}
    if conf.get("familia") != "ml_global":
        return False
    grupos = global_ml.resolver_grupos(conf.get("conjunto"), conf.get("grupos"), conf.get("entidad_categorica", False))
    return "contexto" in grupos


def es_ml_global(modelo: str) -> bool:
    """True si `modelo` es un ML global del lab (familia `ml_global`, la misma regla que `ml.correr_ml.familia`)."""
    return (_yml(modelo) or {}).get("familia") == "ml_global"


def hojas(modelo: str) -> list[str]:
    """Modelos hoja de `modelo` (recorre combinaciones y ensambles congelados); [modelo] si ya es hoja."""
    conf = _yml(modelo)
    ruta = ENSAMBLES_CONF / f"{modelo}.yml"
    if conf is not None and conf.get("familia") == "combinacion":
        miembros = conf["miembros"]
    elif ruta.exists():
        miembros = yaml.safe_load(ruta.read_text(encoding="utf-8"))["miembros"]
    else:
        return [modelo]
    return list(dict.fromkeys(h for m in miembros for h in hojas(m)))


def _miembro(history: pd.DataFrame, dates: pd.DatetimeIndex, modelo: str, contexto: dict | None,
             mascara: pd.DataFrame | None = None) -> pd.DataFrame:
    return pronosticar(history, dates, modelo=modelo, contexto=contexto, mascara=mascara).clip(lower=0.0)


def pronosticar(
    history: pd.DataFrame, dates: pd.DatetimeIndex, *, modelo: str, contexto: dict | None = None,
    mascara: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Pronostico de `modelo` (registro del lab, combinacion o ensamble congelado) para `dates`.

    `mascara` (escenario S2, `PronosticadorEscenario`): dias imputados de `history`; viaja a los ML globales en
    `contexto['mascara_imputacion']` igual que `imputacion.aplicar.con_imputacion` (DI-06). None = como antes.
    """
    from lab.forecasting.registry import MODELS

    ruta = ENSAMBLES_CONF / f"{modelo}.yml"
    conf = _yml(modelo)
    if conf is not None and conf.get("familia") == "combinacion":
        miembros, pesos = conf["miembros"], conf.get("pesos")
        if pesos is None:
            return sum(_miembro(history, dates, m, contexto, mascara) for m in miembros) / len(miembros)
        total = float(sum(pesos))
        return sum(p / total * _miembro(history, dates, m, contexto, mascara)
                   for m, p in zip(miembros, pesos, strict=True))
    if not ruta.exists():
        ctx = contexto if contexto is not None and usa_contexto(modelo) else None
        if mascara is not None and es_ml_global(modelo):
            ctx = {**(ctx or {}), "mascara_imputacion": mascara}
        if ctx is not None:
            return MODELS[modelo](history, dates, contexto=ctx).clip(lower=0.0)
        return MODELS[modelo](history, dates).clip(lower=0.0)
    spec = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    miembros = {m: _miembro(history, dates, m, contexto, mascara) for m in spec["miembros"]}
    if spec["tipo"] == "stacking":
        h = np.asarray((dates - history.index.max()).days)
        salida = pd.DataFrame(0.0, index=dates, columns=history.columns)
        for bloque, (a, b) in BLOQUES.items():
            filas = (h >= a) & (h <= b)
            for m, coef in spec["coeficientes"][bloque].items():
                salida.loc[filas] += coef * miembros[m].loc[filas]
        return salida.clip(lower=0.0)
    total = float(sum(spec["pesos"]))
    pond = sum(p / total * miembros[m] for m, p in zip(spec["miembros"], spec["pesos"], strict=True))
    return (pond * spec["factor_sesgo"]).clip(lower=0.0)


# --------------------------------------------------------------------------- #
# Contexto empaquetado en el modelo registrado                                 #
# --------------------------------------------------------------------------- #
def escribir_contexto(contexto: dict, carpeta: Path) -> dict[str, str]:
    """Guarda el contexto del arnes como parquet (entidades como texto, igual que la entrada del pyfunc)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    atributos = contexto["atributos"].copy()
    atributos.index = atributos.index.astype(str)
    atributos.index.name = "entidad"
    rutas = {ARTEFACTOS[0]: carpeta / "atributos.parquet", ARTEFACTOS[1]: carpeta / "cruzada.parquet"}
    atributos.to_parquet(rutas[ARTEFACTOS[0]])
    cruzada = contexto.get("cruzada")
    cruzada = pd.DataFrame(index=pd.DatetimeIndex([], name="fecha")) if cruzada is None else cruzada.copy()
    cruzada.columns = cruzada.columns.astype(str)
    cruzada.to_parquet(rutas[ARTEFACTOS[1]])
    return {k: str(v) for k, v in rutas.items()}


def leer_contexto(rutas: dict[str, str]) -> dict:
    """Inverso de `escribir_contexto`: {'atributos': DataFrame, 'cruzada': DataFrame o None}."""
    atributos = pd.read_parquet(rutas[ARTEFACTOS[0]])
    atributos.index.name = None
    cruzada = pd.read_parquet(rutas[ARTEFACTOS[1]])
    return {"atributos": atributos, "cruzada": cruzada if cruzada.shape[1] else None}


class PronosticadorConContexto(PronosticadorPanel):
    """`PronosticadorPanel` que pasa a `pronosticar` el contexto guardado como artefactos del modelo.

    Entrada y salida iguales a `PronosticadorPanel`; params: `horizonte` (15) y `usar_contexto` (True; False da la
    variante sin contexto, columnas NaN). El contexto no se serializa con el objeto: se lee en `load_context`.
    """

    def __init__(self, funcion: str, kwargs: dict | None = None):
        """Igual que `PronosticadorPanel`; el contexto se carga despues (`cargar_contexto` o `load_context`)."""
        super().__init__(funcion, kwargs)
        self._contexto = None

    def cargar_contexto(self, rutas: dict[str, str]) -> None:
        """Carga el contexto desde rutas locales (para la firma antes de registrar)."""
        self._contexto = leer_contexto(rutas)

    def load_context(self, context):
        """Resuelve la funcion y lee el contexto de los artefactos del modelo."""
        super().load_context(context)
        self._contexto = leer_contexto(context.artifacts)

    def __getstate__(self):
        """No serializa la funcion resuelta ni el contexto (viaja como artefactos)."""
        estado = super().__getstate__()
        estado["_contexto"] = None
        return estado

    def predict(self, context, model_input: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Pronostico fecha x entidad para `horizonte` dias, con el contexto empaquetado si `usar_contexto`."""
        params = params or {}
        horizonte = int(params.get("horizonte", 15))
        usar = bool(params.get("usar_contexto", True))
        historia = a_matriz(model_input) if {"fecha", "entidad", "y"} <= set(model_input.columns) else model_input
        historia = historia.dropna(axis=1, how="all")
        fechas = pd.date_range(historia.index.max() + pd.Timedelta(days=1), periods=horizonte, freq="D")
        contexto = self._contexto if usar else None
        return self._resolver()(historia, fechas, **self.kwargs, contexto=contexto).clip(lower=0.0)


# --------------------------------------------------------------------------- #
# Escenarios de la repeticion con imputacion (PARTE 5, DI-15)                  #
# --------------------------------------------------------------------------- #
#: Nombre del artefacto con los insumos del escenario (pickle de un dict; lo escribe `escribir_escenario`).
ARTEFACTO_ESCENARIO = "insumos_escenario"


def insumos_escenario(dataset: str, escenario: str, modelo: str, conf: dict) -> dict:
    """Insumos con los que se evaluo `modelo` en el escenario (mismos que `ml.correr_ml.insumos_escenario`).

    - `asof`: `imputacion.contexto_asof.construir_contexto_asof` sobre la matriz corregida (si alguna hoja usa V4):
      snapshots del maestro (M1/M2) o `cupo_max_suc` por fecha (M3), ciudad y matriz corregida del objetivo hermano.
    - `imputacion` (S2): argumentos de `imputacion.aplicar.imputar_historia` (ciudad, desinstalados, corruptos,
      calendario_dim, lectura `cero_real`), los de `ml.correr_ml.args_imputacion`.
    - `huellas`: de `ml/conf/adopcion_ml.yml`, `imputacion/conf/decision_ml.yml`, la eleccion congelada y la regla.
    """
    from imputacion import alcance_d1, aplicar, contexto_asof
    from imputacion import datos as datos_imp
    from imputacion import eleccion as elec

    from ml import adopcion
    from ml import correr_ml as cm

    if escenario not in ("S1", "S2"):
        raise ValueError(f"escenario no registrable: {escenario} (S1 o S2)")
    wide, attrs, correcciones = datos_imp.matriz_corregida(dataset, conf)
    asof = None
    if any(usa_contexto(h) for h in hojas(modelo)):
        asof = contexto_asof.construir_contexto_asof(dataset, wide, attrs, conf)
        asof["ciudad"] = asof["ciudad"].copy()
    imp = None
    if escenario == "S2":
        imp = cm.args_imputacion(dataset, wide, attrs, correcciones)
        imp["lectura"] = "cero_real"
    return {"dataset": dataset, "escenario": escenario, "modelo": modelo, "asof": asof, "imputacion": imp,
            "huellas": {"adopcion": adopcion.huella_regla()[:12], "decision_ml": alcance_d1.huella_decision()[:12],
                        "eleccion": aplicar.huella_eleccion(), "regla_imputacion": elec.huella_corta()}}


def escribir_escenario(insumos: dict, carpeta: Path) -> dict[str, str]:
    """Guarda los insumos del escenario como artefacto del modelo (pickle: conserva tipos e indices exactos)."""
    import pickle

    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "insumos_escenario.pkl"
    ruta.write_bytes(pickle.dumps(insumos, protocol=pickle.HIGHEST_PROTOCOL))
    return {ARTEFACTO_ESCENARIO: str(ruta)}


def leer_escenario(rutas: dict[str, str]) -> dict:
    """Inverso de `escribir_escenario` (artefacto propio del registro, escrito por `ml/registrar_mlflow.py`)."""
    import pickle

    return pickle.loads(Path(rutas[ARTEFACTO_ESCENARIO]).read_bytes())  # noqa: S301 (artefacto propio)


class PronosticadorEscenario(PronosticadorPanel):
    """Pyfunc de la variante evaluada en un escenario de la repeticion (S1 o S2; DI-15 del plan de imputacion).

    `predict` aplica, sobre la historia recibida (la matriz CORREGIDA <= origen, en formato largo), lo mismo que el
    arnes del escenario (`ml.correr_ml.envolver_escenario`):

    - S2: imputa una copia de la historia con `imputacion.aplicar.imputar_historia` (eleccion congelada, nada
      posterior al ultimo dia) y pasa la mascara a los ML globales (`contexto['mascara_imputacion']`);
    - V4: contexto "as of" al origen (`imputacion.contexto_asof.atributos_contexto`: ultimo snapshot del maestro
      <= origen, nunca el vigente) y matriz corregida del objetivo hermano;
    - luego `ml.pronosticar.pronosticar` (combinaciones y ensambles congelados miembro a miembro).

    Los insumos viajan como artefacto (`insumos_escenario`); la eleccion y la regla de imputacion son las del codigo
    empaquetado (`imputacion/conf`). El contexto llega hasta el corte de los datos al registrar.
    """

    def __init__(self, funcion: str, kwargs: dict | None = None):
        """Igual que `PronosticadorPanel`; los insumos se cargan despues (`cargar_contexto` o `load_context`)."""
        super().__init__(funcion, kwargs)
        self._insumos = None

    def cargar_contexto(self, rutas: dict[str, str]) -> None:
        """Carga los insumos desde rutas locales (para la firma antes de registrar)."""
        self._insumos = leer_escenario(rutas)

    def load_context(self, context):
        """Resuelve la funcion y lee los insumos de los artefactos del modelo."""
        super().load_context(context)
        self._insumos = leer_escenario(context.artifacts)

    def __getstate__(self):
        """No serializa la funcion resuelta ni los insumos (viajan como artefacto)."""
        estado = super().__getstate__()
        estado["_insumos"] = None
        return estado

    def predict(self, context, model_input: pd.DataFrame, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Pronostico fecha x entidad para `horizonte` dias con la variante del escenario."""
        from imputacion import aplicar
        from imputacion.contexto_asof import atributos_contexto

        horizonte = int((params or {}).get("horizonte", 15))
        historia = a_matriz(model_input) if {"fecha", "entidad", "y"} <= set(model_input.columns) else model_input
        historia = historia.dropna(axis=1, how="all")
        origen = historia.index.max()
        fechas = pd.date_range(origen + pd.Timedelta(days=1), periods=horizonte, freq="D")
        insumos = self._insumos
        contexto = None
        if insumos["asof"] is not None:  # con_contexto_asof (envoltura exterior en el arnes)
            contexto = {"atributos": atributos_contexto(insumos["asof"], origen, historia.columns),
                        "cruzada": insumos["asof"]["cruzada"]}
        entrada, mascara = historia, None
        if insumos["imputacion"] is not None:  # con_imputacion (misma alineacion)
            imputada, masc, _ = aplicar.imputar_historia(historia, insumos["dataset"], **insumos["imputacion"])
            entrada = imputada.reindex(index=historia.index, columns=historia.columns.astype(str))
            entrada.columns = historia.columns
            if masc.to_numpy().any():
                mascara = masc.reindex(index=historia.index, columns=historia.columns.astype(str))
                mascara = mascara.fillna(False).astype(bool)
                mascara.columns = historia.columns
        return self._resolver()(entrada, fechas, **self.kwargs, contexto=contexto, mascara=mascara).clip(lower=0.0)
