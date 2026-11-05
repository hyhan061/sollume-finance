# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
# 2026-10-14 hoyeon.han: 기존 파일 관리·매뉴얼·브랜드 자산의 보안 전환 회귀.
from pathlib import Path
import sqlite3
import pytest
from streamlit.testing.v1 import AppTest
from test_auth_ui import ui_env, ROOT, _home, _assert_no_exception
from ui_components import render_static_asset_image


def test_administrator_file_manager_preserves_legacy_and_isolated_outputs(ui_env):
    old = Path('processed/매출_2026-10-13.xls')
    new = Path('processed/_session_outputs/owner/job/매출_2026-10-14.xls')
    private = Path('processed/secure_downloads/not-a-public-file')
    for path, content in ((old, b'legacy'), (new, b'new-owned-result'), (private, b'private-grant-only')):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    at = _home(ui_env).switch_page('pages/system.py').run()
    _assert_no_exception(at)
    with sqlite3.connect(ui_env.service.db_path) as connection:
        names = {row[0] for row in connection.execute('SELECT filename FROM security_downloads')}
    assert old.name in names and new.name in names
    assert private.name not in names
    assert new.read_bytes() == b'new-owned-result'


def test_manual_png_is_inline_and_cannot_read_arbitrary_files(ui_env):
    source = "from ui_components import render_static_asset_image\nrender_static_asset_image(" + repr(str(ROOT / 'assets/ecount_sales_download_guide.png')) + ", caption='다운로드 안내')"
    at = AppTest.from_string(source).run()
    _assert_no_exception(at)
    assert 'data:image/png;base64,' in at.markdown[0].value
    assert '/media/' not in at.markdown[0].value
    with pytest.raises(ValueError):
        render_static_asset_image(ui_env.service.db_path)
