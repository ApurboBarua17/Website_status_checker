# Website Status Checker

A serverless tool that tells you whether any website is up or down — and exactly why. It checks DNS resolution, HTTP response, and port connectivity simultaneously, then cross-references results with external monitoring services. Optionally, it can run the same check from multiple AWS regions at once to determine whether an outage is local or global.

---

## What It Does

You type in a URL. The tool runs three independent checks against it:

1. **DNS Resolution** — Asks three public DNS servers (Google, Cloudflare, OpenDNS) whether the domain name can be resolved to an IP address. If none of them can find it, the domain itself may be expired or misconfigured.

2. **HTTP Response** — Sends an actual web request to the site and measures how long it takes to respond. Records the HTTP status code, whether the site redirected you, and how much data it returned.

3. **Port Connectivity** — Opens a direct TCP connection to port 443 (HTTPS) or port 80 (HTTP) to confirm the server is actively accepting connections — separate from whether the web page itself loads.

Results from all three checks are combined into a single verdict: **Up**, **Down**, **Partial** (DNS and port work but HTTP failed), or **DNS Only** (domain resolves but server is unreachable).

The tool also runs secondary checks against three free external monitoring services in parallel, giving a broader picture of the site's global availability.

---

## Why I Built It

I wanted a hands-on project that touched real cloud infrastructure end to end — not just a tutorial. This project gave me experience with:

- Designing and deploying serverless functions on AWS Lambda
- Defining infrastructure as code using AWS SAM (instead of clicking through the console)
- Thinking about performance: parallel execution, caching, and cold start behavior
- Building a clean frontend that talks to a cloud API without a traditional server in the middle

The problem it solves is also genuinely useful — when a site isn't loading, it's often unclear whether the issue is DNS, the server itself, or just a slow connection. This tool breaks that down clearly.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend** | Python 3.9 | Lambda function logic |
| **Cloud Functions** | AWS Lambda | Serverless compute — no server to manage |
| **API Layer** | AWS API Gateway | Public HTTP endpoint the frontend calls |
| **Database** | AWS DynamoDB | Caches external check results for 5 minutes |
| **Infrastructure** | AWS SAM (CloudFormation) | Defines all AWS resources as code |
| **Frontend** | HTML + CSS + Vanilla JS | Single-page UI |
| **Dev Server** | Vite | Local development with hot reload and API proxy |
| **Local DB** | DynamoDB Local (Docker) | Runs DynamoDB locally for development |

---

## How AI Was Used During Development

Claude (Anthropic) was used as a development collaborator throughout this project:

- **Architecture decisions** — Discussed tradeoffs between REST vs WebSocket for real-time status updates, and between Lambda vs EC2 for the backend. Lambda won for cost and simplicity at this scale.
- **Code review** — Identified that the external checks were running sequentially and suggested switching to `concurrent.futures.ThreadPoolExecutor` to run them in parallel, reducing response time.
- **Documentation** — Helped write plain-English explanations for every function so the code is readable to both technical and non-technical audiences.
- **Debugging** — Helped diagnose a CORS issue where the browser was blocking responses because the Lambda wasn't returning the right headers on OPTIONS preflight requests.
- **Frontend polish** — Suggested color-coding response times (green/yellow/red) and converting raw byte counts to KB/MB for readability.

AI was used to accelerate, not replace, the engineering decisions. Every line of code was reviewed and understood before being kept.

---

## Project Structure

```
website-status-checker/
├── backend/
│   ├── lambda_function.py   # All backend logic: DNS, HTTP, port, caching, multi-region
│   ├── template.yaml        # AWS SAM template — defines Lambda, API Gateway, DynamoDB
│   ├── requirements.txt     # Python dependencies (requests, boto3)
│   ├── samconfig.toml       # SAM deployment configuration (region, stack name)
│   └── env.json             # Environment variables for local SAM development
├── frontend/
│   ├── index.html           # HTML shell — the page structure
│   ├── src/
│   │   ├── main.js          # All JavaScript: API calls, result rendering, UI logic
│   │   └── style.css        # All styles: layout, cards, badges, responsive design
│   ├── package.json         # npm scripts (dev, build, preview)
│   └── vite.config.js       # Vite config — proxies /check requests to local backend
├── .env                     # Your AWS credentials (never committed to Git)
├── .env.example             # Template showing which keys are needed
├── .gitignore               # Excludes credentials, node_modules, build artifacts
└── start.sh                 # One-command startup script for local development
```

---

## Running Locally

### Prerequisites

Make sure these are installed before starting:

| Tool | Install |
|---|---|
| [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html) | `brew install aws-sam-cli` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Download and open the app |
| [Node.js + npm](https://nodejs.org/) | `brew install node` |
| [AWS CLI](https://aws.amazon.com/cli/) | `brew install awscli` |

### Step 1 — Clone and configure credentials

```bash
git clone <your-repo-url>
cd website-status-checker

# Copy the credentials template and fill in your AWS keys
cp .env.example .env
```

Edit `.env` and add your AWS credentials:
```
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_DEFAULT_REGION=us-east-2
```

### Step 2 — Start everything with one command

```bash
./start.sh
```

The script will:
1. Check all prerequisites are installed
2. Load your credentials from `.env`
3. Start a local DynamoDB database in Docker
4. Build the Lambda function with SAM
5. Start the backend API on `http://127.0.0.1:3000`
6. Install frontend dependencies if needed
7. Start the Vite dev server on `http://localhost:5173`
8. Open the app in your browser automatically

Press `Ctrl+C` to stop all servers cleanly.

### Running frontend and backend separately

If you prefer to run them independently:

**Backend:**
```bash
# Terminal 1 — local database
docker run -p 8000:8000 amazon/dynamodb-local

# Terminal 2 — API server
cd backend
sam build
sam local start-api --env-vars env.json
```

**Frontend:**
```bash
# Terminal 3 — dev server
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173`.

---

## Deploying to AWS

```bash
cd backend
sam build
sam deploy --guided
```

SAM will walk you through deployment. When finished it prints the live API Gateway URL. Paste that URL into the Settings panel in the frontend (click the Settings button in the top right), then deploy the frontend to any static host (S3, Netlify, Vercel, GitHub Pages).

---

## API Reference

### `POST /check` — Single region check

**Request:**
```json
{ "url": "google.com" }
```

**Response:**
```json
{
  "url": "https://google.com",
  "domain": "google.com",
  "status": "up",
  "response_time_ms": 431.07,
  "region": "us-east-2",
  "timestamp": "2026-04-30T22:05:40",
  "detailed_checks": {
    "dns":  { "overall_status": "success", "success_count": 3, "total_servers": 3 },
    "http": { "status": "success", "status_code": 200, "response_time_ms": 368 },
    "port": { "port": 443, "status": "open", "response_time_ms": 46 }
  },
  "summary": "DNS OK; HTTP OK; Port open"
}
```

### `POST /check-multi` — Multi-region check

Same request format. Response includes results from each region plus an overall verdict and analysis string.

---

## Status Definitions

| Status | Meaning |
|---|---|
| `up` | HTTP response was successful — the website loaded |
| `partial` | DNS resolved and port is open, but HTTP request failed |
| `dns_only` | Domain name resolved but the server port is closed |
| `down` | DNS resolution failed — domain cannot be found at all |
| `mixed` | *(Multi-region only)* Site is reachable from some regions but not others |
