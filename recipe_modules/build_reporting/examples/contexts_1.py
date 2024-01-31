# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.build_report import BuildReport
from recipe_engine import post_process

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
    with api.build_reporting.publish_to_gs(gs_path='gs://foo/bar'):
      with api.build_reporting.step_reporting(StepDetails.STEP_SYNC) \
          as step_report:
        # sync the tree
        if failure == 'failure':
          step_report.fail()

        if failure == 'infra_failure':
          step_report.infra_fail()


def GenTests(api):
  yield api.test(
      'basic',
      api.post_check(
          post_process.StepCommandContains,
          'upload build report to GS.gsutil write build_report.json to GS',
          ['gs://foo/bar/build_report.json'],
      ),
  )
