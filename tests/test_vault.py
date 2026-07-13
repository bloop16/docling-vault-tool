"""Tests fuer Zielordner-Analyse und Integrationsplan."""

from __future__ import annotations

import json

import docling_worker as dw


def test_analyze_new_target(tmp_path):
    profile = dw.analyze_vault(tmp_path / "gibt-es-nicht")
    assert profile.vault_type == "new"
    assert not profile.exists and profile.is_empty


def test_analyze_empty_folder(tmp_path):
    profile = dw.analyze_vault(tmp_path)
    assert profile.vault_type == "folder" and profile.is_empty


def test_analyze_obsidian_central_attachments(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text(
        json.dumps({"attachmentFolderPath": "attachments"})
    )
    (tmp_path / "Projekte").mkdir()
    (tmp_path / "attachments").mkdir()
    (tmp_path / "Projekte" / "n.md").write_text("---\ntitle: x\n---\nText")

    profile = dw.analyze_vault(tmp_path)
    assert profile.vault_type == "obsidian"
    assert profile.attachment_folder_resolved == "attachments"
    assert not profile.attachment_note_relative
    assert profile.uses_frontmatter is True

    cfg = dw.recommend_config(profile)
    assert cfg.notes_subdir == dw.DEFAULT_IMPORT_SUBDIR
    assert cfg.attachments_mode == "central"
    assert cfg.attachments_subdir == "attachments"
    assert cfg.add_frontmatter is True


def test_analyze_obsidian_adjacent_attachments_no_frontmatter(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text(
        json.dumps({"attachmentFolderPath": "./"})
    )
    (tmp_path / "n.md").write_text("kein frontmatter")

    profile = dw.analyze_vault(tmp_path)
    assert profile.attachment_note_relative is True

    cfg = dw.recommend_config(profile)
    assert cfg.attachments_mode == "adjacent"
    assert cfg.add_frontmatter is False


def test_analyze_logseq(tmp_path):
    (tmp_path / "logseq").mkdir()
    (tmp_path / "pages").mkdir()
    profile = dw.analyze_vault(tmp_path)
    assert profile.vault_type == "logseq"
    cfg = dw.recommend_config(profile)
    assert cfg.notes_subdir == "pages"
    assert cfg.attachments_subdir == "assets"


def test_describe_plan_is_human_readable(tmp_path):
    profile = dw.analyze_vault(tmp_path)
    cfg = dw.recommend_config(profile)
    lines = dw.describe_plan(profile, cfg)
    assert any("Notizen" in ln for ln in lines)
    assert any("Anhänge" in ln for ln in lines)
    assert any("Frontmatter" in ln for ln in lines)
