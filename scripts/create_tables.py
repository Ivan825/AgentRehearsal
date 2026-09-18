"""Create the DynamoDB table AgentRehearsal uses (one table, pk/sk keys, on-demand billing).

    cd backend && source .venv/bin/activate && python ../scripts/create_tables.py
Then set AGENTREHEARSAL_DDB_TABLE=agentrehearsal in backend/.env.
"""
import sys
import time

import boto3

sys.path.insert(0, ".")
from agentrehearsal import config  # noqa: E402  (loads .env)

name = sys.argv[1] if len(sys.argv) > 1 else "agentrehearsal"
ddb = boto3.client("dynamodb", region_name=config.AWS_REGION)
try:
    ddb.describe_table(TableName=name)
    print(f"table {name} already exists in {config.AWS_REGION}")
except ddb.exceptions.ResourceNotFoundException:
    ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                     AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
                     KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
    print(f"creating {name} ...", end="", flush=True)
    while ddb.describe_table(TableName=name)["Table"]["TableStatus"] != "ACTIVE":
        time.sleep(2); print(".", end="", flush=True)
    print(" ACTIVE")
print(f"now add to backend/.env:  AGENTREHEARSAL_DDB_TABLE={name}")
