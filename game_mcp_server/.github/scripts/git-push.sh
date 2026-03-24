#!/bin/bash

set -euo pipefail

FILE_TO_MODIFY=$1
NEW_IMAGE_URL=$2
ENV=$3
REPO_NAME=$4
COMMIT_MSG=$5
COMMIT_URL=$6
ACTION_URL=$7

cd gitops-repo
ls -l

REGISTRY="${NEW_IMAGE_URL%%/*}"
IMAGE_NAME="${NEW_IMAGE_URL#*/}"

echo "REGISTRY: ${REGISTRY}"
echo "IMAGE_NAME: ${IMAGE_NAME}"
echo "FILE_TO_MODIFY: ${FILE_TO_MODIFY}"

sed -i "1,25s|image: .*|image: ${REGISTRY}/${IMAGE_NAME}|g" "$FILE_TO_MODIFY"
git config user.name "gitops action"
git config user.email "gitops_action@github.com"
git add .
if git diff-index --quiet HEAD --; then
    echo "image镜像名称替换失败！！！"
    exit 1
fi

git commit -F- <<EOF
deploy[$ENV][$REPO_NAME]: $COMMIT_MSG

action: $ACTION_URL
commit: $COMMIT_URL
EOF

git push
