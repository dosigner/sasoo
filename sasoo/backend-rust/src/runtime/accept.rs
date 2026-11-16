use crate::{
    analysis::config::ConfigSnapshot,
    error::{Result, SasooError},
    storage::{
        db::{Db, DbAccess},
        executions::{NewExecution, enqueue_execution},
    },
    types::{ExecutionId, Hash256, PaperEpoch, PaperId},
};

#[derive(Clone, Debug)]
pub struct PdfPreparationReceipt {
    pub paper_id: PaperId,
    pub paper_epoch: PaperEpoch,
    pub source_sha256: Hash256,
    pub extraction_version: String,
    pub ready: bool,
}

#[derive(Clone, Debug)]
pub struct AcceptInput {
    pub paper_id: PaperId,
    pub pdf_receipt: PdfPreparationReceipt,
    pub config: ConfigSnapshot,
    pub settings_revision: i64,
}

#[derive(Clone, Debug)]
pub struct AcceptedRun {
    pub paper_id: PaperId,
    pub execution_id: ExecutionId,
}

pub async fn accept_run(db: &Db, input: AcceptInput) -> Result<AcceptedRun> {
    if db.access() != DbAccess::ServerOwner {
        return Err(SasooError::Forbidden(
            "Only the schema/queue owner may accept an analysis".into(),
        ));
    }
    if !input.pdf_receipt.ready {
        return Err(SasooError::Incomplete(
            "PDF preparation has not completed".into(),
        ));
    }
    if input.paper_id != input.pdf_receipt.paper_id
        || input.pdf_receipt.extraction_version.trim().is_empty()
        || input.pdf_receipt.paper_epoch.0 < 0
        || input.settings_revision < 0
        || input.config.snapshot().pdf_identity.source_sha256 != input.pdf_receipt.source_sha256
    {
        return Err(SasooError::InvalidInput(
            "PDF receipt and immutable configuration do not describe the same prepared input"
                .into(),
        ));
    }
    let execution_id = ExecutionId(uuid::Uuid::new_v4());
    enqueue_execution(
        db,
        NewExecution {
            execution_id,
            paper_id: input.paper_id,
            paper_epoch: input.pdf_receipt.paper_epoch,
            source_sha256: input.pdf_receipt.source_sha256,
            extraction_version: input.pdf_receipt.extraction_version,
            config_bytes: input.config.canonical_bytes().to_vec(),
            config_hash: input.config.sha256(),
            settings_revision: input.settings_revision,
            secret_refs: input.config.snapshot().secret_refs.clone(),
        },
    )
    .await?;
    Ok(AcceptedRun {
        paper_id: input.paper_id,
        execution_id,
    })
}
