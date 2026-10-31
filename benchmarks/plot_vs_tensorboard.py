"""Draw the charts of docs/benchmarks.md from benchmarks/results/vs_tensorboard.json.

    uv run --with matplotlib python benchmarks/plot_vs_tensorboard.py

One horizontal bar chart per case, in a light and a dark variant, written as
SVG to docs/assets/benchmarks/.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmarks" / "results" / "vs_tensorboard.json"
OUT = ROOT / "docs" / "assets" / "benchmarks"
LABELS = {"nuboard": "nuboard", "tensorboardX": "tensorboardX", "torch": "torch.utils.tensorboard"}
CASES = {
    "scalars_us": ("Logging 50 scalars, training thread", "µs per step", "{:,.1f} µs"),
    "slowdown_pct": (
        "Training slowdown, 1 ms steps, 50 scalars/step",
        "% throughput lost",
        "{:.1f}%",
    ),
    "image_ms": ("Logging a 256×256 image, training thread", "ms per image", "{:,.2f} ms"),
    "write_1m_s": ("Writing 1M points, until on disk", "seconds", "{:,.2f} s"),
    "read_1m_s": ("Reading 1M points back", "seconds", "{:,.2f} s"),
    "disk_1m_mb": ("1M points on disk", "MB", "{:,.1f} MB"),
}
THEMES = {
    # brand blue of the docs for nuboard, neutral grey for the others
    "light": {
        "fg": "#1f2328",
        "muted": "#59636e",
        "grid": "#d1d9e0",
        "us": "#0072b2",
        "them": "#9aa4ae",
    },
    "dark": {
        "fg": "#e6edf3",
        "muted": "#9198a1",
        "grid": "#30363d",
        "us": "#56b4e9",
        "them": "#5a636d",
    },
}


def chart(case: str, results: dict[str, dict[str, float]], theme: str) -> None:
    """Draw one case's bar chart in one theme."""
    title, unit, fmt = CASES[case]
    c = THEMES[theme]
    writers = [w for w in LABELS if w in results and case in results[w]]
    values = [results[w][case] for w in writers]
    fig, ax = plt.subplots(figsize=(7.2, 0.5 + 0.48 * len(writers)), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    y = list(range(len(writers)))[::-1]
    colors = [c["us"] if w == "nuboard" else c["them"] for w in writers]
    ax.barh(y, values, color=colors, height=0.62)
    top = max(values) or 1

    for yi, v, w in zip(y, values, writers):
        ax.text(
            v + top * 0.012,
            yi,
            fmt.format(v),
            va="center",
            ha="left",
            color=c["fg"],
            fontsize=10,
            fontweight="bold" if w == "nuboard" else "normal",
        )

    ax.set_yticks(y, [LABELS[w] for w in writers], color=c["fg"], fontsize=10)
    ax.set_xlim(0, top * 1.22)
    ax.set_xlabel(f"{unit} (lower is better)", color=c["muted"], fontsize=9)
    ax.set_title(title, color=c["fg"], fontsize=11, loc="left", pad=8)
    ax.tick_params(axis="x", colors=c["muted"], labelsize=8)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=c["grid"], linewidth=0.6)
    ax.set_axisbelow(True)

    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)

    ax.spines["bottom"].set_color(c["grid"])
    fig.tight_layout()
    fig.savefig(OUT / f"{case}-{theme}.svg", transparent=True, metadata={"Date": None})
    plt.close(fig)


def main() -> None:
    """Draw every chart from the saved results."""
    plt.rcParams["svg.hashsalt"] = "nuboard"  # stable ids, so redrawing gives small diffs
    plt.rcParams["svg.fonttype"] = "none"  # real text: small files, the page's font
    plt.rcParams["font.family"] = "sans-serif"  # the SVG names the family; the browser picks
    results = json.loads(RESULTS.read_text())["results"]
    OUT.mkdir(parents=True, exist_ok=True)

    for case in CASES:
        for theme in THEMES:
            chart(case, results, theme)

    print(f"wrote {len(CASES) * len(THEMES)} charts to {OUT}")


if __name__ == "__main__":
    main()
