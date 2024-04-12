#!/bin/bash
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Run the recipes command in a tempdir. It will send all the commands that
# are specified on the command line to /tmp/XXXXX/recipes/recipes.py.
#
# Continuing to edit while this is running will result in unspecified behavor
# when git patch applies the contents.
#
# Usage: ./cider_recipes.sh test train --filter=build_release
#
# This script is pretty experimental.

set -e

ARGS=( "${@}" )

# Uncomment for testing.
# set -x

# Define the cleanup function.
# shellcheck disable=SC2317
cleanup() {
  rm -rf "${TEMP_DIR}"
}

pd() {
  if [[ $# -eq 0 ]]; then
    popd >/dev/null
  else
    pushd "$@" >/dev/null
  fi
}

cd "$(dirname "$0")"

# Prepare the workspace for the build.
TEMP_DIR="$(mktemp -d)"

pd ..
# Copy without git information or deps.
rsync -aL \
  --exclude=".recipe_deps/*" \
  --exclude=".git/*" \
  --exclude="**/__pycache__*" \
  recipes "${TEMP_DIR}"
pd

# Delete everything upon exit.
trap cleanup EXIT

# We'll output a patch that will get applied to the current workspace here.
pd "${TEMP_DIR}/recipes"
git init -q
git add . > /dev/null
git commit -q -m "initial tmp repo"

echo
echo "Running ./recipes.py" "${ARGS[@]}"

# Allow the ./recipes.py command to fail but return its exit code.
set +e
./recipes.py "${ARGS[@]}"
RECIPES_EXIT=$?
set -e

git add . > /dev/null
git commit -q -m "train content"
git diff HEAD~1 > "${TEMP_DIR}/run.patch"
pd

git apply --allow-empty "${TEMP_DIR}/run.patch"

exit "${RECIPES_EXIT}"
