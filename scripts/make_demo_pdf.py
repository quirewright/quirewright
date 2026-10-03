#!/usr/bin/env python3
"""Build the demo PDF used for the project-site screenshots.

    python scripts/make_demo_pdf.py demo.pdf

The page mixes text, filled and stroked paths, a curve, an image and two form
fields so that every editing feature has something to show.
"""

from __future__ import annotations

import sys

import pymupdf

OX = (0.478, 0.122, 0.169)
INK = (0.13, 0.12, 0.11)
GREY = (0.45, 0.43, 0.40)
RULE = (0.8, 0.78, 0.74)
BODY = (
    "The survey covered twelve transects along the eastern bank between the weir and the old mill. "
    "Water temperature, dissolved oxygen and turbidity were recorded at each station every two hours. "
    "Figures below summarise the daytime means; the full dataset is attached to this document."
)
NOTES = (
    "Stations S3 and S7 sit just below the riffles, where re-aeration keeps oxygen high. "
    "S4 is in the slack water above the weir and should be resampled after the autumn rains."
)


def footer(page: pymupdf.Page, number: int) -> None:
    page.draw_line((54, 740), (558, 740), color=RULE, width=0.6)
    page.insert_text((54, 758), f"Riverside Trust  ·  Report 2026-09  ·  Page {number} of 3",
                     fontsize=8.5, fontname="helv", color=GREY)


def gradient_image() -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 160, 100), False)
    for y in range(100):
        for x in range(160):
            pix.set_pixel(x, y, (int(60 + x * 0.9), int(90 + y * 1.1), int(130 + (x + y) * 0.3)))
    return pix


def first_page(page: pymupdf.Page) -> None:
    page.draw_rect(pymupdf.Rect(0, 0, 612, 118), color=None, fill=OX)
    page.insert_text((54, 62), "Field survey, autumn 2026", fontsize=28, fontname="hebo", color=(1, 1, 1))
    page.insert_text((54, 88), "Riverside conservation district", fontsize=13, fontname="helv",
                     color=(0.95, 0.9, 0.85))
    page.insert_textbox(pymupdf.Rect(54, 140, 558, 215), BODY, fontsize=11, fontname="helv", color=INK,
                        lineheight=1.4)

    page.insert_text((54, 250), "Dissolved oxygen by station (mg/L)", fontsize=14, fontname="hebo", color=INK)
    values = [8.1, 7.4, 9.2, 6.8, 8.7, 7.9, 9.5, 8.3]
    colours = [OX, (0.83, 0.66, 0.29)]
    x0, base, width = 70, 420, 34
    for i, v in enumerate(values):
        x = x0 + i * 46
        page.draw_rect(pymupdf.Rect(x, base - v * 14, x + width, base), color=None, fill=colours[i % 2])
        page.insert_text((x + 9, base + 16), f"S{i + 1}", fontsize=9, fontname="helv", color=GREY)
    page.draw_line((60, base), (450, base), color=GREY, width=0.8)

    shape = page.new_shape()
    shape.draw_bezier((70, 380), (160, 300), (300, 420), (440, 330))
    shape.finish(color=(0.16, 0.45, 0.33), width=2.5, closePath=False)
    shape.commit()
    page.draw_circle((520, 330), 38, color=OX, fill=(0.98, 0.93, 0.80), width=2)
    page.insert_text((497, 335), "Mill", fontsize=13, fontname="hebo", color=OX)

    page.insert_image(pymupdf.Rect(54, 470, 214, 570), pixmap=gradient_image())
    page.insert_text((54, 586), "Figure 2. Eastern bank at the weir.", fontsize=9, fontname="helv", color=GREY)
    page.insert_textbox(pymupdf.Rect(240, 470, 558, 560), NOTES, fontsize=10.5, fontname="helv", color=INK,
                        lineheight=1.4)

    page.insert_text((54, 640), "Reviewed by", fontsize=10, fontname="hebo", color=INK)
    field = pymupdf.Widget()
    field.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    field.field_name = "reviewer"
    field.rect = pymupdf.Rect(54, 648, 300, 672)
    field.border_color = (0.7, 0.68, 0.64)
    field.fill_color = (0.985, 0.97, 0.94)
    field.text_fontsize = 10
    page.add_widget(field)
    box = pymupdf.Widget()
    box.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    box.field_name = "approved"
    box.rect = pymupdf.Rect(330, 652, 346, 668)
    box.border_color = (0.7, 0.68, 0.64)
    page.add_widget(box)
    page.insert_text((354, 664), "Approved for publication", fontsize=10, fontname="helv", color=INK)
    footer(page, 1)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    doc = pymupdf.open()
    first_page(doc.new_page(width=612, height=792))
    for n in (2, 3):
        page = doc.new_page(width=612, height=792)
        page.insert_text((54, 72), f"Appendix {n - 1}", fontsize=20, fontname="hebo", color=INK)
        page.insert_textbox(pymupdf.Rect(54, 100, 558, 400), BODY + " " + NOTES, fontsize=11, fontname="helv",
                            color=INK, lineheight=1.4)
        footer(page, n)
    doc.set_metadata({"title": "Field survey, autumn 2026", "author": "Riverside Trust"})
    doc.save(sys.argv[1])
    print("wrote", sys.argv[1])


if __name__ == "__main__":
    main()
