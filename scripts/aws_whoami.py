"""Print which AWS identity backend/.env resolves to and what it can do.

Run from the repo root with the backend venv active:
    python scripts/aws_whoami.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ENV = Path(__file__).resolve().parents[1] / "backend" / ".env"


def load_env() -> None:
    if not ENV.exists():
        print(f"missing {ENV}")
        sys.exit(1)
    for raw in ENV.read_text().splitlines():
        line = raw.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    load_env()
    region = os.environ.get("AWS_REGION", "us-east-1")
    ident = boto3.client("sts", region_name=region).get_caller_identity()
    arn = ident["Arn"]
    print(f"identity : {arn}")
    print(f"account  : {ident['Account']}")
    if ":user/" not in arn:
        print("NOTE: these keys are not an IAM user (root or role). Attach policies to this identity, not to 'agentrehearsal'.")
    else:
        name = arn.rsplit("/", 1)[-1]
        iam = boto3.client("iam")
        try:
            pols = [p["PolicyName"] for p in iam.list_attached_user_policies(UserName=name)["AttachedPolicies"]]
            print(f"attached : {pols or '(none)'}")
            for g in iam.list_groups_for_user(UserName=name)["Groups"]:
                gp = [p["PolicyName"] for p in iam.list_attached_group_policies(GroupName=g["GroupName"])["AttachedPolicies"]]
                print(f"group    : {g['GroupName']} -> {gp}")
            boundary = iam.get_user(UserName=name)["User"].get("PermissionsBoundary")
            if boundary:
                print(f"boundary : {boundary['PermissionsBoundaryArn']}  <- this caps what the user can do")
        except ClientError as e:
            print(f"iam      : cannot read own policies ({e.response['Error']['Code']}); check in the console instead")

    checks = {
        "ecr:GetAuthorizationToken": lambda: boto3.client("ecr", region_name=region).get_authorization_token(),
        "ecr:DescribeRepositories": lambda: boto3.client("ecr", region_name=region).describe_repositories(),
        "ecs:ListClusters": lambda: boto3.client("ecs", region_name=region).list_clusters(),
        "bedrock:ListInferenceProfiles": lambda: boto3.client("bedrock", region_name=region).list_inference_profiles(maxResults=1),
        "dynamodb:ListTables": lambda: boto3.client("dynamodb", region_name=region).list_tables(Limit=1),
    }
    for label, fn in checks.items():
        try:
            fn()
            print(f"OK       : {label}")
        except ClientError as e:
            print(f"DENIED   : {label} ({e.response['Error']['Code']})")


if __name__ == "__main__":
    main()
