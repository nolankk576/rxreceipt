"""Plotly charts in the receipt palette.

Color rule: red (markup) and green (savings) fail a deuteranopia check against
each other, so they never carry meaning on their own. Every colored mark has a
direct label with a +/− amount and a word, and reference marks stay neutral.
"""
from __future__ import annotations

import plotly.graph_objects as go

from rxreceipt.pricing import ReceiptMath, fmt_money

PAPER = "#FAF8F3"
INK = "#141414"
MUTED = "#5F5B53"
GRID = "#E6E1D6"
NEUTRAL = "#A8A296"   # reference rungs
GREEN = "#1F8A4C"
RED = "#D7263D"
FONT = "Inter, system-ui, sans-serif"
CONFIG = {"displayModeBar": False, "responsive": True}


def _layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=16, t=8, b=8),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        font=dict(family=FONT, color=INK, size=14),
        showlegend=False,
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=GRID, font=dict(family=FONT, color=INK)),
        dragmode=False,
    )
    return fig


def price_ladder(m: ReceiptMath, extra: list[tuple[str, float, str]] | None = None) -> go.Figure | None:
    """Horizontal bars: pharmacy cost -> fair-ish -> cost-plus -> (extras) -> you paid.

    `extra` rungs are (label, value, hover note), e.g. Medicare Part D average spend.
    """
    if not m.has_rate:
        return None
    rungs = [
        ("Pharmacy's drug cost", m.drug_cost, "NADAC × quantity"),
        ("Fair-ish price", m.fair_price, "drug cost + typical cost to dispense"),
        ("Cost-plus estimate", m.costplus_total, "drug cost + markup + pharmacy fee + shipping"),
    ]
    rungs += extra or []
    diff = m.paid - m.costplus_total
    if diff > 0:
        paid_color, paid_word = RED, f"{fmt_money(diff, signed=True)} above cost-plus"
    elif diff < 0:
        paid_color, paid_word = GREEN, f"{fmt_money(diff, signed=True)} below cost-plus"
    else:
        paid_color, paid_word = INK, "same as cost-plus"
    rungs.append(("You paid", m.paid, paid_word))

    labels = [r[0] for r in rungs][::-1]       # top-to-bottom reading order
    values = [r[1] for r in rungs][::-1]
    notes = [r[2] for r in rungs][::-1]
    colors = [paid_color] + [NEUTRAL] * (len(rungs) - 1)
    texts = [f"{fmt_money(values[0])}  ·  {paid_word}"] + [fmt_money(v) for v in values[1:]]

    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, cornerradius=4, line=dict(color=PAPER, width=2)),
        text=texts, textposition="outside", cliponaxis=False,
        textfont=dict(family=FONT, color=INK, size=14),
        customdata=notes,
        hovertemplate="<b>%{y}</b><br>%{x:$,.2f}<br>%{customdata}<extra></extra>",
        width=0.62,
    ))
    xmax = max(values) if values else 1
    fig.update_xaxes(range=[0, xmax * 1.9 if xmax > 0 else 1], showgrid=True, gridcolor=GRID,
                     zeroline=True, zerolinecolor=MUTED, tickprefix="$", tickformat=",.0f",
                     tickfont=dict(color=MUTED, size=12), fixedrange=True)
    fig.update_yaxes(tickfont=dict(color=INK, size=13), fixedrange=True, automargin=True)
    return _layout(fig, 70 + 52 * len(rungs))
