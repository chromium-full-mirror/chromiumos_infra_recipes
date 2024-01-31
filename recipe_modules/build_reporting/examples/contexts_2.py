# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.build_report import BuildReport
from recipe_engine.recipe_api import InfraFailure, StepFailure

DEPS = [
    'recipe_engine/properties',
    'build_reporting',
]



BuildStatus = BuildReport.BuildStatus
StepDetails = BuildReport.StepDetails


def RunSteps(api):
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     'build_target')

  for failure in [None, 'failure', 'infra_failure']:
    try:
      with api.build_reporting.step_reporting(StepDetails.STEP_SYNC):
        # sync the tree
        if failure == 'failure':
          raise StepFailure('step failure')

        if failure == 'infra_failure':
          raise InfraFailure('infra failure')
    except (StepFailure, InfraFailure):
      continue


def GenTests(api):
  yield api.test('basic')
