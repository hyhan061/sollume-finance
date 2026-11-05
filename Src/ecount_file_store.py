# 2026-11-04 hoyeon.han: 이카운트 판매/구매 최신 원본의 서버 저장소 신규 구현.
"""이카운트 원본을 유형별 최신 한 개씩 보관하는 순수 파일 저장소.

원본 Excel과 메타데이터를 하나의 ZIP에 넣어 원자적으로 교체한다.
읽는 도중 다른 사용자가 새 원본을 저장해도 바이트와 메타데이터는
항상 동일한 업로드에 속한다. ZIP 내부의 원본 바이트는 변경하지 않는다.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ecount_settlement as es
from settlement import TYPE_PURCHASE, TYPE_SALE


class EcountFileStore:
    """매출/매입 최신 원본과 메타데이터를 함께 저장하고 다시 읽는다."""

    _TYPE_DIRECTORIES = {TYPE_SALE: "sale", TYPE_PURCHASE: "purchase"}
    _ORIGINAL_MEMBER = "original.xlsx"
    _METADATA_MEMBER = "metadata.json"
    _KST = timezone(timedelta(hours=9), name="KST")

    def __init__(self, store_dir: str | os.PathLike[str] = "order_data/ecount"):
        # 2026-11-04 hoyeon.han: 조회만 할 때는 디렉토리를 만들지 않는다.
        self.store_dir = Path(store_dir)
        self.logger = logging.getLogger(__name__)

    def _bundle_path(self, doc_type: str) -> Path:
        if not isinstance(doc_type, str) or doc_type not in self._TYPE_DIRECTORIES:
            raise ValueError("정산서 유형은 매출 또는 매입을 선택해 주세요.")
        return self.store_dir / self._TYPE_DIRECTORIES[doc_type] / "current.zip"

    def load(self, doc_type: str) -> dict[str, Any] | None:
        """저장된 원본 바이트와 메타데이터를 반환한다. 없으면 None.

        반환 dict의 ``file_bytes``는 업로드된 원본 그대로이며, ``sha256``은
        이름이나 크기가 같은 수정본도 구별할 수 있는 내용 식별자다.
        손상된 저장본은 빈 저장소로 취급하지 않고 명시적으로 알린다.
        """
        path = self._bundle_path(doc_type)
        try:
            # 2026-11-04 hoyeon.han: 교체 전후 파일 중 하나를 한 번만 열어 읽는다.
            with zipfile.ZipFile(path, "r") as bundle:
                if set(bundle.namelist()) != {
                    self._ORIGINAL_MEMBER,
                    self._METADATA_MEMBER,
                }:
                    raise ValueError("저장된 이카운트 파일의 구성 정보가 올바르지 않습니다.")
                metadata = json.loads(bundle.read(self._METADATA_MEMBER))
                file_bytes = bundle.read(self._ORIGINAL_MEMBER)
            if not isinstance(metadata, dict):
                raise ValueError("저장된 이카운트 파일의 정보가 올바르지 않습니다.")
            if (
                metadata.get("doc_type") != doc_type
                or metadata.get("size_bytes") != len(file_bytes)
                or metadata.get("sha256") != hashlib.sha256(file_bytes).hexdigest()
                or not isinstance(metadata.get("original_name"), str)
            ):
                raise ValueError("저장된 이카운트 원본과 파일 정보가 일치하지 않습니다.")
            return {**metadata, "file_bytes": file_bytes}
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            self.logger.error("이카운트 %s 저장본 읽기 실패", doc_type, exc_info=True)
            if isinstance(exc, OSError):
                raise OSError(
                    "저장된 이카운트 파일을 읽을 수 없습니다. 서버 저장 경로와 권한을 확인해 주세요."
                ) from exc
            raise ValueError(
                "저장된 이카운트 파일이 손상되었습니다. 해당 유형의 원본 파일을 다시 업로드해 주세요."
            ) from exc

    def save(
        self,
        file_bytes: bytes,
        original_name: str,
        doc_type: str,
        uploaded_by: str | None = None,
    ) -> dict[str, Any]:
        """검증한 파일로 해당 유형의 최신 원본만 교체하고 저장 정보를 반환한다.

        유형 불일치, 지원하지 않는 금액/수량, 파일 쓰기 실패가 발생하면
        기존 저장본을 그대로 유지한다. ``original_name``은 표시용으로만
        기록하며, 서버의 저장 경로를 결정하는 데 사용하지 않는다.
        """
        path = self._bundle_path(doc_type)
        temporary_path: Path | None = None
        try:
            if not isinstance(file_bytes, (bytes, bytearray, memoryview)) or not file_bytes:
                raise ValueError("업로드한 이카운트 파일이 비어 있거나 올바르지 않습니다.")
            payload = bytes(file_bytes)

            # 2026-11-04 hoyeon.han: 검증이 끝나기 전에는 기존 저장본에 접근하지 않는다.
            parsed = es.parse_ecount_xlsx(
                io.BytesIO(payload), expected_doc_type=doc_type
            )
            es.to_order_settlement_df(parsed["df"])
            display_name = str(original_name or "이카운트.xlsx").replace("\\", "/").split("/")[-1]
            metadata: dict[str, Any] = {
                "doc_type": doc_type,
                "original_name": display_name or "이카운트.xlsx",
                "uploaded_at": datetime.now(self._KST).isoformat(timespec="seconds"),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "period_start": parsed["start_date"].isoformat(),
                "period_end": parsed["end_date"].isoformat(),
                "row_count": int(len(parsed["df"])),
                "company": str(parsed.get("company") or ""),
                "sheet_name": str(parsed.get("sheet_name") or ""),
                "qty_total": float(parsed["df"]["수량"].sum()),
                "amount_total": float(parsed["df"]["합계"].sum()),
                "blank_amount_rows": int(parsed.get("blank_amount_rows", 0)),
            }
            if uploaded_by is not None:
                metadata["uploaded_by"] = str(uploaded_by)

            path.parent.mkdir(parents=True, exist_ok=True)
            # 2026-11-04 hoyeon.han: 같은 파일시스템에서 완성된 묶음 하나만 교체한다.
            with tempfile.NamedTemporaryFile(
                mode="w+b", prefix=".current-", suffix=".tmp", dir=path.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                with zipfile.ZipFile(temporary_file, "w", compression=zipfile.ZIP_STORED) as bundle:
                    bundle.writestr(self._ORIGINAL_MEMBER, payload)
                    bundle.writestr(
                        self._METADATA_MEMBER,
                        json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                    )
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
            self.logger.info("이카운트 %s 최신 원본 저장 완료 (%s bytes)", doc_type, len(payload))
            return {**metadata, "file_bytes": payload}
        except Exception as exc:
            self.logger.error("이카운트 %s 원본 저장 실패", doc_type, exc_info=True)
            if isinstance(exc, OSError):
                raise OSError(
                    "이카운트 파일을 서버에 저장하지 못했습니다. 저장 공간과 경로 권한을 확인해 주세요."
                ) from exc
            raise
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    self.logger.warning("이카운트 임시 파일 정리 실패", exc_info=True)
