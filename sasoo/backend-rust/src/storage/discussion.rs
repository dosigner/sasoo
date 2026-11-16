//! Durable conversation rows. Reanalysis never resets this history.
use super::db::{Db, DbAccess, db_sql_error};
use crate::{
    error::{Result, SasooError},
    types::PaperId,
};
use rusqlite::params;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub id: i64,
    pub paper_id: i64,
    pub kind: String,
    pub content: String,
    pub status: String,
    pub reset_reason: Option<String>,
    pub model_used: Option<String>,
    pub tokens_in: Option<i64>,
    pub tokens_out: Option<i64>,
    pub cost_usd: Option<f64>,
    pub context: Option<Value>,
    pub created_at: String,
}

#[derive(Debug, Clone)]
pub struct Answer {
    pub content: String,
    pub status: String,
    pub model_used: Option<String>,
    pub tokens_in: Option<i64>,
    pub tokens_out: Option<i64>,
    pub cost_usd: Option<f64>,
    pub context: Option<Value>,
}

fn has_context_column(conn: &rusqlite::Connection) -> Result<bool> {
    let mut stmt = conn
        .prepare("PRAGMA table_info(discussion_messages)")
        .map_err(db_sql_error)?;
    let columns = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(db_sql_error)?;
    for column in columns {
        if column.map_err(db_sql_error)? == "context_json" {
            return Ok(true);
        }
    }
    Ok(false)
}

fn require_owner(db: &Db) -> Result<()> {
    if db.access() != DbAccess::ServerOwner {
        return Err(SasooError::Forbidden(
            "Only the server owner may write discussion messages".into(),
        ));
    }
    Ok(())
}

pub fn append_user(db: &Db, paper: PaperId, content: String) -> Result<i64> {
    require_owner(db)?;
    if content.trim().is_empty() {
        return Err(SasooError::InvalidInput("Message is required".into()));
    }
    db.blocking_call(move |conn| {
        if !has_context_column(conn)? {
            return Err(SasooError::Unsupported(
                "Discussion context column needs a verified migration".into(),
            ));
        }
        conn.execute(
            "INSERT INTO discussion_messages (paper_id,kind,content) VALUES (?1,'user',?2)",
            params![paper.0, content],
        )
        .map_err(db_sql_error)?;
        Ok(conn.last_insert_rowid())
    })
}

pub fn append_answer(db: &Db, paper: PaperId, answer: Answer) -> Result<i64> {
    require_owner(db)?;
    if !matches!(answer.status.as_str(), "complete" | "interrupted")
        || answer.tokens_in.is_some_and(|v| v < 0)
        || answer.tokens_out.is_some_and(|v| v < 0)
        || answer.cost_usd.is_some_and(|v| !v.is_finite() || v < 0.0)
        || (answer.status == "complete"
            && (answer.tokens_in.is_none()
                || answer.tokens_out.is_none()
                || answer.cost_usd.is_none()))
    {
        return Err(SasooError::InvalidInput(
            "Invalid answer status or usage".into(),
        ));
    }
    let context = answer
        .context
        .map(|v| serde_json::to_string(&v))
        .transpose()
        .map_err(|e| SasooError::InvalidInput(format!("Invalid answer context: {e}")))?;
    db.blocking_call(move |conn| {
        if !has_context_column(conn)? {return Err(SasooError::Unsupported("Discussion context column needs a verified migration".into()));}
        conn.execute("INSERT INTO discussion_messages (paper_id,kind,content,status,model_used,tokens_in,tokens_out,cost_usd,context_json) VALUES (?1,'sasoo',?2,?3,?4,?5,?6,?7,?8)",params![paper.0,answer.content,answer.status,answer.model_used,answer.tokens_in,answer.tokens_out,answer.cost_usd,context]).map_err(db_sql_error)?;
        Ok(conn.last_insert_rowid())
    })
}

pub fn append_reset(db: &Db, paper: PaperId, reason: String) -> Result<i64> {
    require_owner(db)?;
    if !matches!(reason.as_str(), "manual" | "budget") {
        return Err(SasooError::InvalidInput("Invalid reset reason".into()));
    }
    db.blocking_call(move |conn| {
        conn.execute("INSERT INTO discussion_messages (paper_id,kind,status,reset_reason) VALUES (?1,'reset','complete',?2)",params![paper.0,reason]).map_err(db_sql_error)?;
        Ok(conn.last_insert_rowid())
    })
}

fn query_messages(
    conn: &rusqlite::Connection,
    paper: PaperId,
    active: bool,
) -> Result<Vec<Message>> {
    let predicate = if active {
        "AND id > COALESCE((SELECT MAX(id) FROM discussion_messages WHERE paper_id=?1 AND kind='reset'),0) AND (kind='user' OR (kind='sasoo' AND status='complete'))"
    } else {
        ""
    };
    let context = if has_context_column(conn)? {
        "context_json"
    } else {
        "NULL AS context_json"
    };
    let sql = format!(
        "SELECT id,paper_id,kind,content,status,reset_reason,model_used,tokens_in,tokens_out,cost_usd,{context},created_at FROM discussion_messages WHERE paper_id=?1 {predicate} ORDER BY id"
    );
    let mut stmt = conn.prepare(&sql).map_err(db_sql_error)?;
    let rows = stmt
        .query_map([paper.0], |r| {
            let context: Option<String> = r.get(10)?;
            Ok(Message {
                id: r.get(0)?,
                paper_id: r.get(1)?,
                kind: r.get(2)?,
                content: r.get(3)?,
                status: r.get(4)?,
                reset_reason: r.get(5)?,
                model_used: r.get(6)?,
                tokens_in: r.get(7)?,
                tokens_out: r.get(8)?,
                cost_usd: r.get(9)?,
                context: context.and_then(|s| serde_json::from_str(&s).ok()),
                created_at: r.get(11)?,
            })
        })
        .map_err(db_sql_error)?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(db_sql_error)
}

fn read_messages(db: &Db, paper: PaperId, active: bool) -> Result<Vec<Message>> {
    db.blocking_call(move |conn| query_messages(conn, paper, active))
}

/// Read the prior active history and append the new question in one transaction.
pub fn begin_turn(db: &Db, paper: PaperId, content: String) -> Result<(Vec<Message>, i64)> {
    require_owner(db)?;
    if content.trim().is_empty() {
        return Err(SasooError::InvalidInput("Message is required".into()));
    }
    db.blocking_call(move |conn| {
        let tx = conn
            .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
            .map_err(db_sql_error)?;
        if !has_context_column(&tx)? {
            return Err(SasooError::Unsupported(
                "Discussion context column needs a verified migration".into(),
            ));
        }
        let history = query_messages(&tx, paper, true)?;
        tx.execute(
            "INSERT INTO discussion_messages (paper_id,kind,content) VALUES (?1,'user',?2)",
            params![paper.0, content],
        )
        .map_err(db_sql_error)?;
        let id = tx.last_insert_rowid();
        tx.commit().map_err(db_sql_error)?;
        Ok((history, id))
    })
}

pub fn list_messages(db: &Db, paper: PaperId) -> Result<Vec<Message>> {
    read_messages(db, paper, false)
}
pub fn active_context(db: &Db, paper: PaperId) -> Result<Vec<Message>> {
    read_messages(db, paper, true)
}
