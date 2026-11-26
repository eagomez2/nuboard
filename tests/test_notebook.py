"""Jupyter support: HTML summaries of runs and projects, and `nb.show`."""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

import nuboard as nb
from nuboard import notebook


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as exc:  # 503 when the frontend is not built
        return exc.code, dict(exc.headers), exc.read()


def test_run_and_project_render_as_html():
    run = nb.init("nbp", run_name="baseline <b>", config={"optim": {"lr": 0.1}}, capture_env=False)
    run.add_scalar({"loss": 0.5, "acc": 0.9}, step=3)
    run.flush()
    live = run._repr_html_()
    assert "baseline &lt;b&gt;" in live  # escaped
    assert "optim.lr" in live and "running" in live
    run.add_scalar("loss", 0.25, step=4)
    run.finish()
    done = run._repr_html_()
    assert "finished" in done and "0.25" in done and "at step 4" in done

    project = nb.load("nbp")
    html = project._repr_html_()
    assert "1 run" in html and run.id in html
    handle = project.run(run.id)
    assert "loss" in handle._repr_html_()


def test_long_configs_are_cut():
    run = nb.init("nbp", config={f"k{i}": i for i in range(40)}, capture_env=False)
    assert "and 28 more keys" in run._repr_html_()
    run.finish()


def test_show_serves_the_viewer_in_a_frame(tmp_path):
    run = nb.init("nbp", capture_env=False)
    run.add_scalar("loss", 1.0, step=0)
    run.flush()
    viewer = nb.show(run)

    try:
        assert viewer.url.startswith("http://127.0.0.1:")
        assert viewer.url.endswith(f"/#/charts?sel={run.path.name}")
        frame = viewer._repr_html_()
        assert "<iframe" in frame and viewer.url in frame
        assert nb.show("nbp").url.split("/#")[0] == viewer.url.split("/#")[0]  # reused

        status, headers, body = _get(viewer.url.split("#")[0] + "api/runs")
        assert status == 200 and run.id.encode() in body
        status, headers, _ = _get(viewer.url.split("#")[0])
        csp = {k.lower(): v for k, v in headers.items()}.get("content-security-policy", "")
        assert "frame-ancestors 'self' http://localhost:*" in csp
        assert "vscode-webview:" in csp
    finally:
        viewer.stop()
        run.finish()


def test_show_of_a_missing_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        nb.show(tmp_path / "nope")


def test_frame_ancestors_are_checked():
    from nuboard.server.app import _framing

    assert _framing(())["X-Frame-Options"] == "SAMEORIGIN"
    assert _framing(("https://a.example",)) == {
        "Content-Security-Policy": "frame-ancestors 'self' https://a.example"
    }

    for bad in ("a; script-src *", "x y", "'none'", ""):
        with pytest.raises(ValueError):
            _framing((bad,))


def test_a_plain_viewer_still_refuses_frames(tmp_path):
    from starlette.testclient import TestClient

    from nuboard.server import create_app

    (tmp_path / "runs").mkdir()
    res = TestClient(create_app(tmp_path)).get("/")
    assert res.headers["x-frame-options"] == "SAMEORIGIN"
    assert res.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert notebook.FRAME_ANCESTORS[0] == "http://localhost:*"
