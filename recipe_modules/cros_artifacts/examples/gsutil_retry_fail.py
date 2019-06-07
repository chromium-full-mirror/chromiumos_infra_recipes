# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_artifacts',
]

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig


def RunSteps(api):
  target = common.BuildTarget()
  target.name = 'target'
  api.assertions.assertRaises(
      api.step.StepFailure, api.cros_artifacts.upload_artifacts,
      target, BuilderConfig.Id.POSTSUBMIT,
      'artifacts_gs_bucket', [BuilderConfig.Artifacts.EBUILD_LOGS])


def attempt_download_file(api, attempt):
  step_text = 'upload artifacts.gsutil rsync'
  if attempt > 1:
    step_text += ' (' + str(attempt) + ')'
  return api.step_data(
      step_text,
      times_out_after=(api.cros_artifacts.gsutil_timeout_seconds + 1))


def GenTests(api):
  yield (api.test('retry_fail_gsutil') + attempt_download_file(
      api, 1) + attempt_download_file(api, 2) + attempt_download_file(api, 3) +
         api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                                  builder='postsubmit-orchestrator'))
