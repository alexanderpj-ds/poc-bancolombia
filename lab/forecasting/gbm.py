"""
Boosting global directo y sus contrastes (ridge, CatBoost).

Un solo modelo para todas las entidades, con el horizonte como variable. El boosting adoptado vive una sola
vez, en el pipeline; aquí quedan los contrastes.

Anti-fuga por construcción (reglas F1–F5 de docs/metodologia-valor.md):
- La función solo recibe `history` (datos <= origen). Los ejemplos de entrenamiento se arman con
  pseudo-orígenes s < origen: variables con datos <= s, objetivo en s+h; todo objetivo > origen no existe.
- No hay rezagos menores que el horizonte: las variables de nivel se calculan en s, nunca en s+h−1.
- Sin escaladores ni codificadores ajustados aparte: el objetivo se divide por el nivel de la propia
  entidad en s. El calendario es determinista (conocido de antemano).
- Sin parada temprana: no hay partición aleatoria interna de validación.

Los argumentos con nombre en español son las claves del yml del experimento (`conf/experimentos/`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from daas.forecasting.global_gbm import GROUPS, forecast_global_gbm  # noqa: F401
from daas.forecasting.global_gbm import calendar as build_calendar_features
from daas.forecasting.global_gbm import predict_gbm as predict_relative
from daas.forecasting.global_gbm import training_set as build_training_set

#: Variables que el modelo lineal trata como categorías (una columna por valor).
CATEGORICAL_FEATURES = ["h", "dow", "dia", "dias_desde_pago", "dias_hasta_pago"]


def ridge_global(
    history: pd.DataFrame,
    dates: pd.DatetimeIndex,
    *,
    grupos: list[str],
    alpha: float,
    paso_dias: int,
    meses_entrenamiento: int,
    dias_pago: list,
) -> pd.DataFrame:
    """
    Mismo conjunto y mismo objetivo relativo que `forecast_global_gbm`, con una regresión ridge.

    Contraste: mide cuánto de la ganancia es el calendario (lo captura un modelo lineal) y cuánto la
    no linealidad del boosting. El imputador y el codificador se ajustan dentro del `fit`, es decir,
    solo con ejemplos <= origen.
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    calendar = build_calendar_features(history.index.min(), dates.max(), tuple(dias_pago))
    columns = [variable for group in grupos for variable in GROUPS[group]]
    features, target, weights = build_training_set(
        history, len(dates), calendar, columns, paso_dias, meses_entrenamiento
    )
    categorical = [c for c in columns if c in CATEGORICAL_FEATURES]
    numeric = [c for c in columns if c not in CATEGORICAL_FEATURES]
    preprocessing = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("num", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), numeric),
        ]
    )

    model = make_pipeline(preprocessing, Ridge(alpha=alpha))
    model.fit(features, target, ridge__sample_weight=weights)
    return predict_relative(model, history, dates, calendar, columns)


def catboost_global(
    history: pd.DataFrame,
    dates: pd.DatetimeIndex,
    *,
    grupos: list[str],
    entidad_categorica: bool,
    paso_dias: int,
    meses_entrenamiento: int,
    dias_pago: list,
    cat: dict,
) -> pd.DataFrame:
    """
    Mismo conjunto y objetivo que `forecast_global_gbm`, con CatBoost y (opcional) la entidad como categórica.

    Anti-fuga de la codificación de la entidad con el objetivo: CatBoost usa estadísticas ordenadas.
    Los ejemplos se ordenan por fecha del objetivo y se pasa `has_time=True`, así cada ejemplo se
    codifica solo con objetivos de fechas anteriores o iguales, nunca con una permutación al azar.
    Todos los objetivos son <= origen, de modo que nada de la ventana de prueba entra a la codificación.
    """
    from catboost import CatBoostRegressor, Pool

    calendar = build_calendar_features(history.index.min(), dates.max(), tuple(dias_pago))
    columns = [variable for group in grupos for variable in GROUPS[group]] + (["entidad"] if entidad_categorica else [])
    features, target, weights = build_training_set(
        history,
        len(dates),
        calendar,
        columns + ["t_objetivo"],
        paso_dias,
        meses_entrenamiento
    )
    order = np.argsort(features["t_objetivo"].to_numpy(), kind="stable")
    categorical = ["entidad"] if entidad_categorica else []
    model = CatBoostRegressor(
        loss_function="RMSE",
        has_time=True,
        random_seed=0,
        verbose=False,
        allow_writing_files=False,
        **cat,
    )

    model.fit(Pool(
        features.iloc[order][columns],
        target[order],
        weight=weights[order],
        cat_features=categorical
    ))
    return predict_relative(model, history, dates, calendar, columns)
