# `add_html`

```python
run.add_html(key, html, step=None, *, time=None)
```

Logs an HTML document, for anything the other types do not cover: a styled
report, a diff of two outputs, a custom visualization with its own script.

**Parameters**

- **key** (*str*): the name the document is logged under.
- **html** (*str*): the HTML source. It can include `<style>`, inline SVG and
  `<script>`.
- **step** (*int*, optional): the training step.

**Stored as** UTF-8, as given.

**In the viewer** each document runs in a sandboxed frame that allows
scripts but has no access to the viewer, its data or its cookies, and the
document is served with a matching Content-Security-Policy. **output / code**
switches to the source, with line numbers. HTML is listed under **HTML**.

**Example**

```python
import nuboard as nb

run = nb.init("api-tour", run_name="html")
pairs = [
    ("the cat sat on the mat", "the cat sat on a mat"),
    ("a quick brown fox", "a quick brown fox"),
    ("we eat at noon", "we meet at noon"),
]

for epoch in range(2):
    rows = ""
    for ref, hyp in pairs[: epoch + 2]:
        words = [w if w == r else f"<mark>{w}</mark>" for w, r in zip(hyp.split(), ref.split())]
        rows += f"<tr><td>{ref}</td><td>{' '.join(words)}</td></tr>"
    run.add_html(
        "eval/diff",
        "<style>body{font:14px system-ui;margin:12px}table{border-collapse:collapse}"
        "td,th{border:1px solid #ccc;padding:4px 8px}mark{background:#fde68a}</style>"
        f"<h3>Transcripts at epoch {epoch}</h3>"
        f"<table><tr><th>reference</th><th>output</th></tr>{rows}</table>",
        step=epoch,
    )

run.finish()
```

**Expected result**

![An HTML card showing a small styled table](../assets/api/html.png)
