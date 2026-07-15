# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_release',
]


def RunSteps(api):
  api.assertions.assertIsNone(
      api.cros_release.buildspec_snapshot_gitiles_commit)
  api.cros_release.set_resultdb_gitiles_commit(
      'https://chrome-internal.googlesource.com/chromeos/manifest-internal',
      'chrome-internal.googlesource.com',
      'chromeos/manifest-internal',
      'release-R108-15183.B-snapshot',
      100,
  )
  api.assertions.assertEqual(
      api.cros_release.buildspec_snapshot_gitiles_commit.host,
      'chrome-internal.googlesource.com')
  api.cros_release.check_buildspec(fatal=api.properties['fatal'])




def GenTests(api):

  def build_result(bbid, buildspec, original_build_bbid=None):
    build = build_pb2.Build(id=bbid)
    build.input.properties['$chromeos/cros_source'] = {
        'syncToManifest': {
            'manifestGsPath': buildspec,
        }
    }
    if original_build_bbid:
      build.input.properties['$chromeos/checkpoint'] = {
          'original_build_bbid': original_build_bbid
      }

    return build

  yield api.test(
      'success',
      api.properties(
          fatal=True, **{
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
                  },
              },
          }),
      api.buildbucket.simulated_search_results(
          [
              # This is the current build so it should be ignored.
              build_result(
                  0,
                  'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml'
              ),
              build_result(
                  123,
                  'gs://chromeos-manifest-versions/buildspecs/114/15408.0.0.xml'
              ),
              build_result(
                  124,
                  'gs://chromeos-manifest-versions/buildspecs/114/15407.0.0.xml'
              ),
          ],
          step_name='check buildspec.check for previous builds.buildbucket.search'
      ),
      api.post_check(post_process.StepSuccess, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-buildspec',
      api.properties(fatal=True),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # `fatal` shouldn't affect the no buildspec failure.
  yield api.test(
      'no-buildspec-nonfatal',
      api.properties(fatal=False),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'build-exists',
      api.properties(
          fatal=True, **{
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
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
      status='FAILURE',
  )

  yield api.test(
      'build-exists-nonfatal',
      api.properties(
          fatal=False, **{
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
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

  yield api.test(
      'retry-success',
      api.properties(
          # `fatal` doesn't matter for retry detection as we're trying to
          # prevent out of band retries.
          fatal=False,
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '123',
              },
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
                  },
              },
          }),
      api.buildbucket.simulated_search_results(
          [
              build_result(
                  123,
                  'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
              ),
              # This is the current build so it should be ignored.
              build_result(
                  0,
                  'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
                  original_build_bbid='123'),
          ],
          step_name='check buildspec.check for previous retries.buildbucket.search'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'retry-fail',
      api.properties(
          # `fatal` doesn't matter for retry detection as we're trying to
          # prevent out of band retries.
          fatal=False,
          **{
              '$chromeos/checkpoint': {
                  'retry': True,
                  'original_build_bbid': '123',
              },
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
                  },
              },
          }),
      api.buildbucket.simulated_search_results(
          [
              build_result(
                  123,
                  'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
              ),
              build_result(
                  124,
                  'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
                  original_build_bbid='123'),
              # This is the current build so it should be ignored.
              build_result(
                  0,
                  'gs://chromeos-manifest-versions/buildspecs/114/15406.0.0.xml',
                  original_build_bbid='123'),
          ],
          step_name='check buildspec.check for previous retries.buildbucket.search'
      ),
      api.post_check(post_process.StepFailure, 'check buildspec'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
