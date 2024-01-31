# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for publish_signed_build_metadata."""
from google.protobuf.json_format import MessageToDict

from PB.chromiumos import build_report as build_report_pb2
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.common import CHANNEL_CANARY, CHANNEL_DEV
from PB.recipe_modules.chromeos.signing.signing import SigningProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'build_reporting',
]


PASSED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED
FAILED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_FAILED


def RunSteps(api):
  # Basic build setup
  api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                     'build_target')
  api.build_reporting.publish_status(BuildReport.BuildStatus.RUNNING)

  signing_results = [
      BuildReport.SignedBuildMetadata(
          release_directory='/archive_dir/',
          status=FAILED,
          board='kukui',
          channel=CHANNEL_DEV,
          keyset='devkeys',
          files=[
              BuildReport.SignedBuildMetadata.FileWithHashes(
                  filename='foo.bin', size=123),
              BuildReport.SignedBuildMetadata.FileWithHashes(
                  filename='bad-artifact', size=456)
          ],
      ),
      BuildReport.SignedBuildMetadata(
          release_directory='/archive_dir/',
          status=PASSED,
          board='kukui',
          channel=CHANNEL_CANARY,
          keyset='devkeys',
          files=[
              BuildReport.SignedBuildMetadata.FileWithHashes(
                  filename='bar.bin', size=789)
          ],
      )
  ]

  api.build_reporting.publish_signed_build_metadata(signing_results)


def GenTests(api):
  yield api.test(
      'publish-signed-build-metadata-local-signing',
      api.properties(**{
          '$chromeos/signing':
              MessageToDict(SigningProperties(local_signing=True))
      }),
      # Successful signing result.
      api.post_check(post_process.LogContains, 'build status pubsub update (2)',
                     'message', ['CHANNEL_CANARY']),
      # Failed signing result.
      api.post_check(post_process.LogDoesNotContain,
                     'build status pubsub update (2)', 'message',
                     ['CHANNEL_DEV']),
      api.post_process(post_process.DropExpectation),
  )
