#!/bin/bash

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# A helper to wrap calls so that output is tee'd to a known file.
# Rather than calling 'command arg1 arg2', a recipe could call:
# '/<full/path>/bin/tee_wrapper.sh /path/to/output.txt command arg1 arg2
# and after the command executes the recipe can read /path/to/output.txt.

# A script wrapper is needed because recipes calls other commands as a list
# containing the binary and the arguments, and not as a pure string allowing
# direct use of 'tee' and output redirection (>&, 2>&1, etc.).

if [[ $# -lt 2 ]]; then
  echo "USAGE: $0 <tee_file> <command> [optional command arguments]"
  exit 1
fi

# Remove output file, use below with 'tee'.
output_file=$1
shift 1

"$@" |& tee "${output_file}"
exit "${PIPESTATUS[0]}"
