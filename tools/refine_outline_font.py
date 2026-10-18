"""Refine the vendored Delta Outline font (requires fonttools[woff]).

Run from any directory. This is build tooling, not a runtime dependency.
Keeps single-storey a/g and the OFL-renamed family; repeated runs are safe.
"""
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

FONT = Path(__file__).resolve().parents[1] / "gkmas_delta/web/assets/fonts/delta-outline/delta-outline-700.woff2"


def main():
    font = TTFont(FONT, recalcTimestamp=False)
    glyphs = font.getGlyphSet()
    replacements = {}
    for code, name in font.getBestCmap().items():
        char = chr(code)
        if not char.isalpha() or char in "gjpqyI":
            continue
        bounds = BoundsPen(glyphs)
        glyphs[name].draw(bounds)
        if bounds.bounds and bounds.bounds[1]:
            pen = TTGlyphPen(glyphs)
            glyphs[name].draw(TransformPen(pen, (1, 0, 0, 1, 0, -bounds.bounds[1])))
            replacements[name] = pen.glyph()

    # Rounded short crossbars, with the existing 104-unit stem weight.
    pen = TTGlyphPen(None)
    pen.moveTo((95, 781))
    pen.lineTo((405, 781)); pen.qCurveTo((450, 781), (450, 736))
    pen.qCurveTo((450, 691), (405, 691)); pen.lineTo((302, 691))
    pen.lineTo((302, 90)); pen.lineTo((405, 90))
    pen.qCurveTo((450, 90), (450, 45)); pen.qCurveTo((450, 0), (405, 0))
    pen.lineTo((95, 0)); pen.qCurveTo((50, 0), (50, 45))
    pen.qCurveTo((50, 90), (95, 90)); pen.lineTo((198, 90))
    pen.lineTo((198, 691)); pen.lineTo((95, 691))
    pen.qCurveTo((50, 691), (50, 736)); pen.qCurveTo((50, 781), (95, 781))
    pen.closePath()
    name = font.getBestCmap()[ord("I")]
    replacements[name] = pen.glyph()
    font['hmtx'].metrics[name] = (500, 50)
    for name, glyph in replacements.items():
        font['glyf'][name] = glyph

    # line-height: 1 now places the baseline at the line box's bottom.
    # Descenders remain in the outlines and are clipped by the heading.
    em = font['head'].unitsPerEm
    font['hhea'].ascent, font['hhea'].descent, font['hhea'].lineGap = em, 0, 0
    font['OS/2'].sTypoAscender = em
    font['OS/2'].sTypoDescender = font['OS/2'].sTypoLineGap = 0
    font['OS/2'].fsSelection |= 1 << 7
    font.save(FONT)
    print(FONT)


if __name__ == '__main__':
    main()
