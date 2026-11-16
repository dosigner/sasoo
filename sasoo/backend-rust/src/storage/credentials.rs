use crate::{
    error::{Result, SasooError},
    storage::db::{Db, db_sql_error},
    types::{KeyEpoch, ProviderId},
};
use fernet::Fernet;
use secrecy::{ExposeSecret, SecretString};
use std::{
    collections::BTreeMap,
    fs::{File, OpenOptions},
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};

pub const KEYRING_SERVICE: &str = "sasoo-desktop";
pub const KEYRING_ACCOUNT: &str = "fernet-key";
pub const ENCRYPTED_PREFIX: &str = "enc:v1:";
pub const LEGACY_KEY_FILENAME: &str = ".sasoo_key";
pub const CREDENTIAL_LOCK_FILENAME: &str = ".sasoo_credentials.lock";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyStoreFailure {
    Locked,
    Unavailable,
    Invalid,
    Unreadable,
}

pub enum SecretState {
    Missing,
    Readable(SecretString),
    Unreadable,
}

impl KeyStoreFailure {
    fn into_sasoo(self) -> SasooError {
        let reason = match self {
            Self::Locked => "OS credential store is locked. Unlock it and try again.",
            Self::Unavailable => "OS credential store is unavailable. Unlock it and try again.",
            Self::Invalid => "OS credential store contains an invalid encryption key.",
            Self::Unreadable => {
                "Stored API key cannot be decrypted with the available encryption key."
            }
        };
        SasooError::CredentialUnavailable(reason.to_owned())
    }
}

pub trait KeyStore: Send + Sync {
    fn get_key(&self) -> std::result::Result<Option<SecretString>, KeyStoreFailure>;
    fn set_key(&self, key: &SecretString) -> std::result::Result<(), KeyStoreFailure>;
}

// The application must explicitly construct this adapter; reads never create keys.
pub struct OsKeyStore;

#[cfg(any(target_os = "macos", target_os = "windows"))]
impl KeyStore for OsKeyStore {
    fn get_key(&self) -> std::result::Result<Option<SecretString>, KeyStoreFailure> {
        let entry =
            keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT).map_err(map_keyring_error)?;
        match entry.get_password() {
            Ok(key) if key.is_empty() => Ok(None),
            Ok(key) => Ok(Some(SecretString::from(key))),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(map_keyring_error(error)),
        }
    }

    fn set_key(&self, key: &SecretString) -> std::result::Result<(), KeyStoreFailure> {
        let entry =
            keyring::Entry::new(KEYRING_SERVICE, KEYRING_ACCOUNT).map_err(map_keyring_error)?;
        match entry.get_password() {
            Ok(current) if current == key.expose_secret() => Ok(()),
            Ok(current) if current.is_empty() => entry
                .set_password(key.expose_secret())
                .map_err(map_keyring_error),
            Ok(_) => Err(KeyStoreFailure::Unavailable),
            Err(keyring::Error::NoEntry) => entry
                .set_password(key.expose_secret())
                .map_err(map_keyring_error),
            Err(error) => Err(map_keyring_error(error)),
        }
    }
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn map_keyring_error(error: keyring::Error) -> KeyStoreFailure {
    match error {
        keyring::Error::NoStorageAccess(_) => KeyStoreFailure::Locked,
        keyring::Error::BadEncoding(_) | keyring::Error::Invalid(_, _) => KeyStoreFailure::Invalid,
        _ => KeyStoreFailure::Unavailable,
    }
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
impl KeyStore for OsKeyStore {
    fn get_key(&self) -> std::result::Result<Option<SecretString>, KeyStoreFailure> {
        Err(KeyStoreFailure::Unavailable)
    }
    fn set_key(&self, _: &SecretString) -> std::result::Result<(), KeyStoreFailure> {
        Err(KeyStoreFailure::Unavailable)
    }
}

#[derive(Clone)]
pub struct SecretRecord {
    pub epoch: KeyEpoch,
    pub stored: Option<String>,
}

pub struct EncryptedSecretUpdate {
    pub provider: ProviderId,
    pub expected_epoch: KeyEpoch,
    pub ciphertext: Option<String>,
}

pub trait CredentialRepository: Send + Sync {
    fn authorize_write(&self) -> Result<()>;
    fn read(&self, provider: ProviderId) -> Result<SecretRecord>;
    fn commit_batch(
        &self,
        secrets: Vec<EncryptedSecretUpdate>,
        settings: BTreeMap<String, String>,
    ) -> Result<Vec<(ProviderId, KeyEpoch)>>;
}

pub enum SecretUpdate {
    Set {
        provider: ProviderId,
        value: SecretString,
    },
    Clear {
        provider: ProviderId,
    },
}

impl SecretUpdate {
    pub fn provider(&self) -> ProviderId {
        match self {
            Self::Set { provider, .. } | Self::Clear { provider } => *provider,
        }
    }
}

pub struct CredentialManager {
    keys: Arc<dyn KeyStore>,
    repository: Arc<dyn CredentialRepository>,
    lock_path: Option<PathBuf>,
    legacy_key_path: Option<PathBuf>,
    local_lock: Mutex<()>,
}

impl CredentialManager {
    pub fn new(
        keys: Arc<dyn KeyStore>,
        repository: Arc<dyn CredentialRepository>,
        app_data_root: Option<&Path>,
    ) -> Self {
        Self {
            keys,
            repository,
            lock_path: app_data_root.map(|root| root.join(CREDENTIAL_LOCK_FILENAME)),
            legacy_key_path: None,
            local_lock: Mutex::new(()),
        }
    }

    pub fn for_db(keys: Arc<dyn KeyStore>, db: Db, app_data_root: &Path) -> Self {
        Self::new(
            keys,
            Arc::new(DbCredentialRepository { db }),
            Some(app_data_root),
        )
    }

    // Legacy reads are an explicit compatibility choice. The file is never changed.
    pub fn with_legacy_read_only(mut self, app_data_root: &Path) -> Self {
        self.legacy_key_path = Some(app_data_root.join(LEGACY_KEY_FILENAME));
        self
    }

    pub fn epoch(&self, provider: ProviderId) -> Result<KeyEpoch> {
        Ok(self.repository.read(provider)?.epoch)
    }

    pub fn read_secret(&self, provider: ProviderId) -> Result<Option<SecretString>> {
        match self.read_secret_state(provider)? {
            SecretState::Missing => Ok(None),
            SecretState::Readable(value) => Ok(Some(value)),
            SecretState::Unreadable => Err(KeyStoreFailure::Unreadable.into_sasoo()),
        }
    }

    pub fn read_secret_state(&self, provider: ProviderId) -> Result<SecretState> {
        let record = self.repository.read(provider)?;
        let Some(stored) = record.stored.filter(|value| !value.is_empty()) else {
            return Ok(SecretState::Missing);
        };
        let Some(token) = stored.strip_prefix(ENCRYPTED_PREFIX) else {
            return Ok(SecretState::Readable(SecretString::from(stored)));
        };
        let primary = self.keys.get_key().map_err(KeyStoreFailure::into_sasoo)?;
        if let Some(primary) = primary {
            let cipher = parse_key(&primary)?;
            if let Ok(plain) = cipher.decrypt(token) {
                return decode_plain(plain).map(SecretState::Readable);
            }
        }
        if let Some(path) = &self.legacy_key_path {
            if let Some(key) = read_legacy_key(path)? {
                if let Ok(plain) = parse_key(&key)?.decrypt(token) {
                    return decode_plain(plain).map(SecretState::Readable);
                }
            }
        }
        Ok(SecretState::Unreadable)
    }

    pub fn apply_secret_update(
        &self,
        update: SecretUpdate,
        expected_epoch: KeyEpoch,
    ) -> Result<KeyEpoch> {
        let epochs = self.apply_settings_update(vec![(update, expected_epoch)], BTreeMap::new())?;
        Ok(epochs[0].1)
    }

    pub fn apply_settings_update(
        &self,
        updates: Vec<(SecretUpdate, KeyEpoch)>,
        settings: BTreeMap<String, String>,
    ) -> Result<Vec<(ProviderId, KeyEpoch)>> {
        // Reject nonowners before accessing files or the key store.
        self.repository.authorize_write()?;
        if settings
            .keys()
            .any(|key| matches!(key.as_str(), "openai_api_key" | "gemini_api_key"))
        {
            return Err(SasooError::InvalidInput(
                "Secret fields must use the credential update boundary.".into(),
            ));
        }
        let _local_guard = self
            .local_lock
            .lock()
            .map_err(|_| SasooError::Internal("Credential update lock is unavailable.".into()))?;
        let _file_guard = self.acquire_file_lock()?;
        let mut seen = Vec::new();
        for (update, expected) in &updates {
            if seen.contains(&update.provider()) {
                return Err(SasooError::InvalidInput(
                    "Duplicate credential update.".into(),
                ));
            }
            seen.push(update.provider());
            if self.repository.read(update.provider())?.epoch != *expected {
                return Err(SasooError::Conflict(
                    "Credential changed. Reload settings and try again.".into(),
                ));
            }
        }
        let mut encrypted = Vec::new();
        for (update, expected_epoch) in updates {
            let provider = update.provider();
            let ciphertext = match update {
                SecretUpdate::Clear { .. } => None,
                SecretUpdate::Set { value, .. } => {
                    if value.expose_secret().is_empty() {
                        return Err(SasooError::InvalidInput(
                            "Use an explicit clear operation for an empty API key.".into(),
                        ));
                    }
                    let key = match self.keys.get_key().map_err(KeyStoreFailure::into_sasoo)? {
                        Some(key) => {
                            parse_key(&key)?;
                            key
                        }
                        None => {
                            // Only an explicit write with a confirmed missing entry can create a key.
                            let candidate = SecretString::from(Fernet::generate_key());
                            self.keys
                                .set_key(&candidate)
                                .map_err(KeyStoreFailure::into_sasoo)?;
                            let persisted = self
                                .keys
                                .get_key()
                                .map_err(KeyStoreFailure::into_sasoo)?
                                .ok_or_else(|| KeyStoreFailure::Unavailable.into_sasoo())?;
                            if persisted.expose_secret() != candidate.expose_secret() {
                                return Err(KeyStoreFailure::Unavailable.into_sasoo());
                            }
                            persisted
                        }
                    };
                    Some(format!(
                        "{ENCRYPTED_PREFIX}{}",
                        parse_key(&key)?.encrypt(value.expose_secret().as_bytes())
                    ))
                }
            };
            encrypted.push(EncryptedSecretUpdate {
                provider,
                expected_epoch,
                ciphertext,
            });
        }
        self.repository.commit_batch(encrypted, settings)
    }

    fn acquire_file_lock(&self) -> Result<Option<File>> {
        let Some(path) = &self.lock_path else {
            return Ok(None);
        };
        if !path.is_absolute() {
            return Err(SasooError::InvalidInput(
                "Credential root must be an absolute path.".into(),
            ));
        }
        if let Ok(metadata) = std::fs::symlink_metadata(path) {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(SasooError::CredentialUnavailable(
                    "Credential lock path is unsafe.".into(),
                ));
            }
        }
        let mut options = OpenOptions::new();
        options.read(true).write(true).create(true).truncate(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = options.open(path)?;
        file.try_lock().map_err(|_| {
            SasooError::StorageBusy("Credential update is already in progress.".into())
        })?;
        Ok(Some(file))
    }
}

fn parse_key(key: &SecretString) -> Result<Fernet> {
    Fernet::new(key.expose_secret()).ok_or_else(|| KeyStoreFailure::Invalid.into_sasoo())
}

fn decode_plain(bytes: Vec<u8>) -> Result<SecretString> {
    String::from_utf8(bytes)
        .map(SecretString::from)
        .map_err(|_| KeyStoreFailure::Unreadable.into_sasoo())
}

fn read_legacy_key(path: &Path) -> Result<Option<SecretString>> {
    let metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(KeyStoreFailure::Unavailable.into_sasoo()),
    };
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(KeyStoreFailure::Unreadable.into_sasoo());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(SasooError::CredentialUnavailable(
                "Legacy key permissions must restrict access to its owner.".into(),
            ));
        }
    }
    let key = SecretString::from(std::fs::read_to_string(path)?.trim().to_owned());
    parse_key(&key)?;
    Ok(Some(key))
}

pub struct DbCredentialRepository {
    pub db: Db,
}

fn provider_name(provider: ProviderId) -> &'static str {
    match provider {
        ProviderId::OpenAi => "openai",
        ProviderId::Gemini => "gemini",
    }
}

fn setting_name(provider: ProviderId) -> &'static str {
    match provider {
        ProviderId::OpenAi => "openai_api_key",
        ProviderId::Gemini => "gemini_api_key",
    }
}

impl CredentialRepository for DbCredentialRepository {
    fn authorize_write(&self) -> Result<()> {
        if self.db.access() != super::db::DbAccess::ServerOwner {
            return Err(SasooError::Forbidden(
                "Only the API server owner may change credentials.".into(),
            ));
        }
        Ok(())
    }

    fn read(&self, provider: ProviderId) -> Result<SecretRecord> {
        self.db.blocking_call(move |connection| {
            connection.query_row(
                "SELECT (SELECT value FROM settings WHERE key=?1), COALESCE((SELECT epoch FROM runtime_credential_epochs WHERE provider=?2),0)",
                rusqlite::params![setting_name(provider),provider_name(provider)],
                |row| Ok(SecretRecord{stored:row.get(0)?,epoch:KeyEpoch(row.get(1)?)}),
            ).map_err(db_sql_error)
        })
    }

    fn commit_batch(
        &self,
        secrets: Vec<EncryptedSecretUpdate>,
        settings: BTreeMap<String, String>,
    ) -> Result<Vec<(ProviderId, KeyEpoch)>> {
        self.authorize_write()?;
        self.db.blocking_call(move |connection| {
            use rusqlite::OptionalExtension;
            let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(db_sql_error)?;
            let mut epochs = Vec::new();
            let mut changed = false;
            for secret in secrets {
                let current = tx.query_row("SELECT epoch FROM runtime_credential_epochs WHERE provider=?1",[provider_name(secret.provider)],|row|row.get::<_,i64>(0))
                    .optional().map_err(db_sql_error)?.unwrap_or(0);
                if current != secret.expected_epoch.0 {
                    return Err(SasooError::Conflict("Credential changed. Reload settings and try again.".into()));
                }
                let next = current.checked_add(1).ok_or_else(||SasooError::Internal("Credential epoch overflow.".into()))?;
                tx.execute("INSERT INTO runtime_credential_epochs(provider,epoch) VALUES (?1,?2) ON CONFLICT(provider) DO UPDATE SET epoch=excluded.epoch",rusqlite::params![provider_name(secret.provider),next]).map_err(db_sql_error)?;
                tx.execute("INSERT INTO settings(key,value) VALUES (?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",rusqlite::params![setting_name(secret.provider),secret.ciphertext.unwrap_or_default()]).map_err(db_sql_error)?;
                epochs.push((secret.provider,KeyEpoch(next)));
                changed=true;
            }
            for (key,value) in settings {
                changed |= tx.execute("INSERT INTO settings(key,value) VALUES (?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP WHERE value IS NOT excluded.value",rusqlite::params![key,value]).map_err(db_sql_error)? > 0;
            }
            if changed {
                tx.execute("UPDATE runtime_server_state SET settings_revision=settings_revision+1 WHERE singleton=1",[]).map_err(db_sql_error)?;
            }
            tx.commit().map_err(db_sql_error)?;
            Ok(epochs)
        })
    }
}
