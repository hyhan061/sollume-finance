"""2026-11-04 hoyeon.han: 게시 전 실제 이미지의 인증·정산 동작을 격리 검증한다.

실행 중인 서버·DB·인증 키는 사용하지 않는다. 가상환경에서 임시 계정과 파일로
검사하며, 결과에는 검사 이름만 기록하고 비밀번호·OTP·세션·키를 출력하지 않는다.
"""
from __future__ import annotations

import html
import json
import logging
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time


def _check(checks: list[str], name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    checks.append(name)


def verify_settlement(checks: list[str], temporary: Path) -> None:
    import openpyxl
    import pandas as pd
    import ecount_settlement as es
    import seller_settlement as ss

    common = {"작성일자": "2026-11-04", "회사명": "검증업체", "품목": "상품",
              "구분": "발주", "수량": 1, "단가": 10000, "합계": 10000,
              "비고": "검증셀러", "배송비": 0, "도선료": 0}
    data = pd.DataFrame([{**common, **row} for row in (
        {}, {"품목": "배송비", "수량": 0, "합계": 3000},
        {"품목": "도선료", "합계": 2000},
        {"품목": "배송비", "수량": -1, "합계": -500},
    )])
    before = data.copy(deep=True)
    for mode in (ss.DETAIL_MODE_SINGLE, ss.DETAIL_MODE_PER_SELLER):
        plan = es.build_ecount_sheet_plan(data, detail_mode=mode)
        details = ({ss.DETAIL_SHEET_NAME: plan["detail_df"]}
                   if mode == ss.DETAIL_MODE_SINGLE else plan["detail_sheets"])
        _check(checks, "settlement_summary_" + mode, plan["overall_df"]["합계"].sum() == 14500)
        for detail in details.values():
            amounts = detail[["상품매출", "판매배송비", "도선료"]]
            _check(checks, "settlement_detail_" + mode, amounts.sum().tolist() == [10000, 2500, 2000])
        path = temporary / (mode + ".xlsx")
        ss.write_seller_settlement_xlsx(str(path), ss.TITLE_SALE, "검증 기간", plan)
        book = openpyxl.load_workbook(path, data_only=True)
        try:
            for name, detail in details.items():
                total = len(detail) + 2
                _check(checks, "settlement_excel_" + mode,
                       [book[name].cell(total, col).value for col in (11, 12, 13)] == [10000, 2500, 2000]
                       and book[name].cell(total + 3, 11).value == 14500)
        finally:
            book.close()
    pd.testing.assert_frame_equal(data, before)
    _check(checks, "settlement_source_preserved", True)


def verify_authentication(checks: list[str], temporary: Path) -> None:
    from auth_gateway import create_app
    from cryptography.fernet import Fernet
    from security_service import SecurityService, SecurityError

    key = Fernet.generate_key().decode("ascii")
    database, downloads = temporary / "users.db", temporary / "downloads"
    service = SecurityService(str(database), key, str(downloads))
    clock = [time.time()]
    service._now = lambda: clock[0]
    origin = "https://office1.sollumeesthe.com"
    settings = {"AUTH_ENV": "production", "AUTH_PUBLIC_ORIGIN": origin,
                "AUTH_ENCRYPTION_KEY": key, "AUTH_DB_PATH": str(database),
                "AUTH_DOWNLOAD_DIR": str(downloads), "TRUSTED_PROXY_NETWORKS": "127.0.0.1/32",
                "TESTING": True}
    app = create_app(settings, service=service)
    owner, other, anonymous = app.test_client(), app.test_client(), app.test_client()
    initial = "Image initial phrase " + secrets.token_urlsafe(20)
    replacement = "Image replacement phrase " + secrets.token_urlsafe(20)

    def get(client, path):
        return client.get(path, base_url=origin)

    def post(client, path, data):
        response = get(client, path)
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        if not match:
            raise AssertionError("csrf_form_missing")
        return client.post(path, base_url=origin, headers={"Origin": origin},
                           data={"csrf_token": html.unescape(match.group(1)), **data})

    def cookie(client, name="__Host-sollume_session"):
        return client.get_cookie(name, domain="office1.sollumeesthe.com")

    def enroll(client, username):
        user = service.bootstrap_user(username, initial, is_admin=False,
                                      permissions=["settlement-ecount"])
        code = service.issue_enrollment_local(user["id"])
        response = post(client, "/auth/login", {"username": username, "password": initial})
        _check(checks, "password_only_denied_" + username,
               response.status_code == 303 and response.location == "/auth/enroll"
               and cookie(client) is None and get(client, "/auth/check").status_code == 401)
        response = post(client, "/auth/enroll", {"stage": "prepare", "enrollment_code": code})
        _check(checks, "enrollment_prepared_" + username, response.status_code == 303)
        pending = cookie(client, "__Host-sollume_challenge")
        secret = service.get_challenge(pending.value)["pending_secret"]
        response = post(client, "/auth/enroll", {"stage": "complete",
                        "otp": service._totp(secret, int(clock[0] // 30)),
                        "new_password": replacement, "confirm_password": replacement})
        session = cookie(client)
        _check(checks, "mfa_completed_" + username,
               response.status_code == 303 and response.location == origin + "/"
               and session is not None and session.secure and session.http_only
               and get(client, "/auth/check").status_code == 200)
        return user, session.value

    _check(checks, "anonymous_auth_denied", get(anonymous, "/auth/check").status_code == 401)
    user, token = enroll(owner, "image.owner")
    _, other_token = enroll(other, "image.other")
    content = b"Synthetic settlement output"
    grant = service.register_download(token, content, "synthetic.xlsx",
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "settlement-ecount")
    response = get(owner, "/downloads/" + grant)
    _check(checks, "owner_download_allowed", response.status_code == 200 and response.data == content)
    _check(checks, "anonymous_download_denied", get(anonymous, "/downloads/" + grant).status_code == 401)
    _check(checks, "other_owner_download_denied", get(other, "/downloads/" + grant).status_code == 403)
    denied = False
    try:
        service.require_permission(other_token, "daily-voucher")
    except SecurityError:
        denied = True
    _check(checks, "unassigned_page_denied", denied)
    service.update_user_local(user["id"], permissions=[])
    _check(checks, "permission_revocation_denied",
           get(owner, "/auth/check").status_code == 401
           and get(owner, "/downloads/" + grant).status_code == 401)


def verify_runtime(root: Path | None = None) -> list[str]:
    checks: list[str] = []
    _check(checks, "python_virtual_environment", sys.prefix != sys.base_prefix)
    root = root or Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "Src"), str(root / "scripts")]
    import auth_gateway  # noqa: F401
    import security_service  # noqa: F401
    import secure_downloads  # noqa: F401
    import manage_users  # noqa: F401
    import init_users_db  # noqa: F401
    _check(checks, "authentication_modules_available", True)
    page = (root / "pages/settlement_ecount.py").read_text(encoding="utf-8")
    _check(checks, "settlement_permission_guard", "auth.require_permission('settlement-ecount')" in page)
    _check(checks, "settlement_protected_download", "protected_download(" in page)
    with tempfile.TemporaryDirectory(prefix="sollume-image-verification-", dir="/tmp") as folder:
        temporary = Path(folder)
        verify_settlement(checks, temporary)
        verify_authentication(checks, temporary)
    _check(checks, "temporary_fixture_removed", not temporary.exists())
    return checks


def main() -> int:
    # 2026-11-04 hoyeon.han: 예외 메시지에도 합성 인증 비밀이 포함될 수 있어 유형만 출력한다.
    logging.disable(logging.CRITICAL)
    try:
        checks = verify_runtime()
    except Exception as exc:
        print(json.dumps({"passed": False, "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({"passed": True, "checks": checks, "check_count": len(checks)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
