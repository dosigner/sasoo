use super::db::{Db, db_sql_error};
use crate::error::Result;
use std::collections::BTreeMap;

pub fn read_settings(db: &Db) -> Result<BTreeMap<String, String>> {
    db.blocking_call(|conn| {
        let mut query = conn
            .prepare("SELECT key,value FROM settings ORDER BY key")
            .map_err(db_sql_error)?;
        let rows = query
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .map_err(db_sql_error)?;
        rows.collect::<rusqlite::Result<BTreeMap<_, _>>>()
            .map_err(db_sql_error)
    })
}

pub fn apply_settings(db: &Db, updates: &BTreeMap<String, String>) -> Result<()> {
    let updates = updates.clone();
    db.blocking_call(move |conn|{
  let tx=conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(db_sql_error)?;
  let mut changed=0;
  for (key,value) in updates {changed+=tx.execute("INSERT INTO settings(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP WHERE settings.value IS NOT excluded.value",(key,value)).map_err(db_sql_error)?;}
  if changed>0 {
   let runtime_exists:bool=tx.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_schema WHERE type='table' AND name='runtime_server_state')",[],|r|r.get(0)).map_err(db_sql_error)?;
   if runtime_exists {tx.execute("UPDATE runtime_server_state SET settings_revision=settings_revision+1 WHERE singleton=1",[]).map_err(db_sql_error)?;}
  }
  tx.commit().map_err(db_sql_error)
 })
}
