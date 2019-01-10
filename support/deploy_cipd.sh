#!/bin/bash -e

cd "$(dirname "$0")"

(cd gerrit-fetch-changes && go build)

cipd create -pkg-def=cipd.yaml -ref latest -json-output deploy_cipd.json
