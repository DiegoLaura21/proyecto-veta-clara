"""Evalúa el sensor ficticio Veta Clara a partir del libro de datos sintéticos."""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter
import numpy as np
import pandas as pd


RAIZ = Path(__file__).resolve().parents[1]
METALES = {"zn": "Zinc", "pb": "Plomo"}
METODOS = {
    "directo": "Lectura directa",
    "sesgo": "Corrección de sesgo",
    "contexto": "Regresión contextual",
}
COLORES = {"directo": "#a35036", "sesgo": "#31718d", "contexto": "#18775e"}
TINTA = "#19352d"
FAJAS = {"Faja Este": "#347594", "Faja Oeste": "#268569"}
TURNOS = {"Día": "#4d9680", "Noche": "#435176"}
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
COLUMNAS_LOTES = [
    "id_lote", "fecha_hora", "faja", "turno", "masa_t", "humedad_pct",
    "horas_desde_calibracion", "zn_sensor_pct", "pb_sensor_pct",
]
COLUMNAS_LAB = ["id_lote", "fecha_informe", "zn_lab_pct", "pb_lab_pct"]


def cargar_datos(ruta):
    lotes = pd.read_excel(ruta, sheet_name="Lotes", usecols=COLUMNAS_LOTES)
    lab = pd.read_excel(ruta, sheet_name="Laboratorio", usecols=COLUMNAS_LAB)
    for tabla, fecha, numericas in (
        (lotes, "fecha_hora", COLUMNAS_LOTES[4:]),
        (lab, "fecha_informe", COLUMNAS_LAB[2:]),
    ):
        if tabla.empty or tabla.isna().any().any() or tabla["id_lote"].duplicated().any():
            raise ValueError(f"Revisa filas vacías, campos faltantes o ID duplicados en {fecha}.")
        tabla[fecha] = pd.to_datetime(tabla[fecha], errors="raise")
        tabla[numericas] = tabla[numericas].apply(pd.to_numeric, errors="raise")
        valores = tabla[numericas].to_numpy()
        if not np.isfinite(valores).all() or (valores < 0).any():
            raise ValueError(f"Hay valores no finitos o negativos en {fecha}.")
    if not lotes["faja"].isin(FAJAS).all() or not lotes["turno"].isin(TURNOS).all():
        raise ValueError("Se encontraron fajas o turnos fuera del diccionario del libro.")
    if not lab["id_lote"].isin(lotes["id_lote"]).all():
        raise ValueError("Hay ensayos sin un lote correspondiente.")
    pares = lotes.merge(lab, on="id_lote", how="inner", validate="one_to_one")
    if (pares["fecha_informe"] < pares["fecha_hora"]).any():
        raise ValueError("Hay informes registrados antes de la lectura del lote.")
    lotes = lotes.sort_values(["fecha_hora", "id_lote"]).reset_index(drop=True)
    return lotes, pares.sort_values(["fecha_hora", "id_lote"]).reset_index(drop=True)


def variables_contexto(datos, metal):
    """Incluye únicamente variables disponibles al medir el lote."""
    return np.column_stack([
        np.ones(len(datos)),
        datos[f"{metal}_sensor_pct"],
        datos["humedad_pct"] - 7,
        datos["horas_desde_calibracion"],
        datos["faja"].eq("Faja Oeste").astype(int),
    ])


def evaluar(pares, corte):
    antes = pares["fecha_hora"] < corte
    disponible = pares["fecha_informe"] < corte
    ajuste = pares.loc[antes & disponible]
    prueba = pares.loc[~antes].copy()
    diferidos = int((antes & ~disponible).sum())
    if len(ajuste) < 10 or prueba.empty:
        raise ValueError("El corte debe dejar al menos 10 ensayos disponibles para ajuste y uno para prueba.")

    metricas = []
    coeficientes = []
    for metal, nombre in METALES.items():
        sensor = f"{metal}_sensor_pct"
        referencia = f"{metal}_lab_pct"
        sesgo = float((ajuste[sensor] - ajuste[referencia]).mean())
        coef, _, rango, _ = np.linalg.lstsq(
            variables_contexto(ajuste, metal), ajuste[referencia], rcond=None
        )
        if rango < len(coef):
            raise ValueError(f"Las variables de ajuste de {nombre} no tienen rango completo.")
        coeficientes.append(dict(zip(
            ["metal", "sesgo_bruto_pp", "intercepto", "lectura_sensor",
             "humedad_centrada", "horas_desde_calibracion", "faja_oeste"],
            [nombre, sesgo, *coef],
        )))
        estimaciones = {
            "directo": prueba[sensor],
            "sesgo": np.maximum(0, prueba[sensor] - sesgo),
            "contexto": np.maximum(0, variables_contexto(prueba, metal) @ coef),
        }
        for metodo, estimacion in estimaciones.items():
            error = estimacion - prueba[referencia]
            prueba[f"{metal}_{metodo}_pct"] = estimacion
            prueba[f"{metal}_{metodo}_error_pp"] = error
            metricas.append({
                "metal": nombre,
                "metodo": METODOS[metodo],
                "n_ajuste": len(ajuste),
                "n_prueba": len(prueba),
                "sesgo_pp": error.mean(),
                "mae_pp": error.abs().mean(),
                "rmse_pp": np.sqrt(error.pow(2).mean()),
            })
    return prueba, pd.DataFrame(metricas), pd.DataFrame(coeficientes), len(ajuste), diferidos


def estilo():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "figure.facecolor": "#f3f6f4",
        "axes.facecolor": "#ffffff",
        "text.color": TINTA,
        "axes.labelcolor": TINTA,
        "axes.titlecolor": TINTA,
        "axes.edgecolor": "#ccd9d2",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#e1ebe5",
        "grid.linewidth": 0.8,
        "xtick.color": "#405c52",
        "ytick.color": "#405c52",
        "legend.frameon": False,
        "savefig.dpi": 155,
        "axes.formatter.use_locale": False,
    })


def decimal(valor, decimales=2):
    return f"{valor:,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", " ")


def eje_decimal(decimales):
    return FuncFormatter(lambda valor, _: decimal(valor, decimales))


def encabezado(fig, titulo, subtitulo):
    fig.text(0.071, 0.955, titulo, fontsize=22, weight="bold", va="top")
    fig.text(0.073, 0.883, subtitulo, color="#45665a", va="top", fontsize=10)


def guardar(fig, ruta):
    fig.savefig(ruta, facecolor=fig.get_facecolor())
    plt.close(fig)


def grafico_operacion(lotes, ruta):
    datos = lotes.assign(dia=lotes["fecha_hora"].dt.normalize())
    diario = datos.pivot_table(
        index="dia", columns="faja", values="masa_t", aggfunc="sum", fill_value=0
    )
    calendario = pd.date_range(diario.index.min(), diario.index.max(), freq="D")
    diario = diario.reindex(index=calendario, columns=list(FAJAS), fill_value=0)
    conteo = pd.crosstab(datos["dia"].dt.dayofweek, datos["turno"])
    conteo = conteo.reindex(index=range(7), columns=list(TURNOS), fill_value=0)
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12.3, 5.2), gridspec_kw={"width_ratios": [1.45, 1]})
    fig.subplots_adjust(left=0.073, right=0.967, bottom=0.17, top=0.76, wspace=0.29)
    encabezado(
        fig, "Operación de las fajas",
        f"{decimal(len(lotes), 0)} lotes · {decimal(lotes['masa_t'].sum(), 0)} t · Datos sintéticos",
    )
    for faja, color in FAJAS.items():
        ax.plot(diario.index, diario[faja], color=color, label=faja, linewidth=1.8)
    ax.set(title="Toneladas diarias por faja", ylabel="Toneladas", xlabel="Fecha")
    localizador = mdates.AutoDateLocator(minticks=4, maxticks=7)
    ax.xaxis.set_major_locator(localizador)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.yaxis.set_major_formatter(eje_decimal(0))
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper right")
    for i, (turno, color) in enumerate(TURNOS.items()):
        bx.bar(np.arange(7) + (i - 0.5) * 0.36, conteo[turno], width=0.36, color=color, label=turno)
    bx.set(title="Lotes por día de la semana y turno", ylabel="Lotes", xlabel="Día de la semana")
    bx.set_xticks(np.arange(7), DIAS)
    bx.yaxis.set_major_formatter(eje_decimal(0))
    bx.legend(loc="upper right")
    for eje in (ax, bx):
        eje.grid(axis="x", visible=False)
    guardar(fig, ruta)


def grafico_concordancia(prueba, ruta):
    fig, ejes = plt.subplots(1, 2, figsize=(11.3, 5.5))
    fig.subplots_adjust(left=0.085, right=0.962, bottom=0.16, top=0.76, wspace=0.31)
    encabezado(
        fig, "Lecturas frente al laboratorio",
        f"{decimal(len(prueba), 0)} lotes en prueba · La diagonal indica concordancia perfecta",
    )
    for ax, (metal, nombre) in zip(ejes, METALES.items()):
        lab = prueba[f"{metal}_lab_pct"]
        columnas = ["directo", "contexto"]
        limite = max(lab.max(), *(prueba[f"{metal}_{m}_pct"].max() for m in columnas)) * 1.04
        ax.plot([0, limite], [0, limite], color="#50655e", linestyle="--", linewidth=1.1)
        for metodo in columnas:
            ax.scatter(lab, prueba[f"{metal}_{metodo}_pct"], s=16, alpha=0.39,
                       color=COLORES[metodo], label=METODOS[metodo], edgecolors="none")
        ax.set(title=nombre, xlabel="Ley de laboratorio (%)", ylabel="Ley estimada (%)",
               xlim=(0, limite), ylim=(0, limite), aspect="equal")
        ax.xaxis.set_major_formatter(eje_decimal(1))
        ax.yaxis.set_major_formatter(eje_decimal(1))
    ejes[0].legend(loc="upper left", markerscale=1.6)
    guardar(fig, ruta)


def grafico_metricas(metricas, ruta):
    fig, ejes = plt.subplots(1, 2, figsize=(12.3, 5.6))
    fig.subplots_adjust(left=0.073, right=0.967, bottom=0.22, top=0.76, wspace=0.26)
    encabezado(fig, "Error por método de calibración",
               "Mismos lotes de prueba · Error = estimación menos ensayo · Unidades en puntos porcentuales")
    posiciones = np.arange(3)
    ancho = 0.24
    for ax, nombre in zip(ejes, METALES.values()):
        datos = metricas.loc[metricas["metal"].eq(nombre)].set_index("metodo")
        minimo = min(0, datos["sesgo_pp"].min())
        maximo = datos["rmse_pp"].max()
        ax.set_ylim(minimo - maximo * 0.23, maximo * 1.22)
        ax.axhline(0, color="#678075", linewidth=0.9)
        for i, (metodo, etiqueta) in enumerate(METODOS.items()):
            fila = datos.loc[etiqueta, ["sesgo_pp", "mae_pp", "rmse_pp"]]
            barras = ax.bar(posiciones + (i - 1) * ancho, fila, ancho * 0.91,
                            label=etiqueta, color=COLORES[metodo])
            ax.bar_label(barras, [decimal(v, 3) for v in fila], padding=3, fontsize=8)
        ax.set(title=nombre, ylabel="Puntos porcentuales")
        ax.set_xticks(posiciones, ["Sesgo", "MAE", "RMSE"])
        ax.yaxis.set_major_formatter(eje_decimal(2))
        ax.grid(axis="x", visible=False)
    fig.legend(*ejes[0].get_legend_handles_labels(), loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, 0.042))
    guardar(fig, ruta)


def grafico_humedad(prueba, ruta):
    limites = [-np.inf, 6, 8, 10, np.inf]
    grupos = ["< 6", "6 a < 8", "8 a < 10", "≥ 10"]
    tramos = pd.cut(prueba["humedad_pct"], limites, labels=grupos, right=False)
    resumen = prueba.groupby(tramos, observed=False)
    conteos = resumen.size()
    posiciones = np.arange(len(grupos))
    fig, ejes = plt.subplots(1, 2, figsize=(12.3, 5.4))
    fig.subplots_adjust(left=0.077, right=0.967, bottom=0.24, top=0.77, wspace=0.28)
    encabezado(fig, "Sesgo según la humedad del lote",
               "Promedio del error en cada tramo · n indica la cantidad de lotes de prueba")
    for ax, (metal, nombre) in zip(ejes, METALES.items()):
        ax.axhline(0, color="#60786c", linewidth=0.9, linestyle="--")
        for metodo in ("directo", "contexto"):
            medias = resumen[f"{metal}_{metodo}_error_pp"].mean()
            ax.plot(posiciones, medias, marker="o", linewidth=2, color=COLORES[metodo],
                    label=METODOS[metodo])
        ax.set(title=nombre, xlabel="Humedad (% en masa)", ylabel="Sesgo (puntos porcentuales)")
        ax.set_xticks(posiciones, [f"{g}\n(n={n})" for g, n in zip(grupos, conteos)])
        ax.yaxis.set_major_formatter(eje_decimal(2))
        ax.margins(x=0.08, y=0.18)
        ax.grid(axis="x", visible=False)
    fig.legend(*ejes[0].get_legend_handles_labels(), loc="lower center", ncol=2,
               bbox_to_anchor=(0.5, 0.025))
    guardar(fig, ruta)


def grafico_tolerancia(prueba, ruta):
    """Para cada tolerancia, muestra la proporción de errores absolutos que la cumplen."""
    fig, ejes = plt.subplots(1, 2, figsize=(12.3, 5.4), sharey=True)
    fig.subplots_adjust(left=0.09, right=0.967, bottom=0.24, top=0.77, wspace=0.19)
    encabezado(
        fig, "Lotes dentro de una tolerancia de error",
        f"{decimal(len(prueba), 0)} lotes de prueba · En cada curva, más arriba indica mayor cobertura",
    )
    proporcion = np.r_[np.arange(len(prueba) + 1) / len(prueba), 1.0]
    for ax, (metal, nombre) in zip(ejes, METALES.items()):
        errores_absolutos = prueba[[f"{metal}_{m}_error_pp" for m in METODOS]].abs()
        limite = max(0.01, 1.05 * errores_absolutos.to_numpy().max())
        for metodo, etiqueta in METODOS.items():
            errores = np.sort(errores_absolutos[f"{metal}_{metodo}_error_pp"].to_numpy())
            ax.step(np.r_[0, errores, limite], proporcion, where="post", linewidth=1.9,
                    color=COLORES[metodo], label=etiqueta)
        ax.set(title=nombre, xlabel="Tolerancia (puntos porcentuales)", xlim=(0, limite),
               ylim=(0, 1.04))
        ax.set_yticks(np.linspace(0, 1, 6))
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
        ax.xaxis.set_major_formatter(eje_decimal(2))
    ejes[0].set_ylabel("Lotes dentro de la tolerancia")
    fig.legend(*ejes[0].get_legend_handles_labels(), loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, 0.03))
    guardar(fig, ruta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", type=Path, default=RAIZ / "datos" / "veta_clara_sintetico.xlsx")
    parser.add_argument("--corte", default="2025-05-19", help="Inicio de la prueba (AAAA-MM-DD).")
    parser.add_argument("--salida", type=Path, default=RAIZ / "resultados")
    args = parser.parse_args()
    corte = pd.Timestamp(args.corte)
    lotes, pares = cargar_datos(args.excel)
    prueba, metricas, coeficientes, n_ajuste, diferidos = evaluar(pares, corte)

    carpeta_graficos = args.salida / "graficos"
    carpeta_graficos.mkdir(parents=True, exist_ok=True)
    estilo()
    grafico_operacion(lotes, carpeta_graficos / "01_operacion.png")
    grafico_concordancia(prueba, carpeta_graficos / "02_concordancia.png")
    grafico_metricas(metricas, carpeta_graficos / "03_metricas.png")
    grafico_humedad(prueba, carpeta_graficos / "04_humedad.png")
    grafico_tolerancia(prueba, carpeta_graficos / "05_tolerancia.png")

    for nombre, datos in (
        ("metricas", metricas), ("coeficientes", coeficientes), ("predicciones_prueba", prueba)
    ):
        datos.to_csv(args.salida / f"{nombre}.csv", index=False, encoding="utf-8-sig", float_format="%.6f")
    print(f"Lotes: {len(lotes)} | con ensayo: {len(pares)} | ajuste: {n_ajuste} | "
          f"prueba: {len(prueba)} | informes diferidos: {diferidos}")
    print(metricas.to_string(index=False, float_format=lambda x: decimal(x, 4)))
    print(f"Resultados guardados en {args.salida}")


if __name__ == "__main__":
    main()

