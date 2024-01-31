# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import BuildTarget
from PB.chromite.api import binhost as binhost_pb

from RECIPE_MODULES.chromeos.repo.api import ProjectInfo

DEPS = [
    'cros_prebuilts',
]



def RunSteps(api):
  BRANCH = 'main'
  PROJECT = ProjectInfo(name='proj', path='', branch=BRANCH, remote='', rrev='')

  # Normal run
  api.cros_prebuilts.set_binhosts_retry(
      binhosts=[(BuildTarget(name='amd64-generic'), 'gs://some-uri/')],
      private=False,
      key=binhost_pb.POSTSUBMIT_BINHOST,
      target_project=PROJECT,
      branch=BRANCH,
  )

  # Empty binhosts
  api.cros_prebuilts.set_binhosts_retry(
      binhosts=[],
      private=False,
      key=binhost_pb.POSTSUBMIT_BINHOST,
      target_project=PROJECT,
      branch=BRANCH,
  )


def GenTests(api):
  yield api.test('basic')
