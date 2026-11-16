use super::db::{Db, db_sql_error};
use crate::{error::Result, types::PaperId};
use rusqlite::{OptionalExtension, types::ValueRef};
use serde_json::{Map, Value};
use std::collections::BTreeMap;

#[derive(Debug, Clone)]
pub struct LegacyPaper {
    pub fields: Map<String, Value>,
}
#[derive(Debug, Clone)]
pub struct LegacyResult {
    pub id: i64,
    pub paper_id: Option<i64>,
    pub phase: String,
    pub result: String,
    pub model_used: Option<String>,
    pub tokens_in: Option<i64>,
    pub tokens_out: Option<i64>,
    pub cost_usd: Option<f64>,
    pub input_hash: Option<String>,
    pub created_at: Option<String>,
    pub interaction_id: Option<String>,
}

pub fn row_json(row: &rusqlite::Row<'_>) -> rusqlite::Result<Map<String, Value>> {
    let mut fields = Map::new();
    for i in 0..row.as_ref().column_count() {
        let value = match row.get_ref(i)? {
            ValueRef::Null => Value::Null,
            ValueRef::Integer(x) => Value::from(x),
            ValueRef::Real(x) => Value::from(x),
            ValueRef::Text(x) => Value::String(String::from_utf8(x.to_vec()).map_err(|e| {
                rusqlite::Error::FromSqlConversionFailure(
                    i,
                    rusqlite::types::Type::Text,
                    Box::new(e),
                )
            })?),
            ValueRef::Blob(_) => {
                return Err(rusqlite::Error::InvalidColumnType(
                    i,
                    row.as_ref().column_name(i)?.into(),
                    rusqlite::types::Type::Blob,
                ));
            }
        };
        fields.insert(row.as_ref().column_name(i)?.into(), value);
    }
    Ok(fields)
}

pub fn read_paper(db: &Db, id: PaperId) -> Result<Option<LegacyPaper>> {
    db.blocking_call(move |conn| {
        conn.query_row("SELECT * FROM papers WHERE id=?1", [id.0], |row| {
            Ok(LegacyPaper {
                fields: row_json(row)?,
            })
        })
        .optional()
        .map_err(db_sql_error)
    })
}

pub fn latest_results(db: &Db, id: PaperId) -> Result<BTreeMap<String, LegacyResult>> {
    db.blocking_call(move |conn|{
  let mut query=conn.prepare("SELECT id,paper_id,phase,result,model_used,tokens_in,tokens_out,cost_usd,input_hash,created_at,interaction_id FROM analysis_results WHERE paper_id=?1 ORDER BY created_at DESC,id DESC").map_err(db_sql_error)?;
  let rows=query.query_map([id.0],|r|Ok(LegacyResult{id:r.get(0)?,paper_id:r.get(1)?,phase:r.get(2)?,result:r.get(3)?,model_used:r.get(4)?,tokens_in:r.get(5)?,tokens_out:r.get(6)?,cost_usd:r.get(7)?,input_hash:r.get(8)?,created_at:r.get(9)?,interaction_id:r.get(10)?})).map_err(db_sql_error)?;
  let mut result=BTreeMap::new(); for row in rows {let row=row.map_err(db_sql_error)?;result.entry(row.phase.clone()).or_insert(row);}
  Ok(result)
 })
}
