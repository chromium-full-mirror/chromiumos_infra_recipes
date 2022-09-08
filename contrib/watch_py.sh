#!/bin/bash

# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This script executes watchman-make to train for *.py changes.

# Assume we're in the contrib dir, one level above the project.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "${SCRIPT_DIR}" || exit 1
cd ".." || exit 1

if ! type watchman-make >/dev/null; then
  echo "Please install watchman-make, on debian:"
  printf "\tsudo apt install watchman python3-pywatchman\n"
  exit 1
fi

watchman-make -p "**/*.py" --run "./recipes.py test train"
