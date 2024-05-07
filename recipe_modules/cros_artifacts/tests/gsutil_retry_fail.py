# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import sysroot
from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_artifacts',
]



def RunSteps(api):
  target = common.BuildTarget()
  target.name = 'target'
  api.assertions.assertRaises(
      StepFailure, api.cros_artifacts.upload_artifacts, 'target-postsubmit',
      BuilderConfig.Id.POSTSUBMIT, 'artifacts_gs_bucket',
      artifacts_info=common.ArtifactsByService(
          legacy={
              'output_artifacts': [{
                  'artifact_types': [
                      common.ArtifactsByService.Legacy.EBUILD_LOGS
                  ],
                  'gs_locations': ['publish_gs_bucket'],
              },],
          },
      ), chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/{}'.format(target.name),
                              build_target=target),
      test_data='{"artifacts":{"legacy":{"artifacts":[{"paths":['
      '{"path":"@@DIR@@/foo","location":2},{"path":"@@DIR@@/bar","location":2}'
      '],"artifactType":"EBUILD_LOGS"}]}}}')


def attempt_download_file(api, attempt):
  step_text = 'upload artifacts.gsutil rsync'
  if attempt > 1:
    step_text += ' (' + str(attempt) + ')'
  return api.step_data(
      step_text,
      times_out_after=(api.cros_artifacts.gsutil_timeout_seconds + 1))


def attempt_publish_file(api, attempt):
  step_text = 'upload artifacts.publish artifacts.gsutil cp'
  if attempt > 1:
    step_text += ' (' + str(attempt) + ')'
  return api.step_data(
      step_text,
      times_out_after=(api.cros_artifacts.gsutil_timeout_seconds + 1))


def GenTests(api):
  yield api.test(
      'retry-fail-gsutil', attempt_download_file(api, 1),
      attempt_download_file(api, 2), attempt_download_file(api, 3),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='snapshot-orchestrator'))

  yield api.test(
      'retry-fail-gsutil-cp', attempt_publish_file(api, 1),
      attempt_publish_file(api, 2), attempt_publish_file(api, 3),
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='snapshot-orchestrator'))
