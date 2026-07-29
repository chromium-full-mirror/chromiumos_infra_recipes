#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Common constants / classes for recipes release."""

import os
import subprocess
import typing

RET_CODE_SUCCESS = 0
# This is the error code that the argparser will system exit with.
RET_CODE_COMMAND_ERROR = 2
RET_CODE_OK_NO_RELEASE = 10
RET_CODE_OK_NO_CHANGES = 11
RET_CODE_OK_STAGING_FAILURES = 12
RET_CODE_NO_COVERED = 20
RET_CODE_NO_RELEASABLE = 21
RET_CODE_INTERNAL_ERROR = 99

RECIPE_BUNDLE = os.path.join('infra', 'recipe_bundles',
                             'chromium.googlesource.com', 'chromiumos', 'infra',
                             'recipes')

BOLDRED = '\033[1;31m'
BOLDGREEN = '\033[1;32m'
BOLDBLUE = '\033[1;34m'
RESET = '\033[0m'

# CipdInstances are instance IDs, as found on the CIPD UI under "Instances".
# For example: "M4HmuQVGbx8YQVkM61c6LnCHVFgpJsSy1bI4DpBjSTwC"
CipdInstance = typing.NewType('CipdInstance', str)
# CipdRefs are named refs, as found on the CIPD UI under "Refs".
# For example: "prod" or "release_2022/09/23-12".
CipdRef = typing.NewType('CipdRef', str)
# CipdVersions can be either instance IDs or named refs.
# These are commonly accepted by the cipd CLI's `-version` flag.
CipdVersion = typing.Union[CipdInstance, CipdRef]
# GitHashes are the SHA of a Git commit (in the recipes repo).
# For example: "5d185ee5339976575a282971eef16f590405217f"
GitHash = typing.NewType('GitHash', str)


def get_timestamp(fmt: str = ''):
  """Get a current timestamp in California time.

  Use Bash's `date` because Python standard lib is shockingly bad at timezones
  prior to Py3.9.
  """
  env = {'TZ': 'America/Los_Angeles'}
  cmd = ['date']
  if fmt:
    cmd.append(f'+{fmt}')
  p = subprocess.run(cmd, capture_output=True, encoding='utf-8', env=env,
                     check=True)
  return p.stdout.strip()
