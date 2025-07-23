# Website Status Checker

A full‑stack web application that lets you verify whether a website is up or down—either from a single AWS Lambda region or across multiple regions—and see detailed diagnostics (DNS, HTTP, port) plus external verifications.

Users can enter any URL (public or local via `host.docker.internal`), click **Check**, and get back a JSON report with status, response times, region info, and summaries.

---

## 🔧 Tech Stack & Tools

- **Backend**  
  - Python 3.9 on AWS Lambda  
  - AWS Serverless Application Model (SAM)  
  - API Gateway (local via `sam local start-api`)  
  - DynamoDB Local for caching “external_checks”  
  - boto3, botocore, requests, urllib, socket, concurrent.futures  

- **Frontend**  
  - React (Create‑React‑App)  
  - Tailwind CSS for styling  
  - `lucide-react` for icons  
  - Plain CSS + custom “cyber” design tokens  

- **Local Dev & CI**  
  - AWS CLI (`aws configure`)  
  - Docker (for DynamoDB Local)  
  - GitHub Actions (recommended) with `aws-actions/configure-aws-credentials`  

---

## 🏗️ Project Structure

```
website-status-checker/        # SAM backend
├─ backend/
│  ├─ lambda_function.py
│  ├─ template.yaml
│  ├─ env.json                # *ignored* in Git
│  └─ requirements.txt
website-status-frontend/       # React frontend
├─ public/
│  └─ index.html
├─ src/
│  ├─ components/
│  ├─ utils/
│  ├─ styles/
│  ├─ App.js
│  └─ index.js
├─ tailwind.config.js
├─ package.json
└─ .gitignore
```

---

## 🚀 Getting Started

### 1. Clone & Ignore Secrets

```bash
git clone https://github.com/your-org/website-status-checker.git
cd website-status-checker

# In .gitignore (if not already):
echo "
# local AWS creds
website‑checker‑dev_accessKeys.csv
env.json
*.csv
# React env
.env
" >> .gitignore
```

### 2. Configure AWS Credentials (Local)

```bash
aws configure
# Enter your Access Key ID / Secret — stored in ~/.aws/credentials
```

> **Do not** commit your `~/.aws/credentials` or any CSV with keys into Git.

### 3. Start DynamoDB Local (for caching)

```bash
docker run -d -p 8000:8000 --name dynamodb-local amazon/dynamodb-local
aws dynamodb create-table   --table-name website-status-cache   --attribute-definitions AttributeName=url,AttributeType=S AttributeName=type,AttributeType=S   --key-schema AttributeName=url,KeyType=HASH AttributeName=type,KeyType=RANGE   --billing-mode PAY_PER_REQUEST   --endpoint-url http://localhost:8000
```

### 4. Run the Backend (SAM)

```bash
cd backend
sam build
sam local start-api   --port 3001   --env-vars env.json
```

- **Endpoints**  
  - `POST http://localhost:3001/check`  
  - `POST http://localhost:3001/check-multi`

### 5. Run the Frontend (React)

```bash
cd ../website-status-frontend
npm install
# Add proxy to package.json:
#   "proxy": "http://localhost:3001",
npm start
```

- **Open** http://localhost:3000  
- Enter a URL and click **Check Website Status** (or **Multi‑Region**)

---

## 🔑 Securing Your AWS Keys

1. **Never** commit them in source.  
2. Use `aws configure` (writes to `~/.aws/credentials`).  
3. If you need project‑specific vars, use a `.env` file and add it to `.gitignore`.  
4. In CI/CD (e.g. GitHub Actions), add your keys under **Settings → Secrets**, then:

   ```yaml
   # .github/workflows/deploy.yml
   - uses: aws-actions/configure-aws-credentials@v2
     with:
       aws-access-key-id:     ${{ secrets.AWS_ACCESS_KEY_ID }}
       aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
       aws-region:            us-east-2
   ```

---

## 🎯 What’s Next

- Hook up a custom domain via Route 53 & CloudFront.  
- Add authentication/authorization.  
- Persist historical checks in DynamoDB table.  
- Dockerize the React app for uniform local dev.  


