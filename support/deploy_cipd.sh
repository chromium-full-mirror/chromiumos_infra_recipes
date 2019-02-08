#!/bin/bash -e

cd "$(dirname "$0")"

for go_tool in gerrit-fetch-changes repo-manifest-diff-projects repo-log-trace
do
  (cd "${go_tool}" && go build)
done

cipd create -pkg-def=cipd.yaml -ref latest -json-output deploy_cipd.json
