use sasoo_backend::error::{Result, SasooError};
use sasoo_backend::{
    storage::credentials::*,
    types::{KeyEpoch, ProviderId},
};
use secrecy::{ExposeSecret, SecretString};
use std::{
    collections::{BTreeMap, HashMap},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
};

struct MemoryKeyStore {
    state: Mutex<(Option<SecretString>, Option<KeyStoreFailure>, usize)>,
    reads: AtomicUsize,
    write_attempts: AtomicUsize,
}
impl MemoryKeyStore {
    fn new(key: Option<SecretString>) -> Self {
        Self {
            state: Mutex::new((key, None, 0)),
            reads: AtomicUsize::new(0),
            write_attempts: AtomicUsize::new(0),
        }
    }
    fn writes(&self) -> usize {
        self.state.lock().unwrap().2
    }
    fn reads(&self) -> usize {
        self.reads.load(Ordering::SeqCst)
    }
    fn write_attempts(&self) -> usize {
        self.write_attempts.load(Ordering::SeqCst)
    }
    fn set_failure(&self, failure: Option<KeyStoreFailure>) {
        self.state.lock().unwrap().1 = failure;
    }
}
impl KeyStore for MemoryKeyStore {
    fn get_key(&self) -> std::result::Result<Option<SecretString>, KeyStoreFailure> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        let state = self.state.lock().unwrap();
        if let Some(failure) = state.1 {
            return Err(failure);
        }
        Ok(state
            .0
            .as_ref()
            .map(|key| SecretString::from(key.expose_secret().to_owned())))
    }
    fn set_key(&self, key: &SecretString) -> std::result::Result<(), KeyStoreFailure> {
        self.write_attempts.fetch_add(1, Ordering::SeqCst);
        let mut state = self.state.lock().unwrap();
        if let Some(failure) = state.1 {
            return Err(failure);
        }
        state.0 = Some(SecretString::from(key.expose_secret().to_owned()));
        state.2 += 1;
        Ok(())
    }
}
#[derive(Default)]
struct MemoryCredentialRepository {
    records: Mutex<HashMap<ProviderId, SecretRecord>>,
    fail_writes: AtomicBool,
}
impl MemoryCredentialRepository {
    fn seed(&self, provider: ProviderId, epoch: KeyEpoch, stored: Option<String>) {
        self.records
            .lock()
            .unwrap()
            .insert(provider, SecretRecord { epoch, stored });
    }
    fn set_fail_writes(&self, value: bool) {
        self.fail_writes.store(value, Ordering::SeqCst);
    }
}
impl CredentialRepository for MemoryCredentialRepository {
    fn authorize_write(&self) -> Result<()> {
        Ok(())
    }

    fn read(&self, provider: ProviderId) -> Result<SecretRecord> {
        Ok(self
            .records
            .lock()
            .unwrap()
            .get(&provider)
            .cloned()
            .unwrap_or(SecretRecord {
                epoch: KeyEpoch(0),
                stored: None,
            }))
    }
    fn commit_batch(
        &self,
        secrets: Vec<EncryptedSecretUpdate>,
        _: BTreeMap<String, String>,
    ) -> Result<Vec<(ProviderId, KeyEpoch)>> {
        if self.fail_writes.load(Ordering::SeqCst) {
            return Err(SasooError::StorageBusy(
                "Injected persistence failure".into(),
            ));
        }
        let mut records = self.records.lock().unwrap();
        for secret in &secrets {
            if records
                .get(&secret.provider)
                .map(|record| record.epoch)
                .unwrap_or(KeyEpoch(0))
                != secret.expected_epoch
            {
                return Err(SasooError::Conflict("epoch mismatch".into()));
            }
        }
        let mut epochs = Vec::new();
        for secret in secrets {
            let epoch = KeyEpoch(secret.expected_epoch.0 + 1);
            records.insert(
                secret.provider,
                SecretRecord {
                    epoch,
                    stored: secret.ciphertext,
                },
            );
            epochs.push((secret.provider, epoch));
        }
        Ok(epochs)
    }
}

fn manager(
    key: Option<&str>,
) -> (
    CredentialManager,
    Arc<MemoryKeyStore>,
    Arc<MemoryCredentialRepository>,
) {
    let keys = Arc::new(MemoryKeyStore::new(
        key.map(|value| SecretString::from(value.to_owned())),
    ));
    let records = Arc::new(MemoryCredentialRepository::default());
    (
        CredentialManager::new(keys.clone(), records.clone(), None),
        keys,
        records,
    )
}

#[test]
fn python_fernet_ciphertext_and_legacy_plaintext_are_readable_without_writes() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../contract-fixtures/rust-backend-v2/credentials.json"
    ))
    .unwrap();
    let case = &fixture["cases"][0];
    let (manager, keys, records) = manager(case["key"].as_str());
    records.seed(
        ProviderId::OpenAi,
        KeyEpoch(4),
        Some(case["stored"].as_str().unwrap().to_owned()),
    );
    assert_eq!(
        manager
            .read_secret(ProviderId::OpenAi)
            .unwrap()
            .unwrap()
            .expose_secret(),
        case["plaintext"].as_str().unwrap()
    );
    records.seed(
        ProviderId::Gemini,
        KeyEpoch(2),
        Some("legacy-plain-text".to_owned()),
    );
    assert_eq!(
        manager
            .read_secret(ProviderId::Gemini)
            .unwrap()
            .unwrap()
            .expose_secret(),
        "legacy-plain-text"
    );
    assert_eq!(keys.writes(), 0);
    assert_eq!(records.read(ProviderId::Gemini).unwrap().epoch, KeyEpoch(2));
}

#[test]
fn locked_unavailable_invalid_and_missing_are_not_interchangeable() {
    for failure in [
        KeyStoreFailure::Locked,
        KeyStoreFailure::Unavailable,
        KeyStoreFailure::Invalid,
    ] {
        let (manager, keys, records) = manager(None);
        records.seed(
            ProviderId::OpenAi,
            KeyEpoch(7),
            Some("enc:v1:original-ciphertext".to_owned()),
        );
        keys.set_failure(Some(failure));
        assert!(manager.read_secret(ProviderId::OpenAi).is_err());
        assert!(
            manager
                .apply_secret_update(
                    SecretUpdate::Set {
                        provider: ProviderId::OpenAi,
                        value: SecretString::from("new-secret".to_owned())
                    },
                    KeyEpoch(7)
                )
                .is_err()
        );
        assert_eq!(keys.writes(), 0);
        assert_eq!(
            records.read(ProviderId::OpenAi).unwrap().stored.as_deref(),
            Some("enc:v1:original-ciphertext")
        );
        assert_eq!(records.read(ProviderId::OpenAi).unwrap().epoch, KeyEpoch(7));
    }
    let (manager, keys, records) = manager(None);
    assert!(manager.read_secret(ProviderId::OpenAi).unwrap().is_none());
    records.seed(
        ProviderId::OpenAi,
        KeyEpoch(1),
        Some("enc:v1:unknown-key".to_owned()),
    );
    assert!(manager.read_secret(ProviderId::OpenAi).is_err());
    assert_eq!(keys.writes(), 0);
}

#[test]
fn explicit_update_uses_epoch_cas_and_clear_does_not_touch_the_key() {
    let (manager, keys, records) = manager(None);
    assert_eq!(
        manager
            .apply_secret_update(
                SecretUpdate::Set {
                    provider: ProviderId::OpenAi,
                    value: SecretString::from("new-secret".to_owned())
                },
                KeyEpoch(0)
            )
            .unwrap(),
        KeyEpoch(1)
    );
    let saved = records.read(ProviderId::OpenAi).unwrap();
    assert!(saved.stored.unwrap().starts_with(ENCRYPTED_PREFIX));
    assert_eq!(
        manager
            .read_secret(ProviderId::OpenAi)
            .unwrap()
            .unwrap()
            .expose_secret(),
        "new-secret"
    );
    assert!(
        manager
            .apply_secret_update(
                SecretUpdate::Clear {
                    provider: ProviderId::OpenAi
                },
                KeyEpoch(0)
            )
            .is_err()
    );
    assert_eq!(
        manager
            .apply_secret_update(
                SecretUpdate::Clear {
                    provider: ProviderId::OpenAi
                },
                KeyEpoch(1)
            )
            .unwrap(),
        KeyEpoch(2)
    );
    assert!(manager.read_secret(ProviderId::OpenAi).unwrap().is_none());
    assert_eq!(keys.writes(), 1);
}

#[test]
fn failed_persistence_keeps_existing_ciphertext_and_epoch() {
    let (manager, _, records) = manager(Some("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="));
    records.seed(
        ProviderId::OpenAi,
        KeyEpoch(6),
        Some("prior-value".to_owned()),
    );
    records.set_fail_writes(true);
    assert!(
        manager
            .apply_secret_update(
                SecretUpdate::Set {
                    provider: ProviderId::OpenAi,
                    value: SecretString::from("replacement".to_owned())
                },
                KeyEpoch(6)
            )
            .is_err()
    );
    assert_eq!(
        records.read(ProviderId::OpenAi).unwrap().stored.as_deref(),
        Some("prior-value")
    );
    assert_eq!(records.read(ProviderId::OpenAi).unwrap().epoch, KeyEpoch(6));
}

#[test]
fn rust_ciphertext_is_decrypted_by_python_without_keychain_or_app_imports() {
    let Some(root) = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).parent() else {
        panic!("app root missing")
    };
    let python = root.join(if cfg!(windows) {
        "backend/.venv/Scripts/python.exe"
    } else {
        "backend/.venv/bin/python"
    });
    assert!(
        python.is_file(),
        "Python compatibility gate requires the existing backend venv"
    );
    let (manager, keys, records) = manager(Some("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="));
    let plain = "rust-synthetic-한글-secret";
    manager
        .apply_secret_update(
            SecretUpdate::Set {
                provider: ProviderId::OpenAi,
                value: SecretString::from(plain.to_owned()),
            },
            KeyEpoch(0),
        )
        .unwrap();
    let stored = records.read(ProviderId::OpenAi).unwrap().stored.unwrap();
    let mut child=std::process::Command::new(python)
        .arg("-c").arg("import json,sys; from cryptography.fernet import Fernet; d=json.load(sys.stdin); p=Fernet(d['key'].encode()).decrypt(d['stored'][7:].encode()).decode(); sys.exit(0 if p==d['expected'] else 1)")
        .env_clear().stdin(std::process::Stdio::piped()).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::piped()).spawn().unwrap();
    use std::io::Write;
    child.stdin.take().unwrap().write_all(serde_json::to_string(&serde_json::json!({"key":keys.get_key().unwrap().unwrap().expose_secret(),"stored":stored,"expected":plain})).unwrap().as_bytes()).unwrap();
    assert!(child.wait_with_output().unwrap().status.success());
}

#[test]
fn invalid_primary_key_never_replaces_the_store_or_uses_a_file_fallback() {
    let (manager, keys, records) = manager(Some("invalid-key"));
    records.seed(
        ProviderId::OpenAi,
        KeyEpoch(8),
        Some("enc:v1:preserved".into()),
    );
    assert!(
        manager
            .apply_secret_update(
                SecretUpdate::Set {
                    provider: ProviderId::OpenAi,
                    value: SecretString::from("replacement".to_owned())
                },
                KeyEpoch(8)
            )
            .is_err()
    );
    assert_eq!(keys.writes(), 0);
    assert_eq!(
        keys.get_key().unwrap().unwrap().expose_secret(),
        "invalid-key"
    );
    assert_eq!(
        records.read(ProviderId::OpenAi).unwrap().stored.as_deref(),
        Some("enc:v1:preserved")
    );
}

#[test]
fn explicit_legacy_file_read_preserves_bytes_and_locked_store_does_not_fall_back() {
    let temp = tempfile::TempDir::new().unwrap();
    let path = temp.path().join(LEGACY_KEY_FILENAME);
    let key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    std::fs::write(&path, key).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let stored = format!(
        "{ENCRYPTED_PREFIX}{}",
        fernet::Fernet::new(key)
            .unwrap()
            .encrypt(b"legacy-synthetic")
    );
    let (manager, keys, records) = manager(None);
    let manager = manager.with_legacy_read_only(temp.path());
    records.seed(ProviderId::OpenAi, KeyEpoch(3), Some(stored));
    assert_eq!(
        manager
            .read_secret(ProviderId::OpenAi)
            .unwrap()
            .unwrap()
            .expose_secret(),
        "legacy-synthetic"
    );
    assert_eq!(std::fs::read_to_string(&path).unwrap(), key);
    assert!(!temp.path().join(CREDENTIAL_LOCK_FILENAME).exists());
    assert_eq!(keys.writes(), 0);
    keys.set_failure(Some(KeyStoreFailure::Locked));
    assert!(manager.read_secret(ProviderId::OpenAi).is_err());
    assert_eq!(std::fs::read_to_string(&path).unwrap(), key);
}

#[test]
fn concurrent_credential_updates_have_one_epoch_cas_winner() {
    let (_, keys, records) = manager(Some("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="));
    let barrier = Arc::new(std::sync::Barrier::new(2));
    let mut handles = Vec::new();
    for value in ["first", "second"] {
        let manager = CredentialManager::new(keys.clone(), records.clone(), None);
        let barrier = barrier.clone();
        handles.push(std::thread::spawn(move || {
            barrier.wait();
            manager.apply_secret_update(
                SecretUpdate::Set {
                    provider: ProviderId::OpenAi,
                    value: SecretString::from(value.to_owned()),
                },
                KeyEpoch(0),
            )
        }));
    }
    let successes = handles
        .into_iter()
        .map(|handle| handle.join().unwrap().is_ok())
        .filter(|success| *success)
        .count();
    assert_eq!(successes, 1);
    assert_eq!(records.read(ProviderId::OpenAi).unwrap().epoch, KeyEpoch(1));
    assert_eq!(keys.writes(), 0);
}

fn database_fixture() -> (
    tempfile::TempDir,
    sasoo_backend::storage::db::Db,
    sasoo_backend::storage::paths::RuntimePaths,
) {
    use sasoo_backend::storage::{
        db::{DbAccess, open_db},
        migrations::{create_backup, migrate_owned_db},
        paths::RuntimePaths,
    };
    let temp = tempfile::TempDir::new().unwrap();
    let root = temp.path().to_path_buf();
    let paths = RuntimePaths {
        app_data_root: root.clone(),
        db_path: root.join("sasoo.db"),
        config_path: root.join("config.json"),
        default_library_root: root.join("library"),
        library_root: root.join("library"),
        library_search_roots: vec![root.join("library")],
        owner_lock_path: root.join("runtime.lock"),
    };
    std::fs::write(
        root.join(".sasoo-rust-isolated-fixture"),
        b"synthetic-only\n",
    )
    .unwrap();
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    conn.execute_batch(include_str!("fixtures/legacy/schema.sql"))
        .unwrap();
    drop(conn);
    let db = open_db(&paths, DbAccess::ServerOwner).unwrap();
    let receipt = create_backup(&db, &root.join("before.sqlite")).unwrap();
    migrate_owned_db(&db, &receipt).unwrap();
    (temp, db, paths)
}

fn credential_database_snapshot(path: &std::path::Path) -> serde_json::Value {
    let conn = rusqlite::Connection::open_with_flags(
        path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .unwrap();
    let settings = conn
        .prepare("SELECT key,value FROM settings ORDER BY key")
        .unwrap()
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?))
        })
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    let epochs = conn
        .prepare("SELECT provider,epoch FROM runtime_credential_epochs ORDER BY provider")
        .unwrap()
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
        })
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    let revision: i64 = conn
        .query_row(
            "SELECT settings_revision FROM runtime_server_state WHERE singleton=1",
            [],
            |row| row.get(0),
        )
        .unwrap();
    serde_json::json!({"settings": settings, "epochs": epochs, "revision": revision})
}

#[test]
fn nonowners_set_is_forbidden_before_key_or_file_access_for_both_constructors() {
    use sasoo_backend::storage::db::{DbAccess, open_db};
    for access in [DbAccess::Worker, DbAccess::ReadOnly] {
        for key_state in ["missing", "existing", "locked"] {
            for use_public_constructor in [false, true] {
                let (_temp, _owner, paths) = database_fixture();
                let keys = Arc::new(MemoryKeyStore::new((key_state != "missing").then(|| {
                    SecretString::from("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=".to_owned())
                })));
                if key_state == "locked" {
                    keys.set_failure(Some(KeyStoreFailure::Locked));
                }
                let db = open_db(&paths, access).unwrap();
                let manager = if use_public_constructor {
                    CredentialManager::new(
                        keys.clone(),
                        Arc::new(DbCredentialRepository { db }),
                        Some(&paths.app_data_root),
                    )
                } else {
                    CredentialManager::for_db(keys.clone(), db, &paths.app_data_root)
                };
                let lock = paths.app_data_root.join(CREDENTIAL_LOCK_FILENAME);
                assert!(!lock.exists());
                let before = credential_database_snapshot(&paths.db_path);
                let error = manager
                    .apply_secret_update(
                        SecretUpdate::Set {
                            provider: ProviderId::OpenAi,
                            value: SecretString::from("synthetic-nonowner-probe".to_owned()),
                        },
                        KeyEpoch(0),
                    )
                    .unwrap_err();
                assert!(matches!(error, SasooError::Forbidden(_)));
                assert_eq!(keys.reads(), 0);
                assert_eq!(keys.write_attempts(), 0);
                assert_eq!(keys.writes(), 0);
                assert!(!lock.exists());
                assert!(before == credential_database_snapshot(&paths.db_path));
            }
        }
    }
}

#[test]
fn nonowners_clear_and_settings_are_forbidden_before_file_or_key_access() {
    use sasoo_backend::storage::db::{DbAccess, open_db};
    for access in [DbAccess::Worker, DbAccess::ReadOnly] {
        for clear_secret in [false, true] {
            let (_temp, _owner, paths) = database_fixture();
            let keys = Arc::new(MemoryKeyStore::new(None));
            let db = open_db(&paths, access).unwrap();
            let manager = CredentialManager::for_db(keys.clone(), db, &paths.app_data_root);
            let lock = paths.app_data_root.join(CREDENTIAL_LOCK_FILENAME);
            assert!(!lock.exists());
            let before = credential_database_snapshot(&paths.db_path);
            let updates = if clear_secret {
                vec![(SecretUpdate::Clear { provider: ProviderId::OpenAi }, KeyEpoch(0))]
            } else {
                Vec::new()
            };
            let error = manager
                .apply_settings_update(updates, BTreeMap::from([("theme".into(), "dark".into())]))
                .unwrap_err();
            assert!(matches!(error, SasooError::Forbidden(_)));
            assert_eq!(keys.reads(), 0);
            assert_eq!(keys.write_attempts(), 0);
            assert!(!lock.exists());
            assert!(before == credential_database_snapshot(&paths.db_path));
        }
    }
}

#[test]
fn nonowner_repository_commit_keeps_its_final_authorization_check() {
    use sasoo_backend::storage::db::{DbAccess, open_db};
    for access in [DbAccess::Worker, DbAccess::ReadOnly] {
        let (_temp, _owner, paths) = database_fixture();
        let repository = DbCredentialRepository { db: open_db(&paths, access).unwrap() };
        let before = credential_database_snapshot(&paths.db_path);
        let error = repository
            .commit_batch(Vec::new(), BTreeMap::from([("theme".into(), "dark".into())]))
            .unwrap_err();
        assert!(matches!(error, SasooError::Forbidden(_)));
        assert!(before == credential_database_snapshot(&paths.db_path));
    }
}

#[test]
fn db_secret_epoch_and_settings_revision_commit_atomically_and_worker_cannot_write() {
    use sasoo_backend::{
        http::settings::{SettingsPatch, SettingsService},
        storage::{
            credentials::DbCredentialRepository,
            db::{DbAccess, open_db},
        },
    };
    let (_temp, db, paths) = database_fixture();
    let keys = Arc::new(MemoryKeyStore::new(Some(SecretString::from(
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=".to_owned(),
    ))));
    let credentials = Arc::new(CredentialManager::for_db(
        keys.clone(),
        db.clone(),
        &paths.app_data_root,
    ));
    let service = SettingsService {
        db: db.clone(),
        credentials: credentials.clone(),
        library_setting_key: "library_path_darwin".into(),
        default_library: paths.library_root.to_string_lossy().into_owned(),
        home: paths.app_data_root.clone(),
        platform: sasoo_backend::storage::paths::Platform::MacOs,
    };
    let reply=service.update_settings(serde_json::from_value::<SettingsPatch>(serde_json::json!({"openai_api_key":"synthetic-new-key-123456789","ai_provider":"openai","theme":"dark"})).unwrap(),&[(ProviderId::OpenAi,KeyEpoch(0))],|raw|Ok(raw.to_owned())).unwrap();
    assert_eq!(reply.openai_api_key, "syntheti...6789");
    assert_eq!(reply.image_provider, "openai");
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    assert_eq!(
        conn.query_row(
            "SELECT settings_revision FROM runtime_server_state",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        1
    );
    let old = DbCredentialRepository { db: db.clone() }
        .read(ProviderId::OpenAi)
        .unwrap();
    assert!(
        service
            .update_settings(
                serde_json::from_value::<SettingsPatch>(
                    serde_json::json!({"openai_api_key":"should-not-save","theme":"light"})
                )
                .unwrap(),
                &[(ProviderId::OpenAi, KeyEpoch(0))],
                |raw| Ok(raw.to_owned())
            )
            .is_err()
    );
    assert_eq!(
        DbCredentialRepository { db: db.clone() }
            .read(ProviderId::OpenAi)
            .unwrap()
            .stored,
        old.stored
    );
    assert_eq!(
        conn.query_row("SELECT value FROM settings WHERE key='theme'", [], |row| {
            row.get::<_, String>(0)
        })
        .unwrap(),
        "dark"
    );
    assert_eq!(
        conn.query_row(
            "SELECT settings_revision FROM runtime_server_state",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        1
    );
    let worker = open_db(&paths, DbAccess::Worker).unwrap();
    let worker_manager = CredentialManager::for_db(keys, worker, &paths.app_data_root);
    assert!(
        worker_manager
            .apply_secret_update(
                SecretUpdate::Clear {
                    provider: ProviderId::OpenAi
                },
                KeyEpoch(1)
            )
            .is_err()
    );
}

#[test]
fn db_failure_after_cipher_update_rolls_back_cipher_epoch_and_other_settings() {
    use sasoo_backend::http::settings::{SettingsPatch, SettingsService};
    let (_temp, db, paths) = database_fixture();
    let keys = Arc::new(MemoryKeyStore::new(Some(SecretString::from(
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=".to_owned(),
    ))));
    let credentials = Arc::new(CredentialManager::for_db(
        keys,
        db.clone(),
        &paths.app_data_root,
    ));
    let service = SettingsService {
        db: db.clone(),
        credentials: credentials.clone(),
        library_setting_key: "library_path_darwin".into(),
        default_library: paths.library_root.to_string_lossy().into_owned(),
        home: paths.app_data_root.clone(),
        platform: sasoo_backend::storage::paths::Platform::MacOs,
    };
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('openai_api_key','prior-plaintext')",
        [],
    )
    .unwrap();
    conn.execute_batch("CREATE TRIGGER fail_theme BEFORE INSERT ON settings WHEN NEW.key='theme' BEGIN SELECT RAISE(ABORT,'injected persistence failure'); END;").unwrap();
    let patch: SettingsPatch = serde_json::from_value(
        serde_json::json!({"openai_api_key":"new-synthetic-secret","theme":"dark"}),
    )
    .unwrap();
    assert!(
        service
            .update_settings(patch, &[(ProviderId::OpenAi, KeyEpoch(0))], |raw| Ok(
                raw.into()
            ))
            .is_err()
    );
    assert_eq!(
        conn.query_row(
            "SELECT value FROM settings WHERE key='openai_api_key'",
            [],
            |row| row.get::<_, String>(0)
        )
        .unwrap(),
        "prior-plaintext"
    );
    assert_eq!(credentials.epoch(ProviderId::OpenAi).unwrap(), KeyEpoch(0));
    assert_eq!(
        conn.query_row(
            "SELECT settings_revision FROM runtime_server_state",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
    assert_eq!(
        conn.query_row(
            "SELECT COUNT(*) FROM settings WHERE key='theme'",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
}

#[test]
fn db_settings_library_fallback_and_noop_masks_preserve_storage() {
    use sasoo_backend::http::settings::{SettingsPatch, SettingsService};
    let (_temp, db, paths) = database_fixture();
    let keys = Arc::new(MemoryKeyStore::new(None));
    let credentials = Arc::new(CredentialManager::for_db(
        keys.clone(),
        db.clone(),
        &paths.app_data_root,
    ));
    let service = SettingsService {
        db: db.clone(),
        credentials,
        library_setting_key: "library_path_darwin".into(),
        default_library: paths.library_root.to_string_lossy().into_owned(),
        home: paths.app_data_root.clone(),
        platform: sasoo_backend::storage::paths::Platform::MacOs,
    };
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    let legacy = paths
        .app_data_root
        .join("legacy-library")
        .to_string_lossy()
        .into_owned();
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('library_path',?1)",
        [&legacy],
    )
    .unwrap();
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('library_path_darwin',?1)",
        [r"C:\Users\synthetic\library"],
    )
    .unwrap();
    assert_eq!(service.get_settings().unwrap().library_path, legacy);
    conn.execute(
        "UPDATE settings SET value='relative-library' WHERE key='library_path_darwin'",
        [],
    )
    .unwrap();
    assert_eq!(service.get_settings().unwrap().library_path, legacy);
    conn.execute(
        "UPDATE settings SET value='not-absolute' WHERE key='library_path'",
        [],
    )
    .unwrap();
    assert_eq!(
        service.get_settings().unwrap().library_path,
        service.default_library
    );
    let patch: SettingsPatch =
        serde_json::from_value(serde_json::json!({"openai_api_key":"masked...value"})).unwrap();
    service
        .update_settings(patch, &[], |raw| Ok(raw.into()))
        .unwrap();
    assert_eq!(keys.writes(), 0);
    assert_eq!(
        conn.query_row(
            "SELECT settings_revision FROM runtime_server_state",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
    assert_eq!(
        conn.query_row(
            "SELECT value FROM settings WHERE key='library_path_darwin'",
            [],
            |row| row.get::<_, String>(0)
        )
        .unwrap(),
        "relative-library"
    );
}

#[test]
fn nullable_legacy_secrets_and_unknown_settings_remain_null_on_read() {
    use sasoo_backend::http::settings::SettingsService;
    let (_temp, db, paths) = database_fixture();
    let keys = Arc::new(MemoryKeyStore::new(None));
    let credentials = Arc::new(CredentialManager::for_db(
        keys.clone(),
        db.clone(),
        &paths.app_data_root,
    ));
    let service = SettingsService {
        db,
        credentials,
        library_setting_key: "library_path_darwin".into(),
        default_library: paths.library_root.to_string_lossy().into_owned(),
        home: paths.app_data_root.clone(),
        platform: sasoo_backend::storage::paths::Platform::MacOs,
    };
    let conn = rusqlite::Connection::open(&paths.db_path).unwrap();
    conn.execute_batch("DROP TABLE settings; CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT,updated_at DATETIME DEFAULT CURRENT_TIMESTAMP); INSERT INTO settings(key,value) VALUES('openai_api_key',NULL),('old_unused_setting',NULL);").unwrap();
    let reply = service.get_settings().unwrap();
    assert_eq!(reply.openai_api_key, "");
    assert!(!reply.openai_key_unreadable);
    assert_eq!(
        conn.query_row(
            "SELECT COUNT(*) FROM settings WHERE value IS NULL",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        2
    );
    conn.execute("INSERT INTO settings(key,value) VALUES('theme',NULL)", [])
        .unwrap();
    assert!(service.get_settings().is_err());
    assert_eq!(
        conn.query_row(
            "SELECT COUNT(*) FROM settings WHERE value IS NULL",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        3
    );
    assert_eq!(keys.writes(), 0);
}
