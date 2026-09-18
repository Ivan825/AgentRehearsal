# AgentCore Gateway + Policy (Path B)

Path A (local Cedar in the Strands hook) is what carries the demo. Path B puts the **same policy** in front of the
**same tools** on AWS: the tools become a Lambda target behind an AgentCore Gateway, and a Policy engine attached to
the Gateway evaluates each call in `LOG_ONLY` (rehearse) or `ENFORCE` (replay) mode.

This follows the AWS getting-started guide for Policy in AgentCore
(https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html). Steps below assume
Node 20+, the AWS CLI configured, and IAM permission to create roles, Lambda functions, gateways and policy engines.

## 1. Deploy the Lambda target

```bash
cd infra/lambda
zip tools.zip tools_handler.py
aws lambda create-function --function-name agentrehearsal-tools --runtime python3.12 --handler tools_handler.handler \
  --zip-file fileb://tools.zip --role arn:aws:iam::<ACCOUNT>:role/<lambda-basic-execution-role>
```

## 2. Gateway, target, policy engine

```bash
npm install -g @aws/agentcore
agentcore create --name AgentRehearsal --language Python --framework Strands --model-provider Bedrock --memory none
cd AgentRehearsal
agentcore add gateway --name RehearsalGateway --authorizer-type NONE --runtimes AgentRehearsal
agentcore add gateway-target --name SupportTools --type lambda-function-arn \
  --lambda-arn arn:aws:lambda:<REGION>:<ACCOUNT>:function:agentrehearsal-tools \
  --tool-schema-file ../tool_schema.json --gateway RehearsalGateway
agentcore add policy-engine --name RehearsalPolicy --attach-to-gateways RehearsalGateway --attach-mode LOG_ONLY
agentcore deploy
```

## 3. Generate the policy in AgentCore form and add it

Locally the policy names actions `Action::"refund_customer"`. On AgentCore the action is
`AgentCore::Action::"SupportTools___refund_customer"` and the resource is the Gateway ARN. The CLI renders that form:

```bash
cd backend
python -m agentrehearsal.cli policy --agentcore-target SupportTools --gateway-arn arn:aws:bedrock-agentcore:<REGION>:<ACCOUNT>:gateway/<ID> > ../infra/supportbot.agentcore.cedar
agentcore add policy --name SupportBotLeastPrivilege --engine RehearsalPolicy --source ../infra/supportbot.agentcore.cedar
agentcore deploy
```

## 4. Point the target agent at the Gateway

```bash
# backend/.env
AGENTREHEARSAL_GATEWAY_URL=https://<gateway-id>.gateway.bedrock-agentcore.<REGION>.amazonaws.com/mcp
AGENTREHEARSAL_GATEWAY_TOKEN=   # only if the gateway uses a JWT authorizer
```

```bash
python -m agentrehearsal.cli rehearse --model bedrock --tools gateway     # policy engine in LOG_ONLY
# switch the engine to ENFORCE (console, or update the gateway's policy engine configuration), then:
python -m agentrehearsal.cli replay --run runs/run_XXXX.json --model bedrock --tools gateway
```

With `--tools gateway` the local hook only observes (it never cancels); denials come back from the Gateway as tool
errors and are recorded as *blocked*. The Diagnose trace shows which boundary made the decision.

## 5. Run history in DynamoDB (optional)

`backend/agentrehearsal/store.py` writes run records to a DynamoDB table when `AGENTREHEARSAL_DDB_TABLE` is set
(partition key `run_id`). Without it, runs are JSON files in `backend/runs/`.

## Status

Path B has not yet been exercised against a live account from this repo. Run steps 1–3 once on Thursday night; if
anything blocks, Path A still carries the full demo.
