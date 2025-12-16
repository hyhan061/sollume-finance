# customer_master_db.py
# 2025-12-16 hoyeon.han
# 거래처 마스터 데이터베이스 관리 클래스

import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path
import shutil
from typing import Tuple, Optional, List
import logging


class CustomerMasterDB:
    """거래처 마스터 데이터베이스 관리 클래스

    기능:
    - CRUD 작업 (Create, Read, Update, Delete)
    - Excel ↔ DB 마이그레이션
    - 데이터베이스 백업/복원
    - 검색 기능
    """

    def __init__(self, db_path: str = "database/customer_master.db"):
        """초기화

        Args:
            db_path: SQLite DB 파일 경로
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

        # DB 디렉토리 생성
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # 테이블 초기화
        self._init_db()

    def _init_db(self):
        """데이터베이스 초기화 및 테이블 생성"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # customers 테이블 생성
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS customers (
                        사업자번호 VARCHAR(12) PRIMARY KEY,
                        발주내역_거래처명 TEXT NOT NULL,
                        경리나라_거래처명 TEXT NOT NULL,
                        대표자명 TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # 인덱스 생성 (빠른 검색)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_customers_order_name
                    ON customers(발주내역_거래처명)
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_customers_accounting_name
                    ON customers(경리나라_거래처명)
                """)

                conn.commit()
                self.logger.info(f"Database initialized: {self.db_path}")

        except Exception as e:
            self.logger.error(f"Database initialization failed: {e}")
            raise

    # ==========================================================================
    # CRUD 작업
    # ==========================================================================

    def add_customer(
        self,
        business_number: str,
        order_name: str,
        accounting_name: str,
        representative: Optional[str] = None
    ) -> Tuple[bool, str]:
        """거래처 추가

        Args:
            business_number: 사업자번호 (PK)
            order_name: 발주내역 거래처명
            accounting_name: 경리나라 거래처명
            representative: 대표자명 (선택)

        Returns:
            (성공 여부, 메시지)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO customers
                    (사업자번호, 발주내역_거래처명, 경리나라_거래처명, 대표자명)
                    VALUES (?, ?, ?, ?)
                """, (business_number, order_name, accounting_name, representative))

                conn.commit()

                self.logger.info(f"Customer added: {business_number} - {order_name}")
                return True, f"거래처가 등록되었습니다: {order_name}"

        except sqlite3.IntegrityError:
            self.logger.warning(f"Duplicate business number: {business_number}")
            return False, f"이미 존재하는 사업자번호입니다: {business_number}"

        except Exception as e:
            self.logger.error(f"Failed to add customer: {e}")
            return False, f"거래처 등록 실패: {str(e)}"

    def get_customer(self, business_number: str) -> Optional[dict]:
        """사업자번호로 거래처 조회

        Args:
            business_number: 사업자번호

        Returns:
            거래처 정보 딕셔너리 또는 None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # Row 객체로 반환
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT * FROM customers WHERE 사업자번호 = ?
                """, (business_number,))

                row = cursor.fetchone()

                if row:
                    return dict(row)
                else:
                    return None

        except Exception as e:
            self.logger.error(f"Failed to get customer: {e}")
            return None

    def update_customer(
        self,
        business_number: str,
        order_name: str,
        accounting_name: str,
        representative: Optional[str] = None
    ) -> Tuple[bool, str]:
        """거래처 정보 수정

        Args:
            business_number: 사업자번호 (PK, 변경 불가)
            order_name: 발주내역 거래처명
            accounting_name: 경리나라 거래처명
            representative: 대표자명 (선택)

        Returns:
            (성공 여부, 메시지)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE customers
                    SET 발주내역_거래처명 = ?,
                        경리나라_거래처명 = ?,
                        대표자명 = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE 사업자번호 = ?
                """, (order_name, accounting_name, representative, business_number))

                if cursor.rowcount == 0:
                    return False, f"거래처를 찾을 수 없습니다: {business_number}"

                conn.commit()

                self.logger.info(f"Customer updated: {business_number}")
                return True, f"거래처 정보가 수정되었습니다: {order_name}"

        except Exception as e:
            self.logger.error(f"Failed to update customer: {e}")
            return False, f"거래처 수정 실패: {str(e)}"

    def delete_customer(self, business_number: str) -> Tuple[bool, str]:
        """거래처 삭제

        Args:
            business_number: 사업자번호

        Returns:
            (성공 여부, 메시지)
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 삭제 전 정보 조회 (로그용)
                customer = self.get_customer(business_number)

                cursor.execute("""
                    DELETE FROM customers WHERE 사업자번호 = ?
                """, (business_number,))

                if cursor.rowcount == 0:
                    return False, f"거래처를 찾을 수 없습니다: {business_number}"

                conn.commit()

                if customer:
                    self.logger.info(
                        f"Customer deleted: {business_number} - "
                        f"{customer.get('발주내역_거래처명')}"
                    )

                return True, "거래처가 삭제되었습니다"

        except Exception as e:
            self.logger.error(f"Failed to delete customer: {e}")
            return False, f"거래처 삭제 실패: {str(e)}"

    # ==========================================================================
    # 검색 기능
    # ==========================================================================

    def search_customers(self, query: str) -> pd.DataFrame:
        """거래처 검색 (거래처명 또는 사업자번호)

        Args:
            query: 검색어 (거래처명 일부 또는 사업자번호)

        Returns:
            검색 결과 DataFrame
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                # LIKE 검색 (부분 일치)
                sql = """
                    SELECT
                        사업자번호,
                        발주내역_거래처명,
                        경리나라_거래처명,
                        대표자명,
                        created_at,
                        updated_at
                    FROM customers
                    WHERE
                        사업자번호 LIKE ? OR
                        발주내역_거래처명 LIKE ? OR
                        경리나라_거래처명 LIKE ?
                    ORDER BY 발주내역_거래처명
                """

                search_pattern = f"%{query}%"
                df = pd.read_sql_query(
                    sql,
                    conn,
                    params=(search_pattern, search_pattern, search_pattern)
                )

                self.logger.info(f"Search: '{query}' -> {len(df)} results")
                return df

        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            return pd.DataFrame()

    def get_all_customers(self) -> pd.DataFrame:
        """모든 거래처 조회

        Returns:
            전체 거래처 DataFrame
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                sql = """
                    SELECT
                        사업자번호,
                        발주내역_거래처명,
                        경리나라_거래처명,
                        대표자명,
                        created_at,
                        updated_at
                    FROM customers
                    ORDER BY 발주내역_거래처명
                """

                df = pd.read_sql_query(sql, conn)
                self.logger.info(f"Retrieved all customers: {len(df)} rows")
                return df

        except Exception as e:
            self.logger.error(f"Failed to get all customers: {e}")
            return pd.DataFrame()

    def get_business_number(self, order_name: str) -> Optional[str]:
        """발주내역 거래처명으로 사업자번호 조회

        Args:
            order_name: 발주내역 거래처명

        Returns:
            사업자번호 또는 None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT 사업자번호 FROM customers
                    WHERE 발주내역_거래처명 = ?
                """, (order_name,))

                row = cursor.fetchone()

                if row:
                    return row[0]
                else:
                    return None

        except Exception as e:
            self.logger.error(f"Failed to get business number: {e}")
            return None

    # ==========================================================================
    # Excel ↔ DB 마이그레이션
    # ==========================================================================

    def import_from_excel(
        self,
        excel_path: str,
        sheet_name: str = "거래처마스터"
    ) -> Tuple[bool, str]:
        """Excel 파일에서 DB로 데이터 가져오기

        Args:
            excel_path: Excel 파일 경로
            sheet_name: 시트 이름

        Returns:
            (성공 여부, 메시지)
        """
        try:
            # Excel 읽기
            df = pd.read_excel(excel_path, sheet_name=sheet_name)

            # 컬럼명 확인
            required_columns = ['거래처명_경리나라', '거래처명_솔루미랩', '사업자번호']
            missing_columns = [col for col in required_columns if col not in df.columns]

            if missing_columns:
                return False, f"필수 컬럼이 없습니다: {missing_columns}"

            # 컬럼명 변경
            df = df.rename(columns={
                '거래처명_솔루미랩': '발주내역_거래처명',
                '거래처명_경리나라': '경리나라_거래처명'
            })

            # NaN 처리
            df['발주내역_거래처명'] = df['발주내역_거래처명'].fillna(df['경리나라_거래처명'])
            df['대표자명'] = df['대표자명'].fillna('')

            # 사업자번호가 없는 행 제외
            df = df[df['사업자번호'].notna()]

            # DB에 저장
            success_count = 0
            duplicate_count = 0
            error_count = 0

            for _, row in df.iterrows():
                success, message = self.add_customer(
                    business_number=str(row['사업자번호']),
                    order_name=str(row['발주내역_거래처명']),
                    accounting_name=str(row['경리나라_거래처명']),
                    representative=str(row.get('대표자명', '')) if pd.notna(row.get('대표자명')) else None
                )

                if success:
                    success_count += 1
                elif "이미 존재" in message:
                    duplicate_count += 1
                else:
                    error_count += 1

            result_message = (
                f"Excel 가져오기 완료\n"
                f"- 성공: {success_count}건\n"
                f"- 중복: {duplicate_count}건\n"
                f"- 실패: {error_count}건"
            )

            self.logger.info(result_message)
            return True, result_message

        except Exception as e:
            self.logger.error(f"Failed to import from Excel: {e}")
            return False, f"Excel 가져오기 실패: {str(e)}"

    def export_to_excel(self, excel_path: str) -> Tuple[bool, str]:
        """DB에서 Excel 파일로 데이터 내보내기

        Args:
            excel_path: 저장할 Excel 파일 경로

        Returns:
            (성공 여부, 메시지)
        """
        try:
            # 모든 거래처 조회
            df = self.get_all_customers()

            if len(df) == 0:
                return False, "내보낼 데이터가 없습니다"

            # 컬럼명 변경 (원본 형식으로)
            df = df.rename(columns={
                '발주내역_거래처명': '거래처명_솔루미랩',
                '경리나라_거래처명': '거래처명_경리나라'
            })

            # 필요한 컬럼만 선택
            df_export = df[[
                '거래처명_경리나라',
                '거래처명_솔루미랩',
                '사업자번호',
                '대표자명'
            ]]

            # Excel 저장
            df_export.to_excel(excel_path, sheet_name='거래처마스터', index=False)

            self.logger.info(f"Exported {len(df_export)} customers to {excel_path}")
            return True, f"Excel 파일로 내보내기 완료: {len(df_export)}건"

        except Exception as e:
            self.logger.error(f"Failed to export to Excel: {e}")
            return False, f"Excel 내보내기 실패: {str(e)}"

    # ==========================================================================
    # 백업 및 복원
    # ==========================================================================

    def backup_db(self, backup_dir: str = "database/backups") -> str:
        """데이터베이스 백업

        Args:
            backup_dir: 백업 디렉토리

        Returns:
            백업 파일 경로
        """
        try:
            # 백업 디렉토리 생성
            backup_path = Path(backup_dir)
            backup_path.mkdir(parents=True, exist_ok=True)

            # 백업 파일명 (날짜_시간 포함)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_path / f"customer_master_backup_{timestamp}.db"

            # 파일 복사
            shutil.copy2(self.db_path, backup_file)

            self.logger.info(f"Database backed up to: {backup_file}")
            return str(backup_file)

        except Exception as e:
            self.logger.error(f"Backup failed: {e}")
            raise

    def restore_db(self, backup_file: str) -> Tuple[bool, str]:
        """데이터베이스 복원

        Args:
            backup_file: 백업 파일 경로

        Returns:
            (성공 여부, 메시지)
        """
        try:
            if not Path(backup_file).exists():
                return False, f"백업 파일이 없습니다: {backup_file}"

            # 현재 DB 백업 (안전)
            current_backup = self.backup_db()

            # 백업 파일로 복원
            shutil.copy2(backup_file, self.db_path)

            self.logger.info(
                f"Database restored from: {backup_file}\n"
                f"Previous version saved to: {current_backup}"
            )

            return True, f"데이터베이스가 복원되었습니다\n(이전 버전: {current_backup})"

        except Exception as e:
            self.logger.error(f"Restore failed: {e}")
            return False, f"복원 실패: {str(e)}"

    # ==========================================================================
    # 통계 및 유틸리티
    # ==========================================================================

    def get_stats(self) -> dict:
        """데이터베이스 통계 정보

        Returns:
            통계 정보 딕셔너리
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 총 거래처 수
                cursor.execute("SELECT COUNT(*) FROM customers")
                total_count = cursor.fetchone()[0]

                # 최근 등록일
                cursor.execute("SELECT MAX(created_at) FROM customers")
                latest_created = cursor.fetchone()[0]

                # 최근 수정일
                cursor.execute("SELECT MAX(updated_at) FROM customers")
                latest_updated = cursor.fetchone()[0]

                return {
                    'total_customers': total_count,
                    'latest_created': latest_created,
                    'latest_updated': latest_updated,
                    'db_path': self.db_path
                }

        except Exception as e:
            self.logger.error(f"Failed to get stats: {e}")
            return {}


# =============================================================================
# 테스트 코드 (이 파일을 직접 실행할 때만 동작)
# =============================================================================

if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 테스트 DB 생성
    db = CustomerMasterDB("database/test_customer_master.db")

    # 테스트 데이터 추가
    print("\n=== 거래처 추가 테스트 ===")
    success, msg = db.add_customer(
        business_number="123-45-67890",
        order_name="테스트거래처",
        accounting_name="(주)테스트",
        representative="홍길동"
    )
    print(f"결과: {msg}")

    # 검색 테스트
    print("\n=== 검색 테스트 ===")
    results = db.search_customers("테스트")
    print(f"검색 결과: {len(results)}건")
    print(results)

    # 통계 조회
    print("\n=== 통계 조회 ===")
    stats = db.get_stats()
    for key, value in stats.items():
        print(f"{key}: {value}")
