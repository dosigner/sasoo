use std::{
    collections::HashSet,
    ffi::OsString,
    net::{IpAddr, Ipv4Addr},
};

use crate::{
    error::{Result, SasooError},
    types::{AttemptId, Generation, PaperId},
};
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Mode {
    Server {
        host: IpAddr,
        port: u16,
    },
    Worker {
        paper_id: PaperId,
        generation: Generation,
        attempt_id: Option<AttemptId>,
    },
}

fn invalid(message: &str) -> SasooError {
    SasooError::InvalidInput(message.into())
}

/// Parse arguments after the executable name. Secret values belong in the environment.
pub fn parse_cli(args: &[OsString]) -> Result<Mode> {
    let mut host = IpAddr::V4(Ipv4Addr::LOCALHOST);
    let mut port = 8000;
    let mut paper_id = None;
    let mut generation = Generation(0);
    let mut attempt_id = None;
    let mut seen = HashSet::new();
    let mut index = 0;
    while index < args.len() {
        let raw = args[index]
            .to_str()
            .ok_or_else(|| invalid("Arguments must be valid UTF-8"))?;
        let (flag, inline_value) = raw
            .split_once('=')
            .map_or((raw, None), |(flag, value)| (flag, Some(value)));
        if !matches!(
            flag,
            "--host" | "--port" | "--analyze-paper" | "--run-generation" | "--attempt-id"
        ) {
            return Err(invalid(
                "Unsupported argument; credentials must not be supplied on the command line",
            ));
        }
        if !seen.insert(flag) {
            return Err(invalid("Duplicate argument"));
        }
        let value = match inline_value {
            Some(value) => value,
            None => {
                index += 1;
                args.get(index)
                    .and_then(|value| value.to_str())
                    .ok_or_else(|| invalid("Argument value is missing or invalid"))?
            }
        };
        match flag {
            "--host" => {
                host = value
                    .parse()
                    .map_err(|_| invalid("Host must be an IP address"))?
            }
            "--port" => {
                port = value
                    .parse::<u16>()
                    .map_err(|_| invalid("Port must be between 1 and 65535"))?;
                if port == 0 {
                    return Err(invalid("Port must be between 1 and 65535"));
                }
            }
            "--analyze-paper" => {
                let id = value
                    .parse::<i64>()
                    .map_err(|_| invalid("Paper ID must be a positive integer"))?;
                if id <= 0 {
                    return Err(invalid("Paper ID must be a positive integer"));
                }
                paper_id = Some(PaperId(id));
            }
            "--run-generation" => {
                let parsed = value
                    .parse::<i64>()
                    .map_err(|_| invalid("Generation must be a nonnegative integer"))?;
                if parsed < 0 {
                    return Err(invalid("Generation must be a nonnegative integer"));
                }
                generation = Generation(parsed);
            }
            "--attempt-id" => {
                attempt_id = Some(AttemptId(
                    Uuid::parse_str(value).map_err(|_| invalid("Attempt ID must be a UUID"))?,
                ))
            }
            _ => unreachable!(),
        }
        index += 1;
    }
    if let Some(paper_id) = paper_id {
        if seen.contains("--host") || seen.contains("--port") {
            return Err(invalid("Worker and server arguments cannot be combined"));
        }
        Ok(Mode::Worker {
            paper_id,
            generation,
            attempt_id,
        })
    } else {
        if seen.contains("--run-generation") || seen.contains("--attempt-id") {
            return Err(invalid("Worker identity requires --analyze-paper"));
        }
        Ok(Mode::Server { host, port })
    }
}
