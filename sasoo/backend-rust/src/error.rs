use std::{error::Error, fmt};

pub type Result<T> = std::result::Result<T, SasooError>;

#[derive(Debug)]
pub enum SasooError {
    NotFound(String),
    InvalidInput(String),
    Unauthorized(String),
    Forbidden(String),
    Conflict(String),
    BudgetBlocked(String),
    CredentialUnavailable(String),
    StorageBusy(String),
    Io(std::io::Error),
    FenceLost(String),
    Incomplete(String),
    OutcomeUnknown(String),
    Unsupported(String),
    Internal(String),
}

impl fmt::Display for SasooError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(error) => write!(f, "{error}"),
            Self::NotFound(message)
            | Self::InvalidInput(message)
            | Self::Unauthorized(message)
            | Self::Forbidden(message)
            | Self::Conflict(message)
            | Self::BudgetBlocked(message)
            | Self::CredentialUnavailable(message)
            | Self::StorageBusy(message)
            | Self::FenceLost(message)
            | Self::Incomplete(message)
            | Self::OutcomeUnknown(message)
            | Self::Unsupported(message)
            | Self::Internal(message) => f.write_str(message),
        }
    }
}

impl Error for SasooError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            _ => None,
        }
    }
}

impl From<std::io::Error> for SasooError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error)
    }
}
