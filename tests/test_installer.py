import io
import json
import zipfile

import pytest

from tgmcp_desk.core import installer
from tgmcp_desk.core.installer import InstallError, inspect_dir, install_source, uv_asset_name


def make_archive(extra=None, root="telegram-mcp-3.2.98"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{root}/pyproject.toml", '[project]\nname = "telegram-mcp"\n')
        zf.writestr(f"{root}/telegram_mcp/__init__.py", "")
        zf.writestr(f"{root}/main.py", "print('hi')\n")
        zf.writestr(f"{root}/.env.example", "X=1\n")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_install_into_empty_and_upgrade_keeps_user_files(tmp_path):
    target = tmp_path / "tm"
    install_source(make_archive(), target, "v3.2.98")
    st = inspect_dir(target)
    assert st.managed and st.is_upstream and st.tag == "v3.2.98"

    (target / ".env").write_text("SECRET=1\n")
    (target / "telegram_session.session").write_bytes(b"s")
    (target / "logs").mkdir()
    (target / "old_upstream_file.py").write_text("stale")
    install_source(make_archive(root="telegram-mcp-3.3.0"), target, "v3.3.0")
    assert (target / ".env").read_text() == "SECRET=1\n"
    assert (target / "telegram_session.session").exists()
    assert (target / "logs").is_dir()
    assert not (target / "old_upstream_file.py").exists()
    assert json.loads((target / installer.MARKER).read_text())["tag"] == "v3.3.0"


def test_refuses_unrelated_folder(tmp_path):
    (tmp_path / "my_document.txt").write_text("important")
    with pytest.raises(InstallError):
        install_source(make_archive(), tmp_path, "v1")
    assert (tmp_path / "my_document.txt").exists()


def test_refuses_path_traversal(tmp_path):
    bad = make_archive({"../evil.txt": "x"})
    with pytest.raises(InstallError):
        install_source(bad, tmp_path / "t", "v1")


def test_rejects_wrong_archive(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other-1.0/pyproject.toml", "")
    with pytest.raises(InstallError):
        install_source(buf.getvalue(), tmp_path / "t", "v1")


def test_adopt_existing_checkout_is_recognised(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "telegram-mcp"\n')
    (tmp_path / "telegram_mcp").mkdir()
    (tmp_path / ".env").write_text("A=1")
    st = inspect_dir(tmp_path)
    assert st.is_upstream and not st.managed and st.has_env


def test_uv_asset_name():
    assert uv_asset_name("Windows", "AMD64") == "uv-x86_64-pc-windows-msvc.zip"
    assert uv_asset_name("Windows", "ARM64") == "uv-aarch64-pc-windows-msvc.zip"
    assert uv_asset_name("Linux", "x86_64") == "uv-x86_64-unknown-linux-gnu.tar.gz"
