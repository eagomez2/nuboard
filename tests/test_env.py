"""What a run records about its code and environment, under every condition we can set up."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import types
import warnings

import pytest

import nuboard as nb
from nuboard import _env

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, **GIT_ENV}
    ).stdout.decode()


def repo(path, commit=True):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    (path / "train.py").write_text("print('hi')\n")

    if commit:
        git(path, "add", "train.py")
        git(path, "commit", "-q", "-m", "first")

    return path


@pytest.fixture(autouse=True)
def _no_script(monkeypatch):
    """Pretend no script started the process (pytest's own would be found otherwise)."""
    monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))
    monkeypatch.setattr(sys, "argv", ["-c"])
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def test_safe_url_drops_credentials_and_keeps_scp_remotes():
    assert _env.safe_url("https://user:TOKEN@github.com/org/repo.git") == (
        "https://github.com/org/repo.git"
    )
    assert _env.safe_url("https://oauth2:glpat-x@gitlab.com/a/b?private_token=y#f") == (
        "https://gitlab.com/a/b"
    )
    assert _env.safe_url("ssh://git@host:2222/org/repo") == "ssh://host:2222/org/repo"
    assert _env.safe_url("git@github.com:org/repo.git") == "git@github.com:org/repo.git"
    assert _env.safe_url("/srv/git/repo.git") == "/srv/git/repo.git"


def test_outside_a_repository_and_without_git_nothing_is_recorded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _env.git_info() == (None, None)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert _env.git_info(cwd=str(repo(tmp_path / "r"))) == (None, None)


def test_a_repository_without_commits(tmp_path, monkeypatch):
    r = repo(tmp_path / "r", commit=False)
    git(r, "add", "train.py")
    (r / "notes.txt").write_text("x\n")
    monkeypatch.chdir(r)
    info, diff = _env.git_info()
    assert info is not None
    assert info["commit"] is None and info["branch"] == "main" and info["pushed"] is None
    assert info["dirty"] is True and info["untracked"] == 1 and info["source"] == "cwd"
    assert "train.py" in (diff or "")


def test_a_clean_checkout_detached_head_and_credentials_in_the_remote(tmp_path, monkeypatch):
    r = repo(tmp_path / "r")
    monkeypatch.chdir(r)
    info, diff = _env.git_info()
    assert info is not None and diff == ""
    assert info["dirty"] is False and info["untracked"] == 0
    assert info["pushed"] is None  # no remote-tracking branches: unknown
    assert info["root"] == str(r.resolve()) and len(str(info["commit"])) == 40

    git(r, "checkout", "-q", "--detach")
    git(r, "remote", "add", "origin", "https://user:TOKEN@example.com/org/r.git")
    info, _ = _env.git_info()
    assert info is not None
    assert info["branch"] is None and info["commit"]
    assert info["remote"] == "https://example.com/org/r.git"


def test_pushed_follows_the_remote_tracking_branches(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    r = repo(tmp_path / "r")
    git(r, "remote", "add", "origin", str(remote))
    git(r, "push", "-q", "origin", "main")
    monkeypatch.chdir(r)
    assert _env.git_info()[0]["pushed"] is True  # type: ignore[index]

    (r / "train.py").write_text("print('changed')\n")
    git(r, "commit", "-q", "-am", "local only")
    info, _ = _env.git_info()
    assert info is not None and info["pushed"] is False


def test_uncommitted_changes_and_untracked_files(tmp_path, monkeypatch):
    r = repo(tmp_path / "r")
    (r / "train.py").write_text("print('changed')\n")
    (r / "new.py").write_text("x = 1\n")
    (r / ".gitignore").write_text("data/\n")
    (r / "data").mkdir()
    (r / "data" / "big.bin").write_bytes(b"\0" * 10)
    monkeypatch.chdir(r)
    info, diff = _env.git_info()
    assert info is not None and info["dirty"] is True
    assert "+print('changed')" in (diff or "")
    assert info["untracked"] == 2  # new.py and .gitignore; ignored files are not counted
    assert "new.py" not in json.dumps(info)  # only the count, never the names


def test_the_script_folder_wins_over_the_working_directory(tmp_path, monkeypatch):
    code = repo(tmp_path / "code")
    other = repo(tmp_path / "dotfiles")
    monkeypatch.setattr(sys, "argv", [str(code / "train.py")])
    monkeypatch.chdir(other)

    with pytest.warns(UserWarning, match="script's repository"):
        info, _ = _env.git_info()

    assert info is not None and info["root"] == str(code.resolve())
    assert info["source"] == "script"

    monkeypatch.chdir(tmp_path)  # outside any repository: no warning

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _env.git_info()[0]["source"] == "script"  # type: ignore[index]


def test_code_dir_wins_and_falls_back_with_a_warning(tmp_path, monkeypatch):
    code = repo(tmp_path / "code")
    here = repo(tmp_path / "here")
    monkeypatch.chdir(here)
    info, _ = _env.git_info(code_dir=code)
    assert info is not None and info["root"] == str(code.resolve())
    assert info["source"] == "code_dir"

    (tmp_path / "plain").mkdir()

    with pytest.warns(UserWarning, match="not inside a git repository"):
        info, _ = _env.git_info(code_dir=tmp_path / "plain")

    assert info is not None and info["source"] == "cwd"

    with pytest.warns(UserWarning):
        assert _env.git_info(code_dir=tmp_path / "missing")[0]["source"] == "cwd"  # type: ignore[index]


def test_failures_inside_git_never_raise(tmp_path, monkeypatch):
    r = repo(tmp_path / "r")
    monkeypatch.chdir(r)

    def boom(*_args, **_kwargs):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(_env, "_describe", boom)
    assert _env.git_info() == (None, None)
    monkeypatch.undo()
    monkeypatch.chdir(r)
    monkeypatch.setattr(_env, "_run", lambda *a, **k: None)  # every git command fails
    assert _env.git_info() == (None, None)


def test_a_deleted_working_directory(tmp_path, monkeypatch):
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.chdir(gone)
    gone.rmdir()

    if os.name == "nt":  # pragma: no cover - Windows cannot remove the working directory
        pytest.skip("Windows keeps the working directory")

    assert _env.git_info() == (None, None)
    assert _env.environment()["cwd"] is None


class FakeDist:
    def __init__(self, name, version, direct=None, broken=False):
        self._meta = {"Name": name}
        self._version = version
        self._direct = direct
        self._broken = broken

    @property
    def metadata(self):
        if self._broken:
            raise ValueError("bad METADATA")

        return self._meta

    @property
    def version(self):
        return self._version

    def read_text(self, name):
        return json.dumps(self._direct) if self._direct is not None else None


def test_pip_freeze_keeps_vcs_commits_without_credentials(monkeypatch):
    dists = [
        FakeDist("numpy", "2.1.0"),
        FakeDist(
            "mylib",
            "0.3",
            {
                "url": "https://user:TOKEN@github.com/org/mylib.git",
                "vcs_info": {"vcs": "git", "commit_id": "abc123"},
            },
        ),
        FakeDist(
            "mine", "0.1", {"url": "file:///home/me/secret-project", "dir_info": {"editable": True}}
        ),
        FakeDist("wheel", "1.0", {"url": "https://h.org/w.whl?sig=SECRET", "archive_info": {}}),
        FakeDist("broken", "1.0", broken=True),
        FakeDist("noversion", None),
    ]
    monkeypatch.setattr(_env.metadata, "distributions", lambda: dists)
    lines = _env.pip_freeze().splitlines()
    assert lines == [
        "mine==0.1  # local: /home/me/secret-project (missing)",
        "mylib @ git+https://github.com/org/mylib.git@abc123",
        "numpy==2.1.0",
        "wheel @ https://h.org/w.whl",
    ]
    text = "\n".join(lines)
    assert "TOKEN" not in text and "SECRET" not in text


def test_init_works_in_any_folder_and_records_what_it_can(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)

    with nb.init("p", run_name="no-repo") as run:
        run.add_scalar({"loss": 1.0}, step=0)

    meta = json.loads((run.path / "run.json").read_text())
    assert meta["git"] is None and meta["env"]["cwd"] == str(plain)
    assert (run.path / "files" / "requirements.txt").exists()
    assert not (run.path / "files" / "git.patch").exists()

    fresh = repo(tmp_path / "fresh", commit=False)
    monkeypatch.chdir(fresh)

    with nb.init("p", run_name="no-commits") as run:
        run.add_scalar({"loss": 1.0}, step=0)

    meta = json.loads((run.path / "run.json").read_text())
    assert meta["git"]["commit"] is None and meta["git"]["untracked"] == 1
    assert meta["status"] == "finished"


def test_init_with_code_dir_and_a_failing_capture_still_runs(tmp_path, monkeypatch):
    code = repo(tmp_path / "code")
    (code / "train.py").write_text("print('edited')\n")
    monkeypatch.chdir(tmp_path)

    def broken(_root=None):
        raise OSError("metadata is unreadable")

    monkeypatch.setattr(_env, "freeze", broken)

    with pytest.warns(UserWarning, match="could not record requirements.txt"):
        run = nb.init("p", run_name="code-dir", code_dir=code)

    with run:
        run.add_scalar({"loss": 1.0}, step=0)

    meta = json.loads((run.path / "run.json").read_text())
    assert meta["git"]["source"] == "code_dir" and meta["git"]["dirty"] is True
    assert "+print('edited')" in (run.path / "files" / "git.patch").read_text()
    assert not (run.path / "files" / "requirements.txt").exists()
    assert meta["status"] == "finished"


def local(name, path, editable=True, version="0.3"):
    return FakeDist(name, version, {"url": path.as_uri(), "dir_info": {"editable": editable}})


def freeze_of(monkeypatch, dists, main_root=None):
    monkeypatch.setattr(_env.metadata, "distributions", lambda: dists)
    text, patches = _env.freeze(str(main_root) if main_root else None)
    names = (re.match(r"[\w.-]+", line) for line in text.splitlines())
    return {m.group(): m.string[m.end() :].strip() for m in names if m}, patches


def pushed_repo(path, remote_url="https://user:TOKEN@example.com/org/lib.git"):
    """A repository whose commit is on a remote, with `remote_url` as its origin."""
    r = repo(path)
    bare = path.parent / f"{path.name}.git"
    git(path.parent, "init", "-q", "--bare", str(bare))
    git(r, "remote", "add", "origin", str(bare))
    git(r, "push", "-q", "origin", "main")
    git(r, "remote", "set-url", "origin", remote_url)
    return r


def test_local_packages_record_the_state_of_their_folder(tmp_path, monkeypatch):
    clean = pushed_repo(tmp_path / "clean")
    (clean / "pkg").mkdir()
    scp = pushed_repo(tmp_path / "scp", "git@github.com:org/scp.git")
    dirty = repo(tmp_path / "dirty")
    (dirty / "train.py").write_text("print('edited')\n")
    unpushed = repo(tmp_path / "unpushed")
    plain = tmp_path / "plain"
    plain.mkdir()
    lines, patches = freeze_of(
        monkeypatch,
        [
            local("clean", clean),
            local("sub", clean / "pkg", editable=False),
            local("scp", scp),
            local("dirty", dirty),
            local("unpushed", unpushed),
            local("plain", plain),
            local("gone", tmp_path / "gone"),
        ],
    )
    head = git(clean, "rev-parse", "HEAD").strip()
    assert lines["clean"] == (f"@ git+https://example.com/org/lib.git@{head}  # local: {clean}")
    assert lines["sub"] == (
        f"@ git+https://example.com/org/lib.git@{head}#subdirectory=pkg  # local: {clean / 'pkg'}"
    )
    assert lines["scp"].startswith("@ git+ssh://git@github.com/org/scp.git@")
    commit = git(dirty, "rev-parse", "HEAD").strip()
    assert lines["dirty"].endswith(f"local: {dirty}, git {commit} (dirty), patch: git-dirty.patch")
    assert "+print('edited')" in patches["git-dirty.patch"] and len(patches) == 1
    assert lines["unpushed"].endswith("(not pushed)")
    assert lines["plain"].endswith(f"# local: {plain}, not under git")
    assert lines["gone"].endswith(f"# local: {tmp_path / 'gone'} (missing)")
    assert "TOKEN" not in "\n".join(lines.values())


def test_packages_in_one_repository_share_a_patch_and_the_runs_own_gets_none(tmp_path, monkeypatch):
    lib = repo(tmp_path / "lib")
    (lib / "a").mkdir()
    (lib / "b").mkdir()
    (lib / "train.py").write_text("print('edited')\n")
    main = repo(tmp_path / "main")
    (main / "train.py").write_text("print('main edited')\n")
    lines, patches = freeze_of(
        monkeypatch,
        [local("alpha", lib / "a"), local("beta", lib / "b"), local("me", main)],
        main_root=main,
    )
    assert list(patches) == ["git-alpha.patch"]
    assert lines["alpha"].endswith("patch: git-alpha.patch")
    assert lines["beta"].endswith("patch: git-alpha.patch")
    assert lines["me"].endswith(f"# local: {main}, the run's repository (see run.json git)")


def test_only_the_first_local_packages_are_inspected(tmp_path, monkeypatch):
    monkeypatch.setattr(_env, "MAX_LOCAL_PACKAGES", 1)
    first, second = repo(tmp_path / "first"), repo(tmp_path / "second")
    lines, _ = freeze_of(monkeypatch, [local("first", first), local("second", second)])
    assert lines["first"].endswith("(not pushed)")
    assert lines["second"] == f"==0.3  # local: {second}"


def test_capture_runs_no_program_from_the_repository_config(tmp_path, monkeypatch):
    r = repo(tmp_path / "r")
    marker = tmp_path / "ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f'#!/bin/sh\ntouch {marker}\ncat "$1" 2>/dev/null\nexit 0\n')
    hook.chmod(0o755)
    (r / ".gitattributes").write_text("*.txt diff=evil\n")
    (r / "notes.txt").write_text("a\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "attrs")
    git(r, "config", "core.fsmonitor", str(hook))
    git(r, "config", "diff.evil.textconv", str(hook))
    git(r, "config", "diff.external", str(hook))
    (r / "notes.txt").write_text("b\n")

    # the same repository does run the program when git is called plainly
    subprocess.run(["git", "diff", "HEAD"], cwd=r, capture_output=True, check=False)
    assert marker.exists()
    marker.unlink()

    monkeypatch.chdir(r)
    info, diff = _env.git_info()
    assert info is not None and info["dirty"] is True and "+b" in (diff or "")
    lines, _ = freeze_of(monkeypatch, [local("evil", r)])
    assert lines["evil"].endswith("patch: git-evil.patch")
    assert not marker.exists()


def test_a_patch_over_the_size_cap_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(_env, "MAX_PATCH_BYTES", 100)
    r = repo(tmp_path / "r")
    (r / "train.py").write_text("x = 1\n" * 100)
    monkeypatch.chdir(r)
    info, diff = _env.git_info()
    assert info is not None and diff == ""
    assert info["dirty"] is True and int(info["patch_bytes"]) > 100  # type: ignore[call-overload]
    lines, patches = freeze_of(monkeypatch, [local("big", r)])
    assert patches == {} and "patch too large" in lines["big"]

    with nb.init("p", run_name="big") as run:
        run.add_scalar({"loss": 1.0}, step=0)

    meta = json.loads((run.path / "run.json").read_text())
    assert meta["git"]["patch_bytes"] > 100
    assert not (run.path / "files" / "git.patch").exists()


def test_init_writes_the_patch_of_a_local_package(tmp_path, monkeypatch):
    lib = repo(tmp_path / "mylib")
    (lib / "train.py").write_text("print('lib edited')\n")
    main = repo(tmp_path / "main")
    real = list(_env.metadata.distributions())
    monkeypatch.setattr(
        _env.metadata, "distributions", lambda: [local("mylib", lib), local("main", main), *real]
    )
    monkeypatch.chdir(main)

    with nb.init("p", run_name="local-pkg") as run:
        run.add_scalar({"loss": 1.0}, step=0)

    files = run.path / "files"
    requirements = (files / "requirements.txt").read_text()
    assert "patch: git-mylib.patch" in requirements
    assert "the run's repository" in requirements
    assert "+print('lib edited')" in (files / "git-mylib.patch").read_text()
    assert not (files / "git.patch").exists()


def test_local_files_and_failures_keep_a_plain_line(tmp_path, monkeypatch):
    wheel = FakeDist("whl", "1.0", {"url": (tmp_path / "w.whl").as_uri(), "archive_info": {}})
    vcs = FakeDist(
        "fromgit",
        "2.0",
        {"url": (tmp_path / "src").as_uri(), "vcs_info": {"vcs": "git", "commit_id": "abc"}},
    )
    odd = FakeDist("odd", "1.0", {"url": "file:", "dir_info": {}})
    lines, patches = freeze_of(monkeypatch, [wheel, vcs, odd, local("lib", repo(tmp_path / "l"))])
    assert lines["whl"] == f"==1.0  # local: {tmp_path / 'w.whl'}"
    assert lines["fromgit"] == f"==2.0  # local: {tmp_path / 'src'}, git abc"
    assert lines["odd"].startswith("==1.0  # local:") and patches == {}

    def boom(*_args, **_kwargs):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(_env, "_describe", boom)
    lines, _ = freeze_of(monkeypatch, [local("lib", tmp_path / "l")])
    assert lines["lib"] == f"==0.3  # local: {tmp_path / 'l'}"
