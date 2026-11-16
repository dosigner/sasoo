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

/// Production HTTPS transport (reqwest + rustls, webpki roots).
/// shortcut: one 600 s timeout for the whole request, matching the OpenAI SDK read
/// timeout; upgrade to separate connect/read budgets when W04 sets provider policy.
pub struct HttpsTransport {
    client: reqwest::Client,
}

impl HttpsTransport {
    pub fn new() -> Result<Self> {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(600))
            .build()
            .map_err(|e| crate::error::SasooError::Internal(format!("HTTP client: {e}")))?;
        Ok(Self { client })
    }

    fn request(&self, req: HttpRequest) -> Result<reqwest::RequestBuilder> {
        let method = reqwest::Method::from_bytes(req.method.as_bytes())
            .map_err(|_| crate::error::SasooError::InvalidInput("HTTP method is invalid".into()))?;
        let mut builder = self.client.request(method, &req.url).body(req.body);
        for (name, value) in req.headers {
            builder = builder.header(name, value);
        }
        Ok(builder)
    }
}

fn transport_error(e: reqwest::Error) -> crate::error::SasooError {
    // reqwest errors carry the URL but never header values, so the key stays out.
    crate::error::SasooError::OutcomeUnknown(format!("HTTP transport failed: {e}"))
}

fn headers_of(map: &reqwest::header::HeaderMap) -> Vec<(String, String)> {
    map.iter()
        .filter_map(|(k, v)| Some((k.as_str().to_owned(), v.to_str().ok()?.to_owned())))
        .collect()
}

impl Transport for HttpsTransport {
    fn send(&self, req: HttpRequest) -> BoxFuture<'_, Result<HttpResponse>> {
        Box::pin(async move {
            let response = self.request(req)?.send().await.map_err(transport_error)?;
            let status = response.status().as_u16();
            let headers = headers_of(response.headers());
            let body = response.bytes().await.map_err(transport_error)?.to_vec();
            Ok(HttpResponse { status, headers, body })
        })
    }

    fn send_stream(&self, req: HttpRequest) -> BoxFuture<'_, Result<(u16, ResponseStream)>> {
        Box::pin(async move {
            let mut response = self.request(req)?.send().await.map_err(transport_error)?;
            let status = response.status().as_u16();
            let (sender, receiver) = mpsc::channel(32);
            tokio::spawn(async move {
                loop {
                    let item = match response.chunk().await {
                        Ok(Some(chunk)) => Ok(chunk.to_vec()),
                        Ok(None) => break,
                        Err(e) => Err(transport_error(e)),
                    };
                    let stop = item.is_err();
                    if sender.send(item).await.is_err() || stop {
                        break;
                    }
                }
            });
            Ok((status, receiver))
        })
    }
}
