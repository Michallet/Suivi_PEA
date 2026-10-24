"""Graphiques Plotly (toujours habillés par style.habiller, jamais plotly.express)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pea.domain.formats import court, fmt, sans_parentheses
from pea.ui import style
from pea.ui.composants.communs import PLOTLY


def afficher(fig: go.Figure) -> None:
    st.plotly_chart(fig, config=PLOTLY)


def _sans_zoom(fig: go.Figure) -> None:
    fig.update_xaxes(fixedrange=True)  # pas de zoom tactile
    fig.update_yaxes(fixedrange=True)


def compare(df: pd.DataFrame, cle: str) -> None:
    """Barres groupées « Actuel / Projeté » (onglet Projet)."""
    d = df.iloc[::-1].copy()  # le plus gros en haut
    d[cle] = sans_parentheses(d[cle])  # noms épurés
    fig = go.Figure()
    fig.add_bar(y=d[cle], x=d["reel"], name="Actuel", orientation="h", marker_color=style.ARDOISE,
                hovertemplate="<b>%{y}</b><br>Actuel : %{x:.1f} %<extra></extra>")
    fig.add_bar(y=d[cle], x=d["projete"], name="Projeté", orientation="h", marker_color=style.BLEU,
                hovertemplate="<b>%{y}</b><br>Projeté : %{x:.1f} %<extra></extra>")
    style.habiller(fig)
    fig.update_layout(barmode="group", margin=dict(l=0, r=0, t=10, b=0), height=max(240, 52 * len(d) + 70),
                      legend=dict(orientation="h", y=-0.12), xaxis_title="% du PEA")
    _sans_zoom(fig)
    afficher(fig)


def secteurs(df: pd.DataFrame) -> None:
    """Anneau de répartition par secteur : palette douce commune à tous les graphiques, pourcentages
    arrondis sur l'anneau (masqués si la part est trop petite), détail arrondi au toucher / survol."""
    d = df.sort_values("valeur", ascending=False)
    total = float(d["valeur"].sum())
    couleurs = [style.PALETTE[i % len(style.PALETTE)] for i in range(len(d))]
    fig = go.Figure(go.Pie(
        labels=d["secteur"].tolist(), values=d["valeur"].tolist(), hole=0.62, sort=False, direction="clockwise",
        marker=dict(colors=couleurs, line=dict(color=style.fond_page(), width=2)),
        texttemplate="%{percent:.0%}", textposition="inside", insidetextorientation="horizontal",
        textfont=dict(color=[style.texte_sur(c) for c in couleurs], size=13),
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} €<br>%{percent:.1%}<extra></extra>"))
    style.habiller(fig)
    fig.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=360, showlegend=True,
        uniformtext=dict(minsize=11, mode="hide"),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.02, yanchor="top", font=dict(size=12)),
        annotations=[dict(text=f"<b>{fmt(total, 0)} €</b><br>en titres", x=0.5, y=0.5,
                          showarrow=False, font=dict(size=16))])
    afficher(fig)


def treemap(d: pd.DataFrame) -> None:
    """Treemap PEA › secteur › ligne ; couleur = performance (moyenne pondérée par la valeur pour les niveaux
    supérieurs). Construit directement avec Plotly (listes simples)."""
    ids, labels, parents, valeurs, perfs = ["PEA"], ["PEA"], [""], [], []
    v_tot = float(d["valeur"].sum())
    perfs.append(float((d["valeur"] * d["perf_pct"]).sum() / v_tot) if v_tot else 0.0)
    valeurs.append(v_tot)
    for secteur, g in d.groupby("secteur"):
        v_s = float(g["valeur"].sum())
        ids.append(f"S|{secteur}")
        labels.append(str(secteur))
        parents.append("PEA")
        valeurs.append(v_s)
        perfs.append(float((g["valeur"] * g["perf_pct"]).sum() / v_s) if v_s else 0.0)
        for r in g.itertuples():
            ids.append(f"L|{r.isin}")
            labels.append(str(r.nom))
            parents.append(f"S|{secteur}")
            valeurs.append(float(r.valeur))
            perfs.append(float(r.perf_pct))
    lim = max(abs(p) for p in perfs) or 1.0
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=valeurs, branchvalues="total",
        marker=dict(colors=perfs, colorscale="RdYlGn", cmin=-lim, cmax=lim, showscale=False),
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} €<br>Performance : %{color:+.1f} %<extra></extra>"))
    style.habiller(fig)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=360)
    afficher(fig)


def barres(df: pd.DataFrame, x: str, labels: dict, titre: str | None = None,
           valeur_infobulle: str = "%{x:+.1f} %") -> None:
    """Barres horizontales (une par ligne), colorées du rouge au vert autour de 0.
    `valeur_infobulle` : format (arrondi) de la valeur affichée au toucher / au survol."""
    valeurs = [float(v) for v in df[x]]
    lim = max(abs(v) for v in valeurs) if valeurs else 1.0
    fig = go.Figure(go.Bar(
        x=valeurs, y=[str(n) for n in df["nom"]], orientation="h",
        marker=dict(color=valeurs, colorscale="RdYlGn", cmin=-lim, cmax=lim, showscale=False),
        hovertemplate="<b>%{y}</b><br>" + valeur_infobulle + "<extra></extra>"))
    style.habiller(fig)
    fig.update_layout(margin=dict(l=0, r=0, t=30 if titre else 10, b=0), height=max(220, 44 * len(df)),
                      title=dict(text=titre) if titre else None,
                      xaxis_title=labels.get(x) or None, yaxis_title=labels.get("nom") or None)
    _sans_zoom(fig)
    afficher(fig)


def courbes(series: list[dict]) -> None:
    """Courbes temporelles (onglet Historique) : [{x, y, name, line, hovertemplate, …}]."""
    fig = go.Figure()
    for s in series:
        fig.add_scatter(mode="lines", **s)
    style.habiller(fig, hovermode="x unified")
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=340, legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(fixedrange=True, hoverformat="%d/%m/%Y")  # pas de zoom tactile
    fig.update_yaxes(fixedrange=True)
    afficher(fig)


def matrice(df: pd.DataFrame, grandeurs: dict, cx: str, cy: str, info) -> None:
    """Nuage de notes 1-10 (taille = poids, couleur = performance, ◆ = watchlist).
    `info(ligne, cle, valeur, note)` : texte d'infobulle d'un axe."""
    def trace(d, **marqueur):
        infos = [[l.nom, info(l, cx, l.vx, l.nx), info(l, cy, l.vy, l.ny),
                  "Watchlist" if l.wl else f"Poids : {fmt(l.poids, 0)} %"] for l in d.itertuples()]
        return go.Scatter(x=d["px"].tolist(), y=d["py"].tolist(), mode="markers+text" if len(df) <= 12 else "markers",
                          text=[court(n, 12) for n in d["nom"]], textposition="top center",
                          textfont=dict(size=11), customdata=infos, showlegend=False,
                          hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                                        "%{customdata[2]}<br>%{customdata[3]}<extra></extra>",
                          marker=marqueur)

    fig = go.Figure()
    detenus_df, suivis_df = df[~df["wl"]], df[df["wl"]]
    if not detenus_df.empty:
        lim = max(5.0, float(detenus_df["perf"].abs().max()))
        fig.add_trace(trace(detenus_df, size=[min(46, 14 + 4.5 * max(p, 0) ** 0.5) for p in detenus_df["poids"]],
                            color=detenus_df["perf"].tolist(), colorscale="RdYlGn", cmin=-lim, cmax=lim,
                            showscale=False, opacity=0.92, line=dict(color="rgba(255,255,255,0.85)", width=1.5)))
    if not suivis_df.empty:
        fig.add_trace(trace(suivis_df, size=15, symbol="diamond", color=style.ARDOISE, opacity=0.9,
                            line=dict(color="rgba(255,255,255,0.85)", width=1.5)))
    fig.add_shape(type="rect", x0=5.5, x1=10.5, y0=5.5, y1=10.5, fillcolor="rgba(22,163,74,0.06)",
                  line_width=0, layer="below")
    fig.add_shape(type="rect", x0=0.5, x1=5.5, y0=0.5, y1=5.5, fillcolor="rgba(220,38,38,0.05)",
                  line_width=0, layer="below")
    gris = "rgba(128,128,128,0.6)"
    fig.add_vline(x=5.5, line=dict(dash="dot", color=gris, width=1))
    fig.add_hline(y=5.5, line=dict(dash="dot", color=gris, width=1))
    for x, y, xa, ya, txt in ((10.4, 10.4, "right", "top", "Fort sur les deux"),
                              (0.6, 0.6, "left", "bottom", "Faible sur les deux"),
                              (0.6, 10.4, "left", "top", f"Fort : {grandeurs[cy][3]}"),
                              (10.4, 0.6, "right", "bottom", f"Fort : {grandeurs[cx][3]}")):
        fig.add_annotation(x=x, y=y, xanchor=xa, yanchor=ya, text=txt, showarrow=False,
                           font=dict(size=11, color="rgba(128,128,128,0.95)"))
    style.habiller(fig)
    axe = dict(range=[0.5, 10.5], tickmode="array", tickvals=list(range(1, 11)), fixedrange=True, zeroline=False)
    fig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0),
                      xaxis=dict(title=f"{grandeurs[cx][0]} — note /10 (10 = {grandeurs[cx][3]})", **axe),
                      yaxis=dict(title=f"{grandeurs[cy][0]} — note /10 (10 = {grandeurs[cy][3]})", **axe))
    afficher(fig)
