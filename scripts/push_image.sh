#!/usr/bin/env bash
# Build the API image and push it to ECR. Needs Docker and the AWS CLI configured (aws configure).
#   ./scripts/push_image.sh            -> prints the image URI to paste into ECS Express Mode
set -euo pipefail
cd "$(dirname "$0")/../backend"
REGION="${AWS_REGION:-us-east-1}"
REPO="${ECR_REPO:-agentrehearsal-api}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
URI="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO"
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 || aws ecr create-repository --repository-name "$REPO" --region "$REGION" >/dev/null
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
docker build --platform linux/amd64 -t "$REPO:latest" .
docker tag "$REPO:latest" "$URI:latest"
docker push "$URI:latest"
echo
echo "IMAGE URI:  $URI:latest"
