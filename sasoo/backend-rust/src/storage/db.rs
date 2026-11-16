use super::paths::RuntimePaths;
use crate::error::{Result, SasooError};
use rusqlite::{Connection, OpenFlags};
use std::{
    fs::{File, OpenOptions},
    path::{Path, PathBuf},
    sync::{Arc, mpsc},
    time::Duration,
};

type Task = Box<dyn FnOnce(&mut Connection) + Send + 'static>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DbAccess {
    ServerOwner,
    Worker,
    ReadOnly,
}

#[derive(Clone)]
pub struct Db {
    inner: Arc<DbInner>,
}
struct DbInner {
    sender: mpsc::SyncSender<Task>,
    access: DbAccess,
    path: PathBuf,
    owner_id: Option<String>,
    owner_lock: Option<Arc<File>>,
}

#[derive(Debug)]
pub struct ConnectionPolicy {
    pub journal_mode: String,
    pub busy_timeout_ms: i64,
    pub foreign_keys: bool,
}

pub fn db_sql_error(error: rusqlite::Error) -> SasooError {
    match &error {
        rusqlite::Error::SqliteFailure(code, _)
            if matches!(
                code.code,
                rusqlite::ErrorCode::DatabaseBusy | rusqlite::ErrorCode::DatabaseLocked
            ) =>
        {
            SasooError::StorageBusy("SQLite is busy; retry only the storage operation".into())
        }
        _ => SasooError::Internal(format!("SQLite operation failed: {error}")),
    }
}

pub fn open_db(paths: &RuntimePaths, access: DbAccess) -> Result<Db> {
    if !paths.db_path.is_absolute() || !paths.db_path.is_file() {
        return Err(SasooError::NotFound(
            "An existing isolated SQLite database is required".into(),
        ));
    }
    let path = paths.db_path.canonicalize()?;
    let root = paths.app_data_root.canonicalize()?;
    if path.parent() != Some(root.as_path()) {
        return Err(SasooError::InvalidInput(
            "Database must be directly inside app_data_root".into(),
        ));
    }
    let owner_lock = if access == DbAccess::ServerOwner {
        // Derive the lock from the canonical DB path so aliases cannot bypass it.
        let lock_path = path.with_extension("db.runtime-owner.lock");
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(lock_path)?;
        file.try_lock().map_err(|_| {
            SasooError::Conflict("Another schema/queue owner holds this database".into())
        })?;
        Some(Arc::new(file))
    } else {
        None
    };
    let owner_id = if access == DbAccess::ServerOwner {
        Some(uuid::Uuid::new_v4().to_string())
    } else {
        None
    };
    start_connection(path, access, owner_id, owner_lock)
}

fn start_connection(
    path: PathBuf,
    access: DbAccess,
    owner_id: Option<String>,
    owner_lock: Option<Arc<File>>,
) -> Result<Db> {
    let flags = if access == DbAccess::ReadOnly {
        OpenFlags::SQLITE_OPEN_READ_ONLY
    } else {
        OpenFlags::SQLITE_OPEN_READ_WRITE
    };
    let mut conn = Connection::open_with_flags(&path, flags).map_err(db_sql_error)?;
    conn.busy_timeout(Duration::from_millis(5000))
        .map_err(db_sql_error)?;
    conn.pragma_update(None, "foreign_keys", true)
        .map_err(db_sql_error)?;
    if access != DbAccess::ReadOnly {
        conn.pragma_update(None, "journal_mode", "WAL")
            .map_err(db_sql_error)?;
    }
    let (sender, receiver) = mpsc::sync_channel::<Task>(64);
    let thread_owner_lock = owner_lock.clone();
    std::thread::Builder::new()
        .name("sasoo-sqlite".into())
        .spawn(move || {
            let _owner_lock = thread_owner_lock;
            while let Ok(task) = receiver.recv() {
                task(&mut conn);
            }
        })?;
    Ok(Db {
        inner: Arc::new(DbInner {
            sender,
            access,
            path,
            owner_id,
            owner_lock,
        }),
    })
}

impl Db {
    pub fn access(&self) -> DbAccess {
        self.inner.access
    }
    pub fn path(&self) -> &Path {
        &self.inner.path
    }
    pub fn owner_peer(&self) -> Result<Db> {
        let owner_id = self.owner_id()?.to_owned();
        start_connection(
            self.inner.path.clone(),
            DbAccess::ServerOwner,
            Some(owner_id),
            self.inner.owner_lock.clone(),
        )
    }
    pub(crate) fn owner_id(&self) -> Result<&str> {
        self.inner
            .owner_id
            .as_deref()
            .ok_or_else(|| SasooError::Forbidden("Only ServerOwner may back up or migrate".into()))
    }

    pub fn blocking_call<T, F>(&self, f: F) -> Result<T>
    where
        T: Send + 'static,
        F: FnOnce(&mut Connection) -> Result<T> + Send + 'static,
    {
        let (sender, receiver) = mpsc::sync_channel(1);
        self.inner
            .sender
            .try_send(Box::new(move |conn| {
                let _ = sender.send(f(conn));
            }))
            .map_err(|_| {
                SasooError::StorageBusy("SQLite execution queue is full or closed".into())
            })?;
        receiver
            .recv()
            .map_err(|_| SasooError::Internal("SQLite execution thread stopped".into()))?
    }

    pub async fn call<T, F>(&self, f: F) -> Result<T>
    where
        T: Send + 'static,
        F: FnOnce(&mut Connection) -> Result<T> + Send + 'static,
    {
        let (sender, receiver) = tokio::sync::oneshot::channel();
        self.inner
            .sender
            .try_send(Box::new(move |conn| {
                let _ = sender.send(f(conn));
            }))
            .map_err(|_| {
                SasooError::StorageBusy("SQLite execution queue is full or closed".into())
            })?;
        receiver
            .await
            .map_err(|_| SasooError::Internal("SQLite execution thread stopped".into()))?
    }

    pub fn connection_policy(&self) -> Result<ConnectionPolicy> {
        self.blocking_call(|conn| {
            Ok(ConnectionPolicy {
                journal_mode: conn
                    .pragma_query_value(None, "journal_mode", |r| r.get(0))
                    .map_err(db_sql_error)?,
                busy_timeout_ms: conn
                    .pragma_query_value(None, "busy_timeout", |r| r.get(0))
                    .map_err(db_sql_error)?,
                foreign_keys: conn
                    .pragma_query_value(None, "foreign_keys", |r| r.get(0))
                    .map_err(db_sql_error)?,
            })
        })
    }
}
