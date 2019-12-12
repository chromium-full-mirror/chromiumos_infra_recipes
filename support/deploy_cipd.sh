#!/bin/bash -e

cd "$(dirname "$0")"

# Build all of the binaries and install them to cipd-bin/
export GOBIN=$(pwd)/cipd-bin
go install ./...
echo "Build the following"
ls -l cipd-bin/

# Bundle everything up as a CIPD package.
cipd create -pkg-def=cipd.yaml -ref latest -json-output deploy_cipd.json
