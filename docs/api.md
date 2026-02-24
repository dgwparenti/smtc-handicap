# Webhook API Reference

The SMTC Handicap webhook API receives notifications about new results emails,
then automatically downloads the PDF, parses it, and ingests race data into the
SQLite database.

## Authentication

Protected endpoints require an `X-API-Key` header matching the server's
`SMTC_API_KEY` environment variable.

```
X-API-Key: <your-api-key>
```

The key is stored locally in `credentials/api_key.txt` and loaded into the
environment when starting the server.

## Endpoints

### `GET /health`

Returns database counts. No authentication required.

**Response:**

```json
{
  "status": "healthy",
  "db_counts": {
    "riders": 3276,
    "races": 525,
    "time_records": 53788
  }
}
```

### `POST /webhook/ingest`

Searches Gmail for a specific email, downloads its PDF attachment link, and
ingests the results into the database. Requires `X-API-Key` header.

**Request body:**

```json
{
  "sender": "annabel.kettler@cresta-run.com",
  "subject": "Daily Results - 24th Feb",
  "timestamp": "2026-02-24T13:16:56Z"
}
```

| Field       | Type   | Description                          |
|-------------|--------|--------------------------------------|
| `sender`    | string | Email sender address                 |
| `subject`   | string | Email subject line                   |
| `timestamp` | string | ISO-8601 timestamp of the email      |

**Response:**

```json
{
  "status": "success",
  "emails_found": 1,
  "pdfs_downloaded": 1,
  "pdfs_failed": 0,
  "ingestion_results": [
    {
      "pdf_filename": "20260224-results.pdf",
      "races": 2,
      "riders": 50,
      "time_records": 120,
      "warnings": [],
      "re_ingested": false
    }
  ],
  "errors": [],
  "db_counts": {
    "riders": 3326,
    "races": 527,
    "time_records": 53908
  }
}
```

**Status values:**

| Status           | Meaning                                              |
|------------------|------------------------------------------------------|
| `success`        | All PDFs downloaded and ingested                     |
| `partial`        | Some PDFs succeeded, some failed                     |
| `no_email_found` | Gmail search returned no matching emails             |
| `no_pdf_link`    | Email found but contained no PDF link                |
| `error`          | All PDFs failed to download or ingest                |

**Error codes:**

| Code | Meaning                                                  |
|------|----------------------------------------------------------|
| 403  | Missing or invalid `X-API-Key` header                    |
| 500  | `SMTC_API_KEY` environment variable not configured       |
| 502  | Gmail API error (quota exceeded, auth failure, etc.)     |

**Re-ingestion:** If a PDF with the same filename already exists in the
database, old records are deleted before re-ingesting. The response will show
`"re_ingested": true` for that PDF.

## Setup

### Install

```bash
pip install -e ".[api]"
```

This adds `fastapi` and `uvicorn` to your environment.

### Generate an API key

```bash
mkdir -p credentials
python -c "import secrets; print(secrets.token_urlsafe(32))" > credentials/api_key.txt
```

### Start the server

```bash
export SMTC_API_KEY=$(cat credentials/api_key.txt)
uvicorn smtc_handicap.api:app --host 0.0.0.0 --port 8000
```

The interactive docs are available at `http://localhost:8000/docs` (Swagger UI).

## Deployment

The API is deployed on a local machine behind a
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/),
exposing it at `https://webhook.crebayes.uk`.

### Cloudflare Tunnel setup

```bash
# Install cloudflared (macOS)
brew install cloudflared

# Authenticate (one-time)
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create smtc-webhook

# Run the tunnel — --protocol http2 is required for Zscaler/corporate proxies
cloudflared tunnel --protocol http2 run --url http://localhost:8000 smtc-webhook
```

The `--protocol http2` flag is needed because the default QUIC protocol is
blocked by some corporate proxy setups (e.g. Zscaler).

### DNS

Point `webhook.crebayes.uk` to the tunnel via a CNAME record in Cloudflare DNS,
targeting `<tunnel-id>.cfargotunnel.com`.

## Zapier integration

The webhook is triggered by a Zapier Zap that watches for new Gmail messages
matching a specific sender/subject pattern.

### Zap configuration

1. **Trigger:** Gmail > New Email Matching Search
   - Search: `from:annabel.kettler@cresta-run.com subject:"Daily Results"`
2. **Action:** Webhooks by Zapier > POST
   - **URL:** `https://webhook.crebayes.uk/webhook/ingest`
   - **Payload Type:** JSON
   - **Headers:**
     - `X-API-Key`: (your API key from `credentials/api_key.txt`)
   - **Body:**
     ```json
     {
       "sender": "{{from}}",
       "subject": "{{subject}}",
       "timestamp": "{{date}}"
     }
     ```

The `{{from}}`, `{{subject}}`, and `{{date}}` placeholders are filled
automatically by Zapier from the matched Gmail message.

## curl examples

### Health check

```bash
curl https://webhook.crebayes.uk/health
```

### Successful ingest

```bash
curl -X POST https://webhook.crebayes.uk/webhook/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $(cat credentials/api_key.txt)" \
  -d '{
    "sender": "annabel.kettler@cresta-run.com",
    "subject": "Daily Results - 24th Feb",
    "timestamp": "2026-02-24T13:16:56Z"
  }'
```

### Auth error (missing key)

```bash
curl -X POST https://webhook.crebayes.uk/webhook/ingest \
  -H "Content-Type: application/json" \
  -d '{"sender": "test@example.com", "subject": "Test", "timestamp": "2026-01-01T00:00:00Z"}'
```

Returns `403`:

```json
{
  "detail": "Invalid or missing API key"
}
```
