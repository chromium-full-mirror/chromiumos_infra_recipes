#!/bin/bash -e

cd "$(dirname "$0")"

# Make the bin dir. It's fine if it already exists.
mkdir -p cipd-bin

# Build all of the binaries and install them to cipd-bin/
# Set the OS and architecture corresponding to the GCE bots.
# This allows cross compilation.
GOOS=linux GOARCH=amd64 go build -o cipd-bin/ ./...
echo "Build the following"
ls -l cipd-bin/

# Bundle everything up as a CIPD package.
cipd create -pkg-def=cipd.yaml -ref latest -json-output deploy_cipd.json
