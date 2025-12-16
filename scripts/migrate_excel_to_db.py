#!/usr/bin/env python3
# migrate_excel_to_db.py
# 2025-12-16 hoyeon.han
# 거래처마스터.xlsx → SQLite DB 마이그레이션 스크립트

import sys
import os
import logging
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# customer_master_db를 직접 import (Src 패키지를 거치지 않음)
# 이렇게 하면 __init__.py의 다른 의존성을 피할 수 있음
import importlib.util
spec = importlib.util.spec_from_file_location(
    "customer_master_db",
    os.path.join(project_root, "Src", "customer_master_db.py")
)
customer_master_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(customer_master_db)
CustomerMasterDB = customer_master_db.CustomerMasterDB


def migrate_excel_to_db():
    """거래처마스터 Excel 파일을 SQLite DB로 마이그레이션"""

    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)

    # 파일 경로 설정
    excel_path = "Src/거래처마스터.xlsx"
    db_path = "database/customer_master.db"

    # Excel 파일 존재 확인
    if not Path(excel_path).exists():
        logger.error(f"Excel 파일을 찾을 수 없습니다: {excel_path}")
        return False

    logger.info("=" * 70)
    logger.info("거래처마스터 Excel → DB 마이그레이션 시작")
    logger.info("=" * 70)

    # DB 인스턴스 생성
    logger.info(f"DB 초기화: {db_path}")
    db = CustomerMasterDB(db_path)

    # 기존 데이터 백업 (DB가 이미 존재하는 경우)
    if Path(db_path).exists():
        logger.info("기존 DB 백업 중...")
        backup_file = db.backup_db()
        logger.info(f"백업 완료: {backup_file}")

    # Excel에서 데이터 가져오기
    logger.info(f"Excel 파일 읽기: {excel_path}")
    success, message = db.import_from_excel(excel_path, sheet_name="거래처마스터")

    if success:
        logger.info("✅ 마이그레이션 성공!")
        logger.info(message)

        # 통계 출력
        logger.info("\n" + "=" * 70)
        logger.info("DB 통계 정보")
        logger.info("=" * 70)

        stats = db.get_stats()
        logger.info(f"총 거래처 수: {stats['total_customers']}개")
        logger.info(f"DB 파일 경로: {stats['db_path']}")
        logger.info(f"최근 등록일: {stats['latest_created']}")

        # 샘플 데이터 출력
        logger.info("\n" + "=" * 70)
        logger.info("샘플 데이터 (처음 5개)")
        logger.info("=" * 70)

        df_all = db.get_all_customers()
        print(df_all.head(5).to_string(index=False))

        logger.info("\n" + "=" * 70)
        logger.info("마이그레이션 완료!")
        logger.info("=" * 70)

        return True

    else:
        logger.error("❌ 마이그레이션 실패!")
        logger.error(message)
        return False


if __name__ == "__main__":
    success = migrate_excel_to_db()
    sys.exit(0 if success else 1)
