# 롤백 검증 결과

2026-10-15 hoyeon.han

전체 결과: True, 검증 55개. 원본 자료 불변: True. 정리: True.

| 검증 | 결과 | 증거 범위 |
|---|---|---|
| initial_real_https_requires_auth | True | actual |
| plan_rejects_uncheckpointed_current_wal_without_mutation | True | actual |
| capture_includes_committed_wal_data | True | actual |
| offline_image_archive_exists_and_manifest_checksum_matches | True | actual |
| release_secret_files_owner_only | True | actual |
| public_release_metadata_contains_no_plaintext_secrets | True | actual |
| default_rollback_is_readonly_plan | True | actual |
| real_shell_wrapper_keeps_production_port_checks_and_exposes_explicit_apply | True | actual |
| production_default_rejects_fixture_high_published_ports | True | actual |
| manifest_project_tampering_rejected_before_mutation | True | actual |
| offline_archive_corruption_rejected_before_mutation | True | actual |
| release_path_outside_allowed_directory_rejected | True | actual |
| unsafe_environment_key_rejected_before_mutation | True | actual |
| current_database_mount_path_mismatch_rejected_before_mutation | True | actual |
| secure_restore_completed_with_public_auth_guards | True | actual |
| secure_restore_keeps_latest_password_role_grants_and_mfa | True | actual |
| secure_restore_clears_sessions_pending_enrollment_and_downloads | True | actual |
| secure_restore_keeps_latest_customer_and_order_files | True | actual |
| tag_movement_does_not_change_restored_image_ids | True | actual |
| actual_cpu_memory_and_bind_mounts_preserved | True | actual |
| actual_readonly_root_and_tmpfs_preserved | True | actual |
| shell_export_contamination_cannot_replace_saved_dotenv_auth_keys | True | actual |
| revoked_pre_rollback_session_cookie_is_denied | True | actual |
| actual_https_mfa_login_with_preserved_encrypted_secret_succeeds | True | actual |
| nginx_failure_keeps_actual_https503_and_current_state_backup | True | actual Docker/HTTPS with one injected failing operation |
| nginx_failure_can_retry_from_partially_stopped_services | True | actual |
| image_failure_keeps_actual_https503_and_current_state_backup | True | actual Docker/HTTPS with one injected failing operation |
| image_failure_can_retry_from_partially_stopped_services | True | actual |
| start_failure_keeps_actual_https503_and_current_state_backup | True | actual Docker/HTTPS with one injected failing operation |
| start_failure_can_retry_from_partially_stopped_services | True | actual |
| health_failure_keeps_actual_https503_and_current_state_backup | True | actual Docker/HTTPS with one injected failing operation |
| health_failure_can_retry_from_partially_stopped_services | True | actual |
| interrupt_failure_keeps_actual_https503_and_current_state_backup | True | actual Docker/HTTPS with one injected failing operation |
| interrupt_failure_can_retry_from_partially_stopped_services | True | actual |
| missing_service_recovery_metadata_contains_no_plaintext_secrets | True | actual |
| missing_auth_service_after_failed_deployment_can_restore | True | actual |
| legacy_snapshot_contains_unmodified_original_user_db | True | actual |
| legacy_missing_required_flags_denied_0_False | True | actual |
| legacy_missing_required_flags_denied_1_False | True | actual |
| legacy_missing_required_flags_denied_1_True | True | actual |
| explicit_legacy_restore_still_defaults_readonly | True | actual |
| legacy_restore_keeps_real_https503 | True | actual |
| legacy_restore_does_not_revive_changed_deleted_stopped_or_reassigned_accounts | True | actual |
| legacy_capture_user_db_stays_unchanged | True | actual |
| unchanged_legacy_bcrypt_password_still_matches | True | actual |
| actual_old_image_auth_qa_stable_success | True | actual |
| actual_old_image_auth_qa_changed_denied | True | actual |
| legacy_password_recovery_denies_qa_stopped | True | actual |
| legacy_password_recovery_denies_qa_deleted | True | actual |
| legacy_password_recovery_denies_qa_renamed | True | actual |
| legacy_password_recovery_defaults_to_plan | True | actual |
| legacy_password_apply_requires_hidden_input_tty | True | actual |
| actual_tty_legacy_password_reset_succeeds_without_password_echo | True | actual |
| actual_old_image_auth_qa_changed_success | True | actual |
| legacy_password_reset_never_reopens_public_https | True | actual |
