# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'build_reporting',
]

# infra/proto/src/chromiumos/builder_report.proto
from PB.chromiumos.build_report import BuildReportBeta as BuildReport
from PB.chromiumos.common import Channel

BuildStatus = BuildReport.BuildStatus
StepDetails = BuildReport.StepDetails


def RunSteps(api):
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE)

  for failure in [None, "failure", "infra_failure"]:
    with api.build_reporting.step_reporting(StepDetails.STEP_SYNC) \
         as step_report:
      # sync the tree
      if failure == "failure":
        step_report.fail()

      if failure == "infra_failure":
        step_report.infra_fail()


def GenTests(api):
  yield api.test('basic')
