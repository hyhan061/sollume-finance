# 수동 백업 검증

2026-10-19 hoyeon.han

결과: True, 검증 32개, 원본 불변: True, 정리: True.

| 검증 | 결과 | 증거 |
|---|---|---|
| actual_gnu_tar_binary_used | True | actual Docker/GNU tar/SQLite |
| actual_gnu_root_dot_and_dot_slash_prefix_present | True | actual Docker/GNU tar/SQLite |
| actual_nonselected_virtualenv_symlink_and_past_backups_present | True | actual Docker/GNU tar/SQLite |
| actual_zero_length_wal_entry_present | True | actual Docker/GNU tar/SQLite |
| actual_manual_plan_validated_without_docker_mutation | True | actual Docker/GNU tar/SQLite |
| actual_two_distinct_original_image_ids_preserved | True | actual Docker/GNU tar/SQLite |
| actual_manual_prepare_idempotent | True | actual Docker/GNU tar/SQLite |
| actual_inspect_cmd_entrypoint_and_image_generate_restoration_compose | True | actual Docker/GNU tar/SQLite |
| actual_source_three_archives_unchanged_after_prepare | True | actual Docker/GNU tar/SQLite |
| manual_rollback_defaults_readonly_and_never_public_resume | True | actual Docker/GNU tar/SQLite |
| legacy_apply_requires_both_explicit_flags_0False | True | actual Docker/GNU tar/SQLite |
| legacy_apply_requires_both_explicit_flags_1False | True | actual Docker/GNU tar/SQLite |
| legacy_apply_requires_both_explicit_flags_1True | True | actual Docker/GNU tar/SQLite |
| unlisted_actual_legacy_site_rejected_before_any_source_or_runtime_mutation | True | actual Docker/GNU tar/SQLite |
| injected_image_failure_preserves_current_backup_and_all_http_https_ingress503 | True | actual Docker/SQLite/HTTP/HTTPS; image load failure injected |
| failure_stops_only_accounting_containers_and_preserves_other_canaries | True | actual Docker/GNU tar/SQLite |
| failure_keeps_original_manual_archives_and_current_business_files | True | actual Docker/GNU tar/SQLite |
| actual_manual_restore_from_partially_removed_state_completes_private | True | actual Docker/GNU tar/SQLite |
| actual_inspect_config_resources_logs_bind_rw_and_loopback_ports_match_original | True | actual Docker/GNU tar/SQLite |
| current_rotated_api_key_overrides_archived_key | True | actual Docker/GNU tar/SQLite |
| actual_legacy_service_health_checks_pass | True | actual Docker/GNU tar/SQLite |
| latest_added_stopped_deleted_password_changed_accounts_and_demotion_preserved | True | actual Docker/GNU tar/SQLite |
| latest_full_security_state_and_added_account_are_preserved_in_private_rescue | True | actual Docker/GNU tar/SQLite |
| current_business_files_original_archives_and_other_canaries_preserved | True | actual Docker/GNU tar/SQLite |
| actual_old_image_private_login_accepts_unchanged_user | True | actual Docker/GNU tar/SQLite |
| actual_old_image_private_login_denies_discarded_password | True | actual Docker/GNU tar/SQLite |
| manual_password_cannot_revive_qa_stopped | True | actual Docker/GNU tar/SQLite |
| manual_password_cannot_revive_qa_deleted | True | actual Docker/GNU tar/SQLite |
| manual_password_changed_admin_and_added_account_default_to_plan | True | actual Docker/GNU tar/SQLite |
| actual_manual_password_tty_reset_succeeds_without_echo | True | actual Docker/GNU tar/SQLite |
| actual_changed_admin_authenticates_privately_after_tty_reset | True | actual Docker/GNU tar/SQLite |
| manual_password_and_private_login_never_reopen_any_ingress | True | actual Docker/GNU tar/SQLite |

단위·shell·Compose 검사: 37 passed, 1.3초.

별도 부모 검증: Python 3.12.13 stdlib-only manual-plan 성공, 최종 helper 1808955… 기준.

원본 운영 수동백업은 제공되지 않았으며 합성 자료만 사용했습니다. Nginx 명령은 로컬 fixture 어댑터로 연결했고 실제 운영 배포는 하지 않았습니다.
