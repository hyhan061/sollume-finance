# Docker 사용자 CLI 검증 결과

2026-10-14 hoyeon.han

전체 결과: **통과**, 35항목.

원본 9파일 불변: True. 최종 소스 해시 일치: True. 임시 자원 정리: True.

실제 운영 Compose와 원본 DB는 실행·마운트하지 않았으며 network_mode:none, 포트 없음, 합성 fixture만 사용했습니다.

MFA는 컨테이너 안의 실제 운영 모드 HTTP 핸들러로 확인했으며 외부 TLS/Nginx 검증은 별도 결과를 참고합니다.

| 검증 | 결과 |
|---|---|
| host_verifier_runs_inside_python_venv | 통과 |
| original_nine_files_match_preserved_baseline | 통과 |
| isolated_compose_manifest_parses | 통과 |
| compose_network_none_no_ports_only_temporary_fixture_mount | 통과 |
| docker_entrypoint_python_uses_opt_venv | 통과 |
| docker_python_pip_streamlit_gunicorn_paths_share_venv | 통과 |
| built_image_cli_auth_source_matches_current_repository | 통과 |
| compose_entrypoint_python_exit_zero | 통과 |
| compose_entrypoint_python_uses_same_venv | 통과 |
| operational_cli_module_imports_do_not_create_db | 통과 |
| active_deployment_preflight_payload_extracted_unambiguously | 통과 |
| actual_deployment_preflight_in_venv_passes_without_creating_db | 통과 |
| actual_deployment_preflight_preserves_existing_db_exact_bytes | 통과 |
| actual_deployment_preflight_rejects_system_python_before_imports | 통과 |
| documented_compose_manage_users_list_exit_zero | 통과 |
| list_shows_three_legacy_accounts_roles_status_without_sensitive_values | 통과 |
| first_cli_migration_preserves_legacy_ids_hashes_history_permissions | 통과 |
| existing_admin_init_repeated_exit_zero_no_duplicate_accounts | 통과 |
| init_repeated_preserves_hashes_ids_history_roles_and_grants | 통과 |
| enrollment_confirmation_no_preserves_existing_account | 통과 |
| documented_enrollment_confirmation_yes_exit_zero | 통과 |
| cli_enrollment_code_stored_as_hash_not_plaintext | 통과 |
| enrollment_preserves_legacy_passwords_history_ids_and_permissions | 통과 |
| missing_encryption_key_cli_fails_closed_without_creating_db | 통과 |
| missing_encryption_key_init_fails_closed_without_creating_db | 통과 |
| non_tty_new_admin_rejected_without_reading_or_storing_password | 통과 |
| legacy-users.db_actual_http_mfa_probe_exit_zero | 통과 |
| legacy-users.db_issued_cli_code_completes_actual_http_mfa_registration | 통과 |
| after_intended_mfa_change_legacy_staff_and_inactive_accounts_unchanged | 통과 |
| list_after_mfa_reports_enrollment_completed | 통과 |
| actual_tty_new_admin_creation_exit_zero | 통과 |
| actual_tty_getpass_password_not_echoed | 통과 |
| actual_tty_created_only_one_admin_with_mandatory_mfa_and_password_change | 통과 |
| tty-admin.db_actual_http_mfa_probe_exit_zero | 통과 |
| tty-admin.db_issued_cli_code_completes_actual_http_mfa_registration | 통과 |
