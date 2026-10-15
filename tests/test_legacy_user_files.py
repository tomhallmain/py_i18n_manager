"""utils/legacy_user_files.py: user files left in the repo move to the app data dir."""

import os

import pytest

from utils import app_paths, legacy_user_files


@pytest.fixture
def roots(tmp_path):
    """A fake repo and an empty app data dir."""
    repo, data = tmp_path / "repo", tmp_path / "data"
    repo.mkdir()
    return repo, data


def _write(path, text, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_every_legacy_file_moves_to_the_same_relative_path(roots):
    repo, data = roots
    _write(repo / "configs" / "user_config.json", "config")
    _write(repo / "configs" / "default_config.json", "bundled")
    _write(repo / "app_info_cache.json", "cache")
    _write(repo / "app_info_cache.json.bak", "bak1")
    _write(repo / "app_info_cache.json.bak4", "bak4")
    _write(repo / "llm_review_output" / "2026-10-01_10-00-00" / "01_batch.md", "review")

    legacy_user_files.move_legacy_user_files(str(repo), str(data))

    assert (data / "configs" / "user_config.json").read_text(encoding="utf-8") == "config"
    assert (data / "app_info_cache.json").read_text(encoding="utf-8") == "cache"
    assert (data / "app_info_cache.json.bak").read_text(encoding="utf-8") == "bak1"
    assert (data / "app_info_cache.json.bak4").read_text(encoding="utf-8") == "bak4"
    assert (data / "llm_review_output" / "2026-10-01_10-00-00" / "01_batch.md").exists()
    assert not (repo / "configs" / "user_config.json").exists()
    assert not (repo / "app_info_cache.json").exists()
    assert not (repo / "llm_review_output").exists()
    # The bundled defaults are not user data.
    assert (repo / "configs" / "default_config.json").exists()
    assert not (data / "configs" / "default_config.json").exists()


def test_an_older_target_is_replaced(roots):
    """E.g. the near-empty cache a build wrote before the checkout ever ran."""
    repo, data = roots
    _write(repo / "app_info_cache.json", "real", mtime=1_000_000)
    _write(data / "app_info_cache.json", "from a build", mtime=2_000_000)
    legacy_user_files.move_legacy_user_files(str(repo), str(data))
    assert (data / "app_info_cache.json").read_text(encoding="utf-8") == "real"
    assert not (repo / "app_info_cache.json").exists()


def test_a_target_with_the_same_time_is_replaced(roots):
    repo, data = roots
    _write(repo / "app_info_cache.json", "legacy", mtime=1_000_000)
    _write(data / "app_info_cache.json", "target", mtime=1_000_000)
    legacy_user_files.move_legacy_user_files(str(repo), str(data))
    assert (data / "app_info_cache.json").read_text(encoding="utf-8") == "legacy"


def test_a_newer_legacy_file_leaves_both(roots):
    repo, data = roots
    _write(repo / "configs" / "user_config.json", "legacy", mtime=2_000_000)
    _write(data / "configs" / "user_config.json", "target", mtime=1_000_000)
    legacy_user_files.move_legacy_user_files(str(repo), str(data))
    assert (repo / "configs" / "user_config.json").read_text(encoding="utf-8") == "legacy"
    assert (data / "configs" / "user_config.json").read_text(encoding="utf-8") == "target"


def test_folders_merge_file_by_file(roots):
    repo, data = roots
    _write(repo / "llm_review_output" / "run_a" / "01.md", "a")
    _write(repo / "llm_review_output" / "run_b" / "01.md", "legacy b", mtime=2_000_000)
    _write(data / "llm_review_output" / "run_b" / "01.md", "target b", mtime=1_000_000)
    _write(data / "llm_review_output" / "run_c" / "01.md", "c")

    legacy_user_files.move_legacy_user_files(str(repo), str(data))

    assert (data / "llm_review_output" / "run_a" / "01.md").read_text(encoding="utf-8") == "a"
    assert (data / "llm_review_output" / "run_c" / "01.md").read_text(encoding="utf-8") == "c"
    # The newer legacy file stays, so its folder does too; the emptied one is gone.
    assert (repo / "llm_review_output" / "run_b" / "01.md").exists()
    assert not (repo / "llm_review_output" / "run_a").exists()


def test_a_file_never_replaces_a_folder(roots):
    repo, data = roots
    _write(repo / "app_info_cache.json", "legacy")
    (data / "app_info_cache.json").mkdir(parents=True)
    legacy_user_files.move_legacy_user_files(str(repo), str(data))
    assert (repo / "app_info_cache.json").exists()
    assert (data / "app_info_cache.json").is_dir()


def test_a_move_across_drives_copies_and_deletes(roots, monkeypatch):
    repo, data = roots
    _write(repo / "app_info_cache.json", "cache")

    def no_cross_device_replace(source, target):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(legacy_user_files.os, "replace", no_cross_device_replace)
    legacy_user_files.move_legacy_user_files(str(repo), str(data))
    assert (data / "app_info_cache.json").read_text(encoding="utf-8") == "cache"
    assert not (repo / "app_info_cache.json").exists()


def test_nothing_to_move(roots):
    repo, data = roots
    legacy_user_files.move_legacy_user_files(str(repo), str(data))
    assert not data.exists()


# migrate_once: when the move runs. The move itself is stubbed, so the real
# repo's files are never touched.

@pytest.fixture
def moves(monkeypatch, tmp_path):
    """Arms migrate_once with no overrides set; returns the moves it asks for."""
    calls = []
    monkeypatch.setattr(legacy_user_files, "_done", False)
    monkeypatch.setattr(legacy_user_files, "move_legacy_user_files",
                        lambda source, target: calls.append((source, target)))
    monkeypatch.setattr(app_paths, "default_app_data_dir", lambda: str(tmp_path / "data"))
    for name in app_paths.OVERRIDE_ENVS:
        monkeypatch.delenv(name, raising=False)
    return calls


def test_moves_from_the_repo_to_the_real_data_dir_once(moves, tmp_path):
    legacy_user_files.migrate_once()
    legacy_user_files.migrate_once()
    assert moves == [(app_paths.RESOURCE_ROOT, str(tmp_path / "data"))]


def test_user_data_path_moves_first(moves):
    app_paths.user_data_path("settings.json")
    assert len(moves) == 1


@pytest.mark.parametrize("name", app_paths.OVERRIDE_ENVS)
def test_no_move_under_an_override(moves, monkeypatch, tmp_path, name):
    monkeypatch.setenv(name, str(tmp_path / "elsewhere"))
    legacy_user_files.migrate_once()
    assert moves == []


def test_no_move_in_a_build(moves, monkeypatch):
    monkeypatch.setattr(app_paths, "IS_BUILD", True)
    legacy_user_files.migrate_once()
    assert moves == []


def test_a_failed_move_does_not_stop_the_start(moves, monkeypatch):
    def fail(source, target):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(legacy_user_files, "move_legacy_user_files", fail)
    legacy_user_files.migrate_once()
