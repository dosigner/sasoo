use crate::error::Result;
use std::{future::Future, pin::Pin};
use tokio::sync::mpsc;

pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;
pub type ResponseStream = mpsc::Receiver<Result<Vec<u8>>>;

// Headers can contain credentials and must not be logged or persisted.
pub struct HttpRequest {
    pub method: String,
    pub url: String,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

pub struct HttpResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

pub trait Transport: Send + Sync {
    fn send(&self, req: HttpRequest) -> BoxFuture<'_, Result<HttpResponse>>;
    fn send_stream(&self, req: HttpRequest) -> BoxFuture<'_, Result<(u16, ResponseStream)>>;
}
