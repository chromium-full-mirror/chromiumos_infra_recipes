# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.build_report import BuildReport
from recipe_engine import post_process

DEPS = [
    'build_reporting',
]



def RunSteps(api):
  # Basic build setup
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     'build_target')

  # DLC GS locations with hashes.
  api.build_reporting.publish_dlc_artifacts({
      'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/libsoda/package/dlc.img':
          {
              'hash': 'deadbeef',
              'id': 'libsoda'
          },
      'gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/handwriting-es/package/dlc.img':
          {
              'hash': 'beefdead',
              'id': 'handwriting-es'
          }
  })


def GenTests(api):
  yield api.test(
      'publish-dlcs',
      api.post_check(post_process.LogContains, 'build status pubsub update',
                     'message', ['dlcArtifactDetails']),
      api.post_check(
          post_process.LogContains, 'build status pubsub update', 'message', [
              '"gcs": "gs://chromeos-image-archive/brya-release/R108-15132.0.0/dlc/libsoda/package/dlc.img"'
          ]),
      api.post_check(post_process.LogContains, 'build status pubsub update',
                     'message', ['"sha256\": \"deadbeef\"']),
      api.post_process(post_process.DropExpectation))
