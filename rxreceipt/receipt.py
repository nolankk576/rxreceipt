"""The receipt: one list of line items, rendered three ways (HTML card, PNG, PDF).

Keeping one source of lines means the card on screen, the PNG and the PDF can
never disagree.
"""
from __future__ import annotations

import html
import io
from dataclasses import dataclass
from pathlib import Path

from rxreceipt.pricing import ReceiptInputs, ReceiptMath, fmt_money, per_unit_label, unit_noun

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONT_REG = FONT_DIR / "IBMPlexMono-Regular.ttf"
FONT_BOLD = FONT_DIR / "IBMPlexMono-Bold.ttf"

INK, PAPER, GREEN, RED, MUTED = "#141414", "#FFFDF8", "#1F8A4C", "#D7263D", "#5F5B53"


@dataclass(frozen=True)
class Line:
    label: str
    value: str = ""
    note: str = ""        # small grey second line
    kind: str = "item"    # item | total | section | rule | good | bad | text


def fmt_ndc(ndc: str) -> str:
    """11-digit NDC -> 5-4-2 (the HIPAA billing format)."""
    d = "".join(c for c in str(ndc) if c.isdigit()).zfill(11)
    return f"{d[:5]}-{d[5:9]}-{d[9:]}"


def fmt_qty(q: float) -> str:
    return f"{q:,.0f}" if float(q).is_integer() else f"{q:,.2f}".rstrip("0").rstrip(".")


def fmt_rate(x: float) -> str:
    """Per-unit rates can be fractions of a cent; CMS publishes 5 decimals, so show them."""
    return f"${x:,.2f}" if x >= 100 else f"${x:,.5f}".rstrip("0").rstrip(".") if x < 1 else f"${x:,.4f}"


def build_lines(inp: ReceiptInputs, m: ReceiptMath, label: str, description: str) -> list[Line]:
    units = unit_noun(inp.pricing_unit, description)
    per = per_unit_label(inp.pricing_unit, description)
    copay = inp.pay_method == "insurance copay"
    paid_label = {"cash": "You paid (cash)", "insurance copay": "You paid (copay)"}.get(inp.pay_method, "You paid")
    lines = [Line(label, kind="title"),
             Line(f"{fmt_qty(inp.quantity)} {units} · {inp.days_supply}-day supply", kind="text")]

    if not m.has_rate:
        lines += [
            Line("rule", kind="rule"),
            Line("Pharmacy's drug cost", "no NADAC rate",
                 "CMS publishes no NADAC rate for this product (common for specialty and some brand drugs).",
                 kind="item"),
            Line("rule", kind="rule"),
            Line(paid_label, fmt_money(m.paid), kind="total"),
            Line(f"Per year at {m.fills_per_year:.1f} fills", fmt_money(m.yearly_paid), kind="item"),
        ]
        return lines

    cp_note = (f"{fmt_money(m.costplus_drug)} drug + {inp.markup_pct:g}% markup {fmt_money(m.costplus_markup)}"
               f" + {fmt_money(m.costplus_fee)} fee + {fmt_money(m.costplus_shipping)} shipping")
    lines += [
        Line("rule", kind="rule"),
        Line("Pharmacy's drug cost", fmt_money(m.drug_cost),
             f"NADAC {fmt_rate(inp.nadac_per_unit)} {per} × {fmt_qty(inp.quantity)}"),
        Line("Typical cost to dispense", fmt_money(m.dispense_fee), "bottle, label, pharmacist time"),
        Line("= Fair-ish price", fmt_money(m.fair_price), kind="total"),
        Line("rule", kind="rule"),
        Line("Cost-plus estimate", fmt_money(m.costplus_total), cp_note, kind="total"),
        Line("rule", kind="rule"),
        Line(paid_label, fmt_money(m.paid), kind="total"),
    ]
    if m.markup_dollars is not None:
        pct = f" ({m.markup_pct:+,.0f}%)" if m.markup_pct is not None else ""
        word = "above" if m.markup_dollars > 0 else "below" if m.markup_dollars < 0 else "equal to"
        kind = "bad" if m.markup_dollars > 0 else "good"
        lines.append(Line("Markup over pharmacy cost", fmt_money(m.markup_dollars, signed=True) + pct,
                          f"what you paid is {word} the pharmacy's drug cost", kind=kind))
    y = m.yearly_vs_costplus
    if y is not None:
        fills = f"vs the cost-plus estimate, at {m.fills_per_year:.1f} fills a year"
        if y > 0:
            lines.append(Line("Yearly difference", f"could save {fmt_money(y)}/yr", fills, kind="good"))
        elif y < 0:
            note = "your copay already beats the cost-plus estimate" if copay else \
                "you already pay less than the cost-plus estimate"
            lines.append(Line("Yearly difference", f"{fmt_money(y, signed=True)}/yr",
                              f"{note} ({m.fills_per_year:.1f} fills a year)", kind="text"))
        else:
            lines.append(Line("Yearly difference", "$0.00/yr", fills, kind="text"))
    return lines


# --- barcode -------------------------------------------------------------

# EAN-13 "L" digit patterns. Decorative only: this is not a scannable code.
_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]


def barcode_modules(ndc: str) -> str:
    d = "".join(c for c in str(ndc) if c.isdigit()).zfill(11)
    mid = len(d) // 2
    body = "".join(_L[int(c)] for c in d[:mid]) + "01010" + "".join(
        "".join("1" if b == "0" else "0" for b in _L[int(c)]) for c in d[mid:])
    return "101" + body + "101"


def barcode_svg(ndc: str, height: int = 56) -> str:
    mods = barcode_modules(ndc)
    rects = [f'<rect x="{i}" y="0" width="1" height="{height}"/>' for i, b in enumerate(mods) if b == "1"]
    return (f'<svg class="rx-barcode" viewBox="0 0 {len(mods)} {height}" preserveAspectRatio="none" '
            f'aria-hidden="true" fill="{INK}">{"".join(rects)}</svg>')


# --- HTML ----------------------------------------------------------------

def render_html(lines: list[Line], ndc: str | None, as_of: str, paper_note: str = "") -> str:
    e = html.escape
    rows = []
    for ln in lines:
        if ln.kind == "title":
            rows.append(f'<div class="rx-product">{e(ln.label)}</div>')
        elif ln.kind == "rule":
            rows.append('<div class="rx-rule" aria-hidden="true"></div>')
        elif ln.kind == "text" and not ln.value:
            rows.append(f'<div class="rx-sub">{e(ln.label)}</div>')
        else:
            note = f'<div class="rx-note">{e(ln.note)}</div>' if ln.note else ""
            rows.append(f'<div class="rx-line rx-{ln.kind}"><span class="rx-label">{e(ln.label)}</span>'
                        f'<span class="rx-value">{e(ln.value)}</span></div>{note}')
    code = ""
    if ndc:
        code = f'{barcode_svg(ndc)}<div class="rx-ndc">NDC {e(fmt_ndc(ndc))}</div>'
    return f"""
<div class="rx-receipt" role="figure" aria-label="Prescription price receipt">
  <div class="rx-head">
    <div class="rx-brand">RxReceipt</div>
    <div class="rx-tag">a receipt that tells the truth</div>
    <div class="rx-meta">prices as of {e(as_of)}</div>
  </div>
  {''.join(rows)}
  <div class="rx-rule" aria-hidden="true"></div>
  {code}
  <div class="rx-foot">ESTIMATE · NOT A BILL · EDUCATIONAL ONLY{e(paper_note)}</div>
</div>"""


# --- PNG -----------------------------------------------------------------

def render_png(lines: list[Line], ndc: str | None, as_of: str, width: int = 760) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    pad, gap = 48, 10
    f_body = ImageFont.truetype(str(FONT_REG), 22)
    f_bold = ImageFont.truetype(str(FONT_BOLD), 23)
    f_note = ImageFont.truetype(str(FONT_REG), 17)
    f_big = ImageFont.truetype(str(FONT_BOLD), 40)
    inner = width - 2 * pad

    def wrap(text: str, font, max_w: int) -> list[str]:
        words, out, cur = text.split(), [], ""
        for w in words:
            t = f"{cur} {w}".strip()
            if font.getlength(t) <= max_w:
                cur = t
            else:
                out.append(cur)
                cur = w
        return out + ([cur] if cur else [])

    # Lay out first (list of draw ops), then size the canvas to fit.
    ops: list[tuple] = []
    y = pad + 20

    def text(t, font, fill=INK, align="left"):
        nonlocal y
        ops.append(("text", t, font, fill, align, y))
        y += font.size + gap

    text("RxReceipt", f_big, align="center")
    text("a receipt that tells the truth", f_note, MUTED, "center")
    text(f"prices as of {as_of}", f_note, MUTED, "center")
    y += 8
    for ln in lines:
        color = {"good": GREEN, "bad": RED}.get(ln.kind, INK)
        if ln.kind == "rule":
            ops.append(("rule", y + 6))
            y += 22
        elif ln.kind == "title":
            for t in wrap(ln.label, f_bold, inner):
                text(t, f_bold)
        elif ln.kind == "text" and not ln.value:
            text(ln.label, f_note, MUTED)
        else:
            font = f_bold if ln.kind in ("total", "good", "bad") else f_body
            vw = font.getlength(ln.value)
            label_lines = wrap(ln.label, font, inner - vw - 20)
            ops.append(("pair", label_lines[0], ln.value, font, color, y))
            y += font.size + gap
            for t in label_lines[1:]:
                text(t, font, color)
            for t in wrap(ln.note, f_note, inner) if ln.note else []:
                text(t, f_note, MUTED)
    ops.append(("rule", y + 6))
    y += 26
    if ndc:
        ops.append(("barcode", y))
        y += 80
        text(f"NDC {fmt_ndc(ndc)}", f_note, MUTED, "center")
    text("ESTIMATE · NOT A BILL · EDUCATIONAL ONLY", f_note, MUTED, "center")
    height = y + pad

    img = Image.new("RGB", (width, height + 40), "#FAF8F3")
    d = ImageDraw.Draw(img)
    tooth = 14
    # Paper with zigzag torn top and bottom edges.
    top = [(0, 20 + tooth)] + [(x, 20 + (0 if (x // tooth) % 2 else tooth)) for x in range(0, width + 1, tooth)] + [(width, 20 + tooth)]
    d.polygon(top + [(width, height), (0, height)], fill=PAPER)
    bottom = [(x, height + (tooth if (x // tooth) % 2 else 0)) for x in range(0, width + 1, tooth)]
    d.polygon([(0, height - 2)] + bottom + [(width, height - 2)], fill=PAPER)

    for op in ops:
        if op[0] == "text":
            _, t, font, fill, align, yy = op
            x = (width - font.getlength(t)) / 2 if align == "center" else pad
            d.text((x, yy), t, font=font, fill=fill)
        elif op[0] == "pair":
            _, lab, val, font, fill, yy = op
            d.text((pad, yy), lab, font=font, fill=fill)
            d.text((width - pad - font.getlength(val), yy), val, font=font, fill=fill)
        elif op[0] == "rule":
            for x in range(pad, width - pad, 12):
                d.line([(x, op[1]), (x + 6, op[1])], fill=MUTED, width=2)
        elif op[0] == "barcode":
            mods = barcode_modules(ndc)
            mw = 4
            x0 = (width - len(mods) * mw) // 2
            for i, b in enumerate(mods):
                if b == "1":
                    d.rectangle([x0 + i * mw, op[1], x0 + i * mw + mw - 1, op[1] + 64], fill=INK)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# --- PDF -----------------------------------------------------------------

def render_pdf(lines: list[Line], ndc: str | None, as_of: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format=(100, 240), unit="mm")
    pdf.set_margins(8, 8, 8)
    pdf.set_auto_page_break(True, 10)
    pdf.add_page()
    pdf.add_font("Plex", "", str(FONT_REG))
    pdf.add_font("Plex", "B", str(FONT_BOLD))
    pdf.set_fill_color(0xFF, 0xFD, 0xF8)
    pdf.rect(0, 0, 100, 240, "F")
    w = pdf.epw

    def rgb(hexstr):
        return tuple(int(hexstr[i:i + 2], 16) for i in (1, 3, 5))

    def rule():
        pdf.set_draw_color(*rgb(MUTED))
        pdf.set_dash_pattern(dash=1, gap=1)
        y = pdf.get_y() + 1.5
        pdf.line(pdf.l_margin, y, pdf.l_margin + w, y)
        pdf.set_dash_pattern()
        pdf.ln(4)

    pdf.set_font("Plex", "B", 16)
    pdf.cell(w, 8, "RxReceipt", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Plex", "", 7.5)
    pdf.set_text_color(*rgb(MUTED))
    pdf.cell(w, 4, "a receipt that tells the truth", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w, 4, f"prices as of {as_of}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for ln in lines:
        color = rgb({"good": GREEN, "bad": RED}.get(ln.kind, INK))
        if ln.kind == "rule":
            rule()
            continue
        if ln.kind == "title":
            pdf.set_text_color(*rgb(INK))
            pdf.set_font("Plex", "B", 9.5)
            pdf.multi_cell(w, 4.6, ln.label, new_x="LMARGIN", new_y="NEXT")
            continue
        if ln.kind == "text" and not ln.value:
            pdf.set_text_color(*rgb(MUTED))
            pdf.set_font("Plex", "", 7.5)
            pdf.multi_cell(w, 4, ln.label, new_x="LMARGIN", new_y="NEXT")
            continue
        bold = "B" if ln.kind in ("total", "good", "bad") else ""
        pdf.set_text_color(*color)
        pdf.set_font("Plex", bold, 8.5)
        vw = pdf.get_string_width(ln.value) + 2
        y = pdf.get_y()
        pdf.multi_cell(w - vw, 4.6, ln.label, new_x="LMARGIN", new_y="NEXT")
        y_after = pdf.get_y()
        pdf.set_xy(pdf.l_margin + w - vw, y)
        pdf.cell(vw, 4.6, ln.value, align="R")
        pdf.set_xy(pdf.l_margin, y_after)
        if ln.note:
            pdf.set_text_color(*rgb(MUTED))
            pdf.set_font("Plex", "", 6.8)
            pdf.multi_cell(w, 3.6, ln.note, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.8)
    rule()
    if ndc:
        mods = barcode_modules(ndc)
        mw = 0.6
        x0 = pdf.l_margin + (w - len(mods) * mw) / 2
        y = pdf.get_y()
        pdf.set_fill_color(*rgb(INK))
        for i, b in enumerate(mods):
            if b == "1":
                pdf.rect(x0 + i * mw, y, mw, 10, "F")
        pdf.set_y(y + 11)
        pdf.set_text_color(*rgb(MUTED))
        pdf.set_font("Plex", "", 7)
        pdf.cell(w, 4, f"NDC {fmt_ndc(ndc)}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Plex", "", 6.5)
    pdf.set_text_color(*rgb(MUTED))
    pdf.cell(w, 4, "ESTIMATE · NOT A BILL · EDUCATIONAL ONLY", align="C", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
