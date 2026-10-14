# 2026-10-14 hoyeon.han: 파일을 사용자와 세션에 귀속하고 인증된 HTTP 경로로 제공.
import hashlib
from urllib.parse import quote

import streamlit as st


def secure_download_button(label, data, file_name=None, mime=None, key=None,
                           page_id=None, admin_only=False, disabled=False,
                           use_container_width=False, type="secondary", help=None,
                           icon=None, **unused):
    """Streamlit /media 대신 불변 파일과 만료 있는 다운로드 권한을 사용."""
    import auth
    if not page_id:
        raise ValueError("다운로드 화면 권한을 지정해야 합니다.")
    auth.require_permission(page_id)
    if admin_only:
        auth.require_admin()
    if disabled:
        st.button(label, disabled=True, key=key, help=help,
                  use_container_width=use_container_width)
        return False
    if isinstance(data, str):
        payload = data.encode("utf-8")
        mime = mime or "text/plain"
    elif isinstance(data, (bytes, bytearray, memoryview)):
        payload = bytes(data)
    elif hasattr(data, "getvalue"):
        payload = data.getvalue()
    else:
        position = data.tell() if hasattr(data, "tell") else None
        payload = data.read()
        if position is not None:
            data.seek(position)
    if not isinstance(payload, bytes):
        raise ValueError("다운로드 자료는 파일 또는 바이트 형식이어야 합니다.")
    name = file_name or "download.bin"
    mime = mime or "application/octet-stream"
    identity = hashlib.sha256(payload).hexdigest()
    cache_key = (str(key), page_id, name, mime, identity, bool(admin_only))
    cache = st.session_state.setdefault("_secure_download_grants", {})
    service = auth.get_service()
    token = auth.get_session_token()
    grant_id = cache.get(cache_key)
    if grant_id:
        try:
            service.get_download(token, grant_id)
        except Exception:
            grant_id = None
    if not grant_id:
        grant_id = service.register_download(token, payload, name, mime, page_id,
                                             admin_only=admin_only)
        cache[cache_key] = grant_id
    origin = auth.get_settings()["AUTH_PUBLIC_ORIGIN"].rstrip("/")
    st.link_button(label, origin + "/downloads/" + quote(grant_id, safe=""),
                   help=help, type=type, icon=icon,
                   use_container_width=use_container_width)
    return False
