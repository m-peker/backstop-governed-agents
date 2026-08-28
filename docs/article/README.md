# The articles

Two write-ups of what this repository argues, both drafted for Medium. They are not
translations of each other.

- [`medium.md`](medium.md) - English, ~3,600 words, six figures. Written for someone who
  will go and read the code afterwards, so it quotes real rules and real refusals.
- [`medium-tr.md`](medium-tr.md) - Turkish, ~1,100 words, three figures. Written for
  someone deciding whether the idea is worth their afternoon, so it carries the argument
  and drops the implementation detail. It ends with what to do in your own system.

## Publishing it

Medium supports headings, lists, code blocks, blockquotes and images. It does **not**
support tables, which is why there are none in the draft.

1. Paste `medium.md` into a Medium draft. Headings, code fences and quotes survive the
   paste; the image lines do not, and become literal text.
2. Delete each `![Figure N ...](figures/...)` line and upload the matching PNG from
   [`figures/`](figures/) in its place. Set the caption from the alt text.
3. Figure 1 (or `tr1-katmanlar.png` for the Turkish piece) works well as the cover image.

The PNGs are rendered at 2x, so they stay sharp when a reader clicks to zoom.

## Regenerating the figures

The figures are generated rather than drawn, so the palette, type scale and arrowheads
stay identical across all nine by construction instead of by care. Colour carries an
argument in them and is not decoration:

- **teal** - deterministic code, which cannot be talked out of a decision
- **violet**, always dashed - the model, the part that can be persuaded
- **red** - a refusal
- **amber** - a person
- **slate** - the record

To rebuild:

```bash
cd docs/article/figures
for f in fig*.py tr_figures.py; do uv run python "$f"; done   # .py -> .svg
node render.mjs 2                                  # .svg -> .png at 2x
```

`render.mjs` needs [`@resvg/resvg-js`](https://github.com/yisibl/resvg-js), which is a
build-time tool rather than a project dependency. Install it wherever is convenient and
point `RESVG_MODULES` at that `node_modules` directory:

```bash
npm install @resvg/resvg-js --prefix /tmp/svg
RESVG_MODULES=/tmp/svg/node_modules node render.mjs 2
```

[`_theme.py`](figures/_theme.py) holds the palette and the drawing primitives. Editing a
colour there changes it in every figure, which is the point. `fig*.py` are the English
set; [`tr_figures.py`](figures/tr_figures.py) is the Turkish one - flatter, fewer, and
with the sequence diagram redrawn as a numbered timeline, because that article is doing
a different job.

## Checking the figures

Look at the PNGs. Text width in the generator is estimated rather than measured, so a
long label added later can overflow its box, and the estimate is the first thing to
suspect when something looks wrong.
