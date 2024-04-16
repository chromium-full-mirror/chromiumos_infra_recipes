# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import CrosArtifactsProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/cv',
    'recipe_engine/properties',
    'cros_artifacts',
    'cros_build_api',
]



def RunSteps(api):
  config = BuilderConfig()

  api.cros_artifacts.upload_artifacts(
      'builder', config.id.type, config.artifacts.artifacts_gs_bucket,
      artifacts_info=config.artifacts.artifacts_info,
      sysroot=Sysroot(path='/build/target',
                      build_target=BuildTarget(name='target')))


def GenTests(api):
  SOME_FAILED_RESPONSE = '''{
  "artifacts": {
    "image": {
      "artifacts": [
        {
          "artifactType": 34,
          "paths": [
            {
              "location": 2,
              "path": "/b/s/w/ir/x/w/recipe_cleanup/artifactsjyhpy4i9/dlc"
            },
            {
              "location": 2,
              "path": "/b/s/w/ir/x/w/recipe_cleanup/artifactsjyhpy4i9/dlc-scaled"
            }
          ]
        }
      ]
    },
    "sysroot": {
      "artifacts": [
        {
          "artifactType": 32,
          "paths": [
            {
              "location": 2,
              "path": "/b/s/w/ir/x/w/recipe_cleanup/artifactsjyhpy4i9/debug.tgz"
            }
          ]
        },
        {
          "artifactType": 40,
          "failed": true,
          "failureReason": "return code: 1; ..."
        }
      ]
    }
  }
}'''

  yield api.test(
      'some-failed',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          SOME_FAILED_RESPONSE),
      api.post_check(post_process.MustRun, 'upload artifacts.gsutil rsync'),
      api.post_check(post_process.StepFailure,
                     'upload artifacts.call artifacts service'),
      api.post_check(post_process.StepTextEquals,
                     'upload artifacts.call artifacts service',
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.post_check(post_process.ResultReason,
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'some-failed-cq-dry-run',
      api.cv(run_mode=api.cv.DRY_RUN),
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          SOME_FAILED_RESPONSE),
      api.post_check(post_process.MustRun, 'upload artifacts.gsutil rsync'),
      api.post_check(post_process.StepFailure,
                     'upload artifacts.call artifacts service'),
      api.post_check(post_process.StepTextEquals,
                     'upload artifacts.call artifacts service',
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.post_check(post_process.ResultReason,
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'some-failed-superceded',
      api.step_data('upload artifacts.gsutil rsync', retcode=1),
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          SOME_FAILED_RESPONSE),
      api.post_check(post_process.MustRun, 'upload artifacts.gsutil rsync'),
      api.post_check(
          post_process.ResultReason,
          "Infra Failure: Step('upload artifacts.gsutil rsync') (retcode: 1)"),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )

  ALL_FAILED_RESPONSE = '''{
  "artifacts": {
    "sysroot": {
      "artifacts": [
        {
          "artifactType": 40,
          "failed": true,
          "failureReason": "return code: 1; ..."
        }
      ]
    }
  }
}'''

  yield api.test(
      'all-failed',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          ALL_FAILED_RESPONSE),
      api.post_check(post_process.DoesNotRun, 'upload artifacts.gsutil rsync'),
      api.post_check(post_process.StepFailure,
                     'upload artifacts.call artifacts service'),
      api.post_check(post_process.StepTextEquals,
                     'upload artifacts.call artifacts service',
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.post_check(post_process.ResultReason,
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'some-failed-skip-publish',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          SOME_FAILED_RESPONSE),
      api.post_check(post_process.MustRun, 'upload artifacts.gsutil rsync'),
      api.post_check(post_process.StepFailure,
                     'upload artifacts.call artifacts service'),
      api.post_check(post_process.StepTextEquals,
                     'upload artifacts.call artifacts service',
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.post_check(post_process.ResultReason,
                     'Failed to generate: SIMPLE_CHROME_SYSROOT'),
      api.properties(**{
          '$chromeos/cros_artifacts':
              CrosArtifactsProperties(skip_publish=True),
      }),
      api.post_check(post_process.MustRun,
                     'upload artifacts.skip publish artifacts'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
