use lambda_http::{run, service_fn, tracing, Body, Error, Request, Response};
use uuid::Uuid;


#[derive(serde::Deserialize, Debug)]
struct AcceptibleRequest {
    device_id: Uuid,
    helper_psk: String,
}

/// This is the main body for the function.
/// Write your code inside it.
/// There are some code examples in the Runtime repository:
/// - <https://github.com/awslabs/aws-lambda-rust-runtime/tree/main/examples>
async fn function_handler(event: Request) -> Result<Response<Body>, Error> {
    // Get the body of the request.
    let body = event.body();
    // You can parse the body as JSON, form data, etc.
    let Ok(req) = serde_json::from_slice::<AcceptibleRequest>(body.as_ref()) else  {
        tracing::error!("Request body is not valid JSON");
        let resp = Response::builder()
        .status(400)
        .header("content-type", "application/json")
        .body(serde_json::json!({"error": "Invalid request body"}).to_string().into())
        .map_err(Box::new)?;
        return Ok(resp);
    };

    let acceptible_psk: String = std::env::var("JOIN_HELPER_PSK").expect("JOIN_HELPER_PSK must be set");
    let api_token: String = std::env::var("BOWTIE_API_TOKEN").expect("BOWTIE_API_TOKEN must be set");
    let bowtie_url: String = std::env::var("BOWTIE_CONTROLLER_URL").expect("BOWTIE_CONTROLLER_URL must be set");

    // Check if the helper_psk matches the environment variable
    if req.helper_psk != acceptible_psk {
        tracing::error!("Invalid helper_psk");
        let resp = Response::builder()
            .status(403)
            .header("content-type", "application/json")
            .body(serde_json::json!({"error": "Invalid helper_psk"}).to_string().into())
            .map_err(Box::new)?;
        return Ok(resp);
    }

    // If the request is valid, you can process it further.
    tracing::info!("Received valid request: {:?}", req);
    // Make an API call to bowtie
    let client = reqwest::Client::new();
    let response = client
        .post(format!("{}/-net/api/v0/device/state", bowtie_url))
        .header("Authorization", format!("Basic {}", api_token))
        .header("Content-Type", "application/json")
        .body(serde_json::json!({"devices": [{
            "id": req.device_id.to_string(),
            "state": "accepted",
        }]}).to_string())
        .send()
        .await?;
    if !response.status().is_success() {
        tracing::error!("Failed to join device: {}", response.status());
        let resp = Response::builder()
            .status(response.status())
            .header("content-type", "application/json")
            .body(serde_json::json!({"error": "Failed to join device"}).to_string().into())
            .map_err(Box::new)?;
        return Ok(resp);
    }
    tracing::info!("Device joined successfully");

    // Return something that implements IntoResponse.
    // It will be serialized to the right response event automatically by the runtime
    let resp = Response::builder()
        .status(200)
        .header("content-type", "text/html")
        .body("Device Accepted\n".into())
        .map_err(Box::new)?;
    Ok(resp)
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    // required to enable CloudWatch error logging by the runtime
    tracing::init_default_subscriber();

    run(service_fn(function_handler)).await
}