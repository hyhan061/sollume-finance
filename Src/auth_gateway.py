"""현재 회계앱 전용 인증·다운로드 게이트웨이.

2026-10-14 hoyeon.han: 모듈 import는 DB와 비밀키를 만들지 않는다.
운영 실행: gunicorn --pythonpath Src 'auth_gateway:create_app()'
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import logging
import os
import secrets
import time
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from flask import (
    Flask, abort, flash, get_flashed_messages, redirect, render_template,
    request, send_file, session, url_for,
)
from werkzeug.exceptions import HTTPException


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHALLENGE_SECONDS = 300
SESSION_SECONDS = 8 * 60 * 60
CSRF_SECONDS = 30 * 60


def _origin(value: str, *, development: bool, app_origin: bool = False) -> str:
    """2026-10-14 hoyeon.han: 리다이렉트·쿠키에 쓰는 출처는 고정된 값만 허용한다."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("인증 접속 주소 형식을 확인해 주세요.") from exc
    if (
        not parsed.hostname or parsed.username or parsed.password
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        or any(char in value for char in ("\\", "\r", "\n", "\t", " "))
    ):
        raise ValueError("인증 접속 주소에는 출처 주소만 지정해 주세요.")
    hostname = parsed.hostname.lower()
    loopback = hostname in ("localhost", "127.0.0.1", "::1")
    if development:
        if not loopback or parsed.scheme != "http":
            raise ValueError("개발 모드는 로컬 HTTP 주소에서만 사용할 수 있습니다.")
    elif parsed.scheme != "https" or loopback:
        raise ValueError("운영 모드에는 공개 도메인의 HTTPS 주소가 필요합니다.")
    if app_origin and not development:
        raise ValueError("개발용 업무 주소는 운영 모드에서 사용할 수 없습니다.")
    host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if parsed.scheme == "http" else 443
    return f"{parsed.scheme}://{host}" + (f":{port}" if port and port != default_port else "")


def load_security_settings(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """2026-10-14 hoyeon.han: 회계앱과 인증 서버가 같은 필수 설정을 검사한다."""
    supplied = dict(config or {})

    def value(key: str, default: Any = None) -> Any:
        return supplied[key] if key in supplied else os.environ.get(key, default)

    environment = value("AUTH_ENV", "production")
    if environment not in ("production", "development"):
        raise ValueError("AUTH_ENV는 production 또는 development로 지정해 주세요.")
    development = environment == "development"
    public_origin = value("AUTH_PUBLIC_ORIGIN", "http://localhost:8503" if development else None)
    if not public_origin:
        raise ValueError("AUTH_PUBLIC_ORIGIN에 공개 HTTPS 주소를 설정해 주세요.")
    public_origin = _origin(str(public_origin), development=development)
    app_origin = value("AUTH_DEV_APP_ORIGIN", "http://localhost:8501")
    if development:
        app_origin = _origin(str(app_origin), development=True, app_origin=True)
    elif "AUTH_DEV_APP_ORIGIN" in supplied or os.environ.get("AUTH_DEV_APP_ORIGIN"):
        raise ValueError("운영 모드에서는 AUTH_DEV_APP_ORIGIN을 설정하지 마세요.")
    else:
        app_origin = public_origin

    encryption_key = value("AUTH_ENCRYPTION_KEY")
    if not encryption_key:
        raise ValueError("AUTH_ENCRYPTION_KEY를 별도로 생성하여 설정해 주세요.")
    try:
        raw_key = base64.urlsafe_b64decode(str(encryption_key).encode("ascii"))
        if len(raw_key) != 32:
            raise ValueError("invalid key length")
        from cryptography.fernet import Fernet
        Fernet(str(encryption_key).encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("AUTH_ENCRYPTION_KEY의 Fernet 키 형식을 확인해 주세요.") from exc

    # 2026-10-14 hoyeon.han: 쿠키 서명과 MFA 암호화의 키 용도를 분리한다.
    signing_key = value("AUTH_SIGNING_KEY")
    if signing_key:
        if len(str(signing_key).encode("utf-8")) < 32:
            raise ValueError("AUTH_SIGNING_KEY는 32바이트 이상의 무작위 값으로 설정해 주세요.")
        signing_key = str(signing_key)
    else:
        signing_key = hashlib.sha256(b"SollumeLab CSRF session signing v1\0" + raw_key).hexdigest()

    networks_value = value("TRUSTED_PROXY_NETWORKS", "127.0.0.0/8,::1/128")
    try:
        parts = networks_value.split(",") if isinstance(networks_value, str) else networks_value
        networks = tuple(
            ipaddress.ip_network(str(part).strip(), strict=False)
            for part in parts if str(part).strip()
        )
    except ValueError as exc:
        raise ValueError("TRUSTED_PROXY_NETWORKS의 IP 대역을 확인해 주세요.") from exc
    if not networks or any(network.prefixlen == 0 for network in networks):
        raise ValueError("신뢰 프록시는 실제 내부 IP 대역만 지정해 주세요.")

    return {
        "AUTH_ENV": environment,
        "AUTH_PUBLIC_ORIGIN": public_origin,
        "AUTH_DEV_APP_ORIGIN": app_origin,
        "AUTH_ENCRYPTION_KEY": str(encryption_key),
        "AUTH_SIGNING_KEY": signing_key,
        "AUTH_DB_PATH": str(value("AUTH_DB_PATH", PROJECT_ROOT / "database" / "users.db")),
        "AUTH_DOWNLOAD_DIR": str(value("AUTH_DOWNLOAD_DIR", PROJECT_ROOT / "processed" / "secure_downloads")),
        "TRUSTED_PROXY_NETWORKS": networks,
    }


def session_cookie_name(settings: Mapping[str, Any]) -> str:
    return "sollume_dev_session" if settings["AUTH_ENV"] == "development" else "__Host-sollume_session"


def challenge_cookie_name(settings: Mapping[str, Any]) -> str:
    return "sollume_dev_challenge" if settings["AUTH_ENV"] == "development" else "__Host-sollume_challenge"


def _core_module():
    # 2026-10-14 hoyeon.han: WSGI와 패키지 실행을 모두 지원하되 실제 서비스 생성은 명시적으로 한다.
    if __package__:
        from . import security_service
    else:
        import security_service
    return security_service


@lru_cache(maxsize=4)
def _cached_service(db_path: str, encryption_key: str, download_dir: str):
    return _core_module().SecurityService(
        db_path=db_path, encryption_key=encryption_key, download_dir=download_dir,
    )


def get_service(settings: Mapping[str, Any]):
    """2026-10-14 hoyeon.han: 호출한 경우에만 공통 보안 저장소를 준비한다."""
    return _cached_service(
        settings["AUTH_DB_PATH"], settings["AUTH_ENCRYPTION_KEY"], settings["AUTH_DOWNLOAD_DIR"],
    )


def create_app(config: Mapping[str, Any] | None = None, service=None) -> Flask:
    """실제 계정 DB 대신 임시 서비스 객체를 주입해 전체 HTTP 흐름을 검증할 수 있다."""
    settings = load_security_settings(config)
    development = settings["AUTH_ENV"] == "development"
    core = _core_module()
    service = service if service is not None else get_service(settings)
    app = Flask(__name__, static_folder=None, template_folder=str(Path(__file__).parent / "templates"))
    app.config.update(
        SECRET_KEY=settings["AUTH_SIGNING_KEY"],
        SESSION_COOKIE_NAME="sollume_dev_csrf" if development else "__Host-sollume_csrf",
        SESSION_COOKIE_SECURE=not development,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_PATH="/",
        SESSION_COOKIE_DOMAIN=None,
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=16 * 1024,
        MAX_FORM_MEMORY_SIZE=16 * 1024,
        MAX_FORM_PARTS=20,
    )
    if config and "TESTING" in config:
        app.config["TESTING"] = bool(config["TESTING"])
    app.extensions["security_service"] = service
    app.extensions["security_settings"] = settings
    auth_cookie = session_cookie_name(settings)
    challenge_cookie = challenge_cookie_name(settings)

    def is_trusted_proxy() -> bool:
        try:
            remote = ipaddress.ip_address(request.remote_addr or "")
            if isinstance(remote, ipaddress.IPv6Address) and remote.ipv4_mapped:
                remote = remote.ipv4_mapped
            return any(remote in network for network in settings["TRUSTED_PROXY_NETWORKS"])
        except ValueError:
            return False

    def client_ip() -> str:
        # 2026-10-14 hoyeon.han: 인터넷 클라이언트가 전달한 프록시 헤더를 신뢰하지 않는다.
        if is_trusted_proxy():
            try:
                return str(ipaddress.ip_address(request.headers.get("X-Real-IP", "")))
            except ValueError:
                pass
        return request.remote_addr or ""

    def csrf_token() -> str:
        issued = session.get("csrf_issued", 0)
        if not session.get("csrf") or not isinstance(issued, (int, float)) or time.time() - issued > CSRF_SECONDS:
            session.clear()
            session["csrf"] = secrets.token_urlsafe(32)
            session["csrf_issued"] = time.time()
        return session["csrf"]

    def render(mode: str, **context):
        return render_template(
            "auth.html", mode=mode, csrf_token=csrf_token(),
            messages=get_flashed_messages(), nonce=getattr(request, "csp_nonce", ""),
            development=development, **context,
        )

    def delete_cookie(response, name: str):
        response.delete_cookie(name, path="/", secure=not development, httponly=True, samesite="Lax")

    def set_cookie(response, name: str, token: str, seconds: int):
        response.set_cookie(
            name, token, max_age=seconds, path="/", secure=not development,
            httponly=True, samesite="Lax",
        )

    def login_redirect():
        response = redirect(url_for("login_page"), code=303)
        delete_cookie(response, auth_cookie)
        delete_cookie(response, challenge_cookie)
        return response

    def challenge():
        token = request.cookies.get(challenge_cookie, "")
        if not token:
            return None, None
        try:
            return token, service.get_challenge(token)
        except core.SecurityError:
            return None, None

    def current_user(touch: bool = False):
        token = request.cookies.get(auth_cookie, "")
        if not token:
            return None
        try:
            return service.get_session(token, touch=touch)
        except core.SecurityError:
            return None

    def completed(token: str):
        session.clear()
        response = redirect(settings["AUTH_DEV_APP_ORIGIN"] + "/", code=303)
        set_cookie(response, auth_cookie, token, SESSION_SECONDS)
        delete_cookie(response, challenge_cookie)
        return response

    def requested_password(info: Mapping[str, Any]) -> str | None:
        if not info.get("must_change_password"):
            return None
        password = request.form.get("new_password", "")
        if not password or password != request.form.get("confirm_password", ""):
            raise core.SecurityError("새 비밀번호와 확인 입력을 일치시켜 주세요.")
        return password

    @app.before_request
    def protect_request():
        # 2026-10-14 hoyeon.han: 전달된 Host를 검사하고 리다이렉트에 사용하지 않는다.
        request.csp_nonce = secrets.token_urlsafe(18)
        try:
            host = urlsplit("//" + request.host)
            host.port
        except ValueError:
            abort(400)
        if development:
            allowed_host = host.hostname in ("localhost", "127.0.0.1", "::1")
        else:
            allowed_host = request.host.lower() == urlsplit(settings["AUTH_PUBLIC_ORIGIN"]).netloc
        if not allowed_host or host.username or host.password or host.path or host.query or host.fragment:
            abort(400)
        if request.path in ("/auth/check", "/health", "/auth/health") and not is_trusted_proxy():
            abort(404)
        # 2026-10-14 hoyeon.han: 운영 HTTP는 신뢰 프록시가 HTTPS를 종료한 경우에만 통과한다.
        if not development and request.path not in ("/health", "/auth/health"):
            if request.scheme != "https" and not (
                is_trusted_proxy() and request.headers.get("X-Forwarded-Proto") == "https"
            ):
                abort(400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # 출처 헤더가 없는 요청도 서명된 브라우저 nonce가 일치해야 한다.
            expected = settings["AUTH_PUBLIC_ORIGIN"]
            origin_header = request.headers.get("Origin")
            referer = request.headers.get("Referer")
            if origin_header:
                try:
                    actual = _origin(origin_header, development=development)
                except ValueError:
                    abort(400)
                if actual != expected:
                    abort(400)
            elif referer:
                source = urlsplit(referer)
                try:
                    actual = _origin(f"{source.scheme}://{source.netloc}", development=development)
                except ValueError:
                    abort(400)
                if actual != expected:
                    abort(400)
            if request.headers.get("Sec-Fetch-Site") in ("cross-site", "none"):
                abort(400)
            incoming = request.form.get("csrf_token", "")
            stored = session.get("csrf", "")
            issued = session.get("csrf_issued", 0)
            if (
                not incoming or not stored or not isinstance(issued, (int, float))
                or not 0 <= time.time() - issued <= CSRF_SECONDS
                or not secrets.compare_digest(incoming.encode("utf-8"), stored.encode("utf-8"))
            ):
                abort(400)

    @app.after_request
    def security_headers(response):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # 2026-10-14 hoyeon.han: same-origin 폼 POST의 Origin을 유지하고 외부에는 Referer를 보내지 않는다.
        # response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # 2026-10-14 hoyeon.han: 개발 인증 포트에서 업무 포트로의 고정 303 이동만 추가 허용한다.
        form_origins = "'self'" + (" " + settings["AUTH_DEV_APP_ORIGIN"] if development else "")
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            f"style-src 'nonce-{getattr(request, 'csp_nonce', '')}'; "
            f"img-src 'self' data:; form-action {form_origins}; base-uri 'none'; frame-ancestors 'none'"
        )
        if not development:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/health")
    @app.get("/auth/health")
    def health():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/auth/check")
    def check():
        # 2026-10-14 hoyeon.han: nginx auth_request 응답은 이동 없이 성공/거부만 반환한다.
        return ("", 200) if current_user() else ("", 401)

    @app.route("/auth/login", methods=["GET", "POST"])
    def login_page():
        if request.method == "GET":
            if current_user():
                return redirect(settings["AUTH_DEV_APP_ORIGIN"] + "/", code=303)
            return render("login")
        try:
            info = service.begin_login(
                request.form.get("username", ""), request.form.get("password", ""), ip_address=client_ip(),
            )
            response = redirect(url_for("enroll_page" if info["needs_enrollment"] else "mfa_page"), code=303)
            set_cookie(response, challenge_cookie, info["token"], CHALLENGE_SECONDS)
            return response
        except core.SecurityError:
            flash("로그인 정보를 확인하거나 관리자에게 문의해 주세요.")
            return redirect(url_for("login_page"), code=303)

    @app.route("/auth/mfa", methods=["GET", "POST"])
    def mfa_page():
        token, info = challenge()
        if not info:
            return login_redirect()
        if info["needs_enrollment"]:
            return redirect(url_for("enroll_page"), code=303)
        if request.method == "GET":
            return render("mfa", must_change_password=info.get("must_change_password", False))
        try:
            return completed(service.complete_login(
                token, request.form.get("otp", ""), new_password=requested_password(info), ip_address=client_ip(),
            ))
        except core.SecurityError:
            flash("인증 번호와 새 비밀번호 입력을 확인해 주세요. 반복 실패 시 관리자에게 문의해 주세요.")
            return redirect(url_for("mfa_page"), code=303)

    @app.route("/auth/enroll", methods=["GET", "POST"])
    def enroll_page():
        token, info = challenge()
        if not info:
            return login_redirect()
        if not info["needs_enrollment"]:
            return redirect(url_for("mfa_page"), code=303)
        if request.method == "POST":
            try:
                if request.form.get("stage") == "prepare":
                    service.prepare_enrollment(token, request.form.get("enrollment_code", ""))
                    return redirect(url_for("enroll_page"), code=303)
                if request.form.get("stage") == "complete" and info.get("pending_secret"):
                    return completed(service.complete_login(
                        token, request.form.get("otp", ""), new_password=requested_password(info), ip_address=client_ip(),
                    ))
                raise core.SecurityError("등록 순서를 확인해 주세요.")
            except core.SecurityError:
                flash("등록 코드, 인증 번호 또는 비밀번호 입력을 확인해 주세요. 등록 코드는 관리자에게 요청하세요.")
                return redirect(url_for("enroll_page"), code=303)
        secret = info.get("pending_secret")
        qr_uri = None
        if secret:
            import pyotp
            import qrcode
            from qrcode.image.svg import SvgPathImage
            image = qrcode.make(
                pyotp.TOTP(secret).provisioning_uri(name=info["username"], issuer_name="SollumeLab 회계"),
                image_factory=SvgPathImage, box_size=5, border=4,
            )
            buffer = BytesIO()
            image.save(buffer)
            qr_uri = "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        return render(
            "enroll", qr_uri=qr_uri, secret=secret,
            must_change_password=info.get("must_change_password", False),
        )

    @app.route("/auth/logout", methods=["GET", "POST"])
    def logout_page():
        if request.method == "GET":
            if not current_user():
                return login_redirect()
            return render("logout")
        token = request.cookies.get(auth_cookie)
        if token:
            service.revoke_session(token)
        session.clear()
        return login_redirect()

    @app.route("/auth/account", methods=["GET", "POST"])
    def account_page():
        if not current_user(touch=True):
            return login_redirect()
        if request.method == "GET":
            return render("account", app_url=settings["AUTH_DEV_APP_ORIGIN"] + "/")
        try:
            new_password = request.form.get("new_password", "")
            if new_password != request.form.get("confirm_password", ""):
                raise core.SecurityError("비밀번호 확인이 일치하지 않습니다.")
            service.change_own_password(
                request.cookies.get(auth_cookie, ""), request.form.get("current_password", ""),
                new_password, request.form.get("otp", ""),
            )
            session.clear()
            response = login_redirect()
            flash("비밀번호가 변경되었습니다. 새 비밀번호와 인증 앱으로 다시 로그인해 주세요.")
            return response
        except core.SecurityError:
            flash("현재 비밀번호, 새 비밀번호 또는 인증 번호를 확인해 주세요.")
            return redirect(url_for("account_page"), code=303)

    @app.get("/downloads/<download_id>")
    def download(download_id: str):
        if not current_user(touch=True):
            abort(401)
        try:
            item = service.get_download(request.cookies.get(auth_cookie, ""), download_id)
        except core.SecurityError:
            abort(403)
        filename = str(item["filename"])
        filename = "".join("_" if char in "\\/\r\n\x00" or ord(char) < 32 else char for char in filename)
        return send_file(
            item["path"], as_attachment=True, download_name=filename or "다운로드.xlsx",
            mimetype=item["mime"], conditional=True,
        )

    @app.errorhandler(HTTPException)
    def http_error(error):
        message = {
            400: "요청을 확인할 수 없습니다. 로그인 화면을 새로 열고 다시 시도해 주세요.",
            401: "로그인이 만료되었거나 필요합니다. 다시 로그인해 주세요.",
            403: "이 작업 또는 파일에 접근할 권한이 없습니다.",
            404: "요청한 주소를 찾을 수 없습니다.",
            413: "입력한 내용이 너무 큽니다. 입력 길이를 확인해 주세요.",
        }.get(error.code, "요청을 처리할 수 없습니다. 관리자에게 문의해 주세요.")
        return render("error", error_message=message), error.code or 500

    @app.errorhandler(Exception)
    def unexpected_error(error):
        # 2026-10-14 hoyeon.han: 입력값·비밀번호·OTP·토큰을 오류 로그에 남기지 않는다.
        logger.error("인증 요청 처리 오류: %s", type(error).__name__)
        return render("error", error_message="인증 서비스를 이용할 수 없습니다. 관리자에게 문의해 주세요."), 503

    return app


if __name__ == "__main__":
    # 2026-10-14 hoyeon.han: 개발 직접 실행은 loopback에만 바인딩한다. 운영은 Gunicorn을 사용한다.
    settings = load_security_settings()
    if settings["AUTH_ENV"] != "development":
        raise SystemExit("운영 모드에서는 Gunicorn으로 인증 서버를 실행해 주세요.")
    create_app(settings).run(host="127.0.0.1", port=8503, debug=False)
