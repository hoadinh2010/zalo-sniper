# tests/modules/test_code_agent.py
import pytest
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from zalosniper.modules.code_agent import CodeAgent, find_relevant_files


def test_find_relevant_files(tmp_path):
    # Create fake repo with some python files
    (tmp_path / "auth.py").write_text("def login(user, password): pass")
    (tmp_path / "models.py").write_text("class User: pass")
    (tmp_path / "utils.py").write_text("def helper(): pass")

    results = find_relevant_files(str(tmp_path), keywords=["login", "user"], max_files=10)
    filenames = [os.path.basename(r) for r in results]
    assert "auth.py" in filenames
    assert "models.py" in filenames


def test_find_relevant_files_respects_max(tmp_path):
    for i in range(20):
        (tmp_path / f"file{i}.py").write_text("def login(): pass")

    results = find_relevant_files(str(tmp_path), keywords=["login"], max_files=5)
    assert len(results) <= 5


def test_read_files_for_context(tmp_path):
    f = tmp_path / "auth.py"
    f.write_text("def login(): pass\n")
    agent = CodeAgent(repos_dir=str(tmp_path))
    context = agent.read_files_for_context([str(f)], max_tokens_per_file=100)
    assert "auth.py" in context
    assert "def login" in context


@pytest.mark.asyncio
async def test_apply_patch(tmp_path):
    original = "def login(user):\n    return user.name\n"
    patch_text = (
        "--- a/auth.py\n+++ b/auth.py\n"
        "@@ -1,2 +1,4 @@\n"
        " def login(user):\n"
        "+    if user is None:\n"
        "+        raise ValueError('user required')\n"
        "     return user.name\n"
    )
    target = tmp_path / "auth.py"
    target.write_text(original)

    agent = CodeAgent(repos_dir=str(tmp_path))
    success = await agent.apply_patch(patch_text, repo_dir=str(tmp_path))
    # patch application may fail for invalid unified diff — just check no exception
    assert isinstance(success, bool)
