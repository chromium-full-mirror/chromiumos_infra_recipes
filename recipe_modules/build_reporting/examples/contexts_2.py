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
from PB.chromiumos.build.payload.metadata import BuildMetadata

from recipe_engine.recipe_api import InfraFailure, StepFailure

BuildStatus = BuildReport.BuildStatus
StepDetails = BuildReport.StepDetails


def RunSteps(api):
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE)

  for failure in [None, "failure", "infra_failure"]:
    try:
      with api.build_reporting.step_reporting(StepDetails.STEP_SYNC):
        # sync the tree
        if failure == "failure":
          raise StepFailure("step failure")

        if failure == "infra_failure":
          raise InfraFailure("infra failure")
    except:
      continue


def GenTests(api):
  yield api.test('basic')
