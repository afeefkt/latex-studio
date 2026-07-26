# ── Document deletion tests ──
#
# Deletion is irreversible and its path comes straight off a URL, so the guards
# matter more than the happy path.

import shutil

import pytest

import app.docs as docs


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Point the module at a throwaway workspace with a base CV and one document."""
    ws = tmp_path / "workspace"
    (ws / "cv").mkdir(parents=True)
    (ws / "cv" / "main.tex").write_text("base", encoding="utf-8")
    (ws / "cv_acme").mkdir()
    (ws / "cv_acme" / "main.tex").write_text("generated", encoding="utf-8")

    docgit = tmp_path / ".docgit"
    (docgit / "cv_acme").mkdir(parents=True)
    (docgit / "cv_acme" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

    monkeypatch.setattr(docs, "WORKSPACE", ws)
    monkeypatch.setattr(docs, "DOCGIT_DIR", docgit)
    return ws, docgit


def test_deletes_document_and_its_git_dir(workspace):
    """The git dir lives outside the document tree and was being orphaned."""
    ws, docgit = workspace
    docs.delete_document("cv_acme")
    assert not (ws / "cv_acme").exists()
    assert not (docgit / "cv_acme").exists()


def test_refuses_to_delete_the_base_cv(workspace):
    """Designed templates copy their class file and photo out of 'cv' — losing it
    would silently degrade every CV generated afterwards."""
    ws, _ = workspace
    with pytest.raises(PermissionError):
        docs.delete_document("cv")
    assert (ws / "cv").exists()


@pytest.mark.parametrize("attempt", ["../secret", "cv_acme/../../escape", "/", ""])
def test_refuses_paths_outside_the_workspace(workspace, attempt):
    ws, _ = workspace
    with pytest.raises((PermissionError, FileNotFoundError)):
        docs.delete_document(attempt)
    assert (ws / "cv").exists()


def test_missing_document_is_not_found(workspace):
    with pytest.raises(FileNotFoundError):
        docs.delete_document("no_such_doc")


def test_deletes_read_only_files(workspace):
    """Git stores objects read-only; a plain rmtree aborts partway on Windows and
    leaves a half-deleted folder behind."""
    ws, _ = workspace
    nested = ws / "cv_acme" / ".git" / "objects"
    nested.mkdir(parents=True)
    obj = nested / "deadbeef"
    obj.write_text("x", encoding="utf-8")
    obj.chmod(0o444)

    docs.delete_document("cv_acme")
    assert not (ws / "cv_acme").exists()


def test_os_errors_are_not_reported_as_refusals(workspace, monkeypatch):
    """An EACCES from the filesystem must not surface as the base-CV guard, which
    is what PermissionError means to the caller."""
    def _boom(_path):
        raise PermissionError("file is locked")

    monkeypatch.setattr(docs, "_force_rmtree", _boom)
    with pytest.raises(RuntimeError):
        docs.delete_document("cv_acme")


# ── Asset copying ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,skipped", [
    ("fortysecondscv.cls", False),
    ("PIC_SQR.png", False),
    ("main.tex", False),
    ("Afeef_CV_2025.pdf", True),   # a whole previous CV was being duplicated
    ("out.pdf", True),
    ("main.aux", True),
    ("main.log", True),
    (".git", True),                # nested git dirs are how the submodule mess started
    (".build", True),
])
def test_only_compilable_assets_are_copied(name, skipped):
    assert docs._skip_asset(name) is skipped


def test_copytree_filter_drops_the_same_names():
    ignored = docs._ignore_assets("pics", ["PIC_SQR.png", "old_cv.pdf", ".git"])
    assert ignored == {"old_cv.pdf", ".git"}
