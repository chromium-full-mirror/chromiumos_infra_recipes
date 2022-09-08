#!/bin/bash

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_UNDER_TEST="recipe_scripts/tee_wrapper.sh"

PASSES=0
FAILS=0

TMPDIR=$(mktemp -d)
trap 'rm -rf "${TMPDIR}"' EXIT

# Verify tee_wrapper.sh on success using 'echo' command.
TEE_OUTPUT=${TMPDIR}/"echo_file.txt"
# Ensure the output file doesn't already exist.
echo "Running echo test"
"${SCRIPT_UNDER_TEST}" "${TEE_OUTPUT}" "echo" "a b c"
return_code=$?

# Verify non-error return code.
if [[ ${return_code} -ne 0 ]]; then
  echo "ECHO TEST FAILED"
  : $(( FAILS += 1 ))
fi

# Verify that the file contents match the command outout.
actual_contents=$(cat "${TEE_OUTPUT}")
expected_contents="a b c"
if [[ ${actual_contents} == "${expected_contents}" ]]; then
  : $(( PASSES += 1 ))
else
  echo "FAIL: ${TEE_OUTPUT}"
  echo "actual_contents -${actual_contents}- does not match"
  echo "   expected_contents -${expected_contents}-"
  : $(( FAILS += 1 ))
fi


# Verify tee_wrapper.sh propagates exit code on failure.
TEE_OUTPUT=${TMPDIR}/"error_file.txt"
echo "Running no_such_command test"
"${SCRIPT_UNDER_TEST}" "${TEE_OUTPUT}" "no_such_command" "a b c"
return_code=$?

# Verify non-error return code.
if [[ ${return_code} -eq 0 ]]; then
  echo "no_such_command TEST FAILED, should have returned non-zero."
  : $(( FAILS += 1 ))
fi
actual_contents=$(cat "${TEE_OUTPUT}")
if [[ ${actual_contents} == *"command not found"* ]]; then
  : $(( PASSES += 1 ))
else
  echo "FAIL: ${TEE_OUTPUT}"
  echo "Output -${actual_contents}- does not contain 'command not found'"
fi

echo "PASSES: ${PASSES} FAILS: ${FAILS}"

if [[ ${FAILS} -ne 0 ]]; then
  echo "FAILURE"
  exit 1
fi
