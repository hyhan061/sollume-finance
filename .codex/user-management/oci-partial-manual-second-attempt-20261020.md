# 수동 백업 검증

hoyeon.han · 검증 시각(UTC): 2026-10-20T02:23:34.191129+00:00

이미지 저장 형식: partial-oci

결과: False, 검증 12개, 원본 불변: True, 정리: True.

| 검증 | 결과 | 증거 |
|---|---|---|
| actual_partial_oci_roots_match_inspected_container_ids | True | actual Docker/GNU tar/SQLite |
| manual_initial_acme_http200_body_matches_and_other_sites_preserved | True | actual Docker/GNU tar/SQLite |
| actual_gnu_tar_binary_used | True | actual Docker/GNU tar/SQLite |
| actual_gnu_root_dot_and_dot_slash_prefix_present | True | actual Docker/GNU tar/SQLite |
| actual_nonselected_virtualenv_symlink_and_past_backups_present | True | actual Docker/GNU tar/SQLite |
| actual_zero_length_wal_entry_present | True | actual Docker/GNU tar/SQLite |
| actual_manual_plan_validated_without_docker_mutation | True | actual Docker/GNU tar/SQLite |
| actual_two_distinct_original_image_ids_preserved | True | actual Docker/GNU tar/SQLite |
| actual_manual_prepare_idempotent | True | actual Docker/GNU tar/SQLite |
| actual_inspect_cmd_entrypoint_and_image_generate_restoration_compose | True | actual Docker/GNU tar/SQLite |
| actual_source_three_archives_unchanged_after_prepare | True | actual Docker/GNU tar/SQLite |
| manual_secure_acme200_root401_download401_and_other_sites_preserved | False | actual Docker/GNU tar/SQLite |
