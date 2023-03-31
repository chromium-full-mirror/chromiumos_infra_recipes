# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from recipe_engine.recipe_api import Property

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_release',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'fatal':
        Property(
            kind=bool,
            help='Whether the check_buildspec error should be fatal.',
            default=False,
        ),
}


def RunSteps(api, fatal):
  api.cros_release.check_buildspec(fatal=fatal)


def GenTests(api):

  def build_result(bbid, buildspec):
    build = build_pb2.Build(id=bbid)
    build.input.properties['$chromeos/cros_source'] = {
        'syncToManifest': {
            'manifestGsPath': buildspec,
        }
    }
    return build

  yield api.test(
      'success',
      api.properties(
          fatal=True, **{
              '$chromeos/cros_source': {
                  "syncToManifest": {
                      "manifestGsPath":
                          "gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml",
                  },
              },
          }),
      api.buildbucket.simulated_search_results([
          build_result(
              123,
              'gs://chromeos-manifest-versions/buildspecs/114/15408.0.0.xml'),
          build_result(
              124,
              'gs://chromeos-manifest-versions/buildspecs/114/15407.0.0.xml'),
      ], step_name='check buildspec.check for previous builds.buildbucket.search'
                                              ),
      api.post_check(post_process.StepSuccess, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-buildspec',
      api.properties(fatal=True),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  # `fatal` shouldn't affect the no buildspec failure.
  yield api.test(
      'no-buildspec-nonfatal',
      api.properties(fatal=False),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      'build-exists',
      api.properties(
          fatal=True, **{
              '$chromeos/cros_source': {
                  "syncToManifest": {
                      "manifestGsPath":
                          "gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml",
                  },
              },
          }),
      api.buildbucket.simulated_search_results([
          build_result(
              123,
              'gs://chromeos-manifest-versions/buildspecs/114/15408.0.0.xml'),
          build_result(
              124,
              'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml'),
      ], step_name='check buildspec.check for previous builds.buildbucket.search'
                                              ),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
      status="FAILURE",
  )

  yield api.test(
      'build-exists-nonfatal',
      api.properties(
          fatal=False, **{
              '$chromeos/cros_source': {
                  "syncToManifest": {
                      "manifestGsPath":
                          "gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml",
                  },
              },
          }),
      api.buildbucket.simulated_search_results([
          build_result(
              123,
              'gs://chromeos-manifest-versions/buildspecs/114/15408.0.0.xml'),
          build_result(
              124,
              'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml'),
      ], step_name='check buildspec.check for previous builds.buildbucket.search'
                                              ),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
  )
