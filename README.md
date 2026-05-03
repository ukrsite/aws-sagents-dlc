# aws-sagents-dlc

AWS Strands Agents prototype implementing the full **AI-Driven Development Life Cycle (AI-DLC)** workflow.

## What's in this repo

| Directory | Description |
|---|---|
| [`ai-dlc-agent/`](ai-dlc-agent/) | The AI-DLC Strands Agent — main application |
| [`kiro-sandbox/`](kiro-sandbox/) | Sample target repository (Java Spring Boot API) used for testing |
| [`kiro-sandbox/.kiro/aws-aidlc-rule-details/`](kiro-sandbox/.kiro/aws-aidlc-rule-details/) | AI-DLC stage rule files (read-only, used by the agent) |
| [`docs/`](docs/) | Homework assignment and reference materials |

## Quick start

```bash
cd ai-dlc-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret

rm -rf kiro-sandbox/services/java-api/aidlc-docs/

python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As an admin, I want to view a paginated list of all users"

python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile"

python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As an admin, I want to view a paginated list of all users"


```

See [`ai-dlc-agent/README.md`](ai-dlc-agent/README.md) for full setup and usage instructions.
