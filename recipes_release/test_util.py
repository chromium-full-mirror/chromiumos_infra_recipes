#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This file contains common functions/variables for use in unit tests."""

import subprocess

SUBPROCESS_KWARGS = {
    'encoding': 'utf-8',
    'capture_output': True,
    'check': True,
}


def subprocess_stdout(stdout: str) -> subprocess.CompletedProcess:
  """subprocess_stdout returns a successful response for subprocess.run"""
  return subprocess.CompletedProcess([], 0, stdout)
