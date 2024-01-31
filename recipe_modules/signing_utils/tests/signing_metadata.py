# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for signing_response_to_metadata."""

from PB.chromite.api.image import SignImageResponse
from PB.chromiumos import signing as signing_pb2
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.common import CHANNEL_CANARY, CHANNEL_DEV

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'signing_utils',
]


PASSED = BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED
FAILED = BuildReport.SignedBuildMetadata.SIGNING_STATUS_FAILED


def RunSteps(api: RecipeApi):
  signing_response = SignImageResponse(
      output_archive_dir='/archive_dir/',
      signed_artifacts=signing_pb2.BuildTargetSignedArtifacts(
          archive_artifacts=[
              signing_pb2.ArchiveArtifacts(
                  build_target='kukui',
                  channel=CHANNEL_DEV,
                  keyset='devkeys',
                  keyset_is_mp=False,
                  keyset_versions=signing_pb2.KeysetVersions(
                      firmware_key_version=11,
                      firmware_version=22,
                      kernel_key_version=33,
                      kernel_version=44,
                  ),
                  signed_artifacts=[
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='foo.bin',
                      ),
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='bad-artifact',
                      )
                  ],
                  signing_status=FAILED,
              ),
              signing_pb2.ArchiveArtifacts(
                  build_target='kukui',
                  channel=CHANNEL_CANARY,
                  keyset='notdevkeys',
                  keyset_is_mp=True,
                  keyset_versions=signing_pb2.KeysetVersions(
                      firmware_key_version=11,
                      firmware_version=22,
                      kernel_key_version=33,
                      kernel_version=44,
                  ),
                  signed_artifacts=[
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='bar.bin',
                      ),
                  ],
                  signing_status=PASSED,
              ),
              signing_pb2.ArchiveArtifacts(
                  build_target='kukui',
                  # no channel, gets skipped.
                  keyset='devkeys',
                  keyset_is_mp=False,
                  keyset_versions=signing_pb2.KeysetVersions(
                      firmware_key_version=11,
                      firmware_version=22,
                      kernel_key_version=33,
                      kernel_version=44,
                  ),
                  signed_artifacts=[
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='no-channel.bin',
                      ),
                  ],
                  signing_status=PASSED,
              )
          ]))

  metadata = api.signing_utils.signing_response_to_metadata(signing_response)

  expected_versions = [
      BuildReport.SignedBuildMetadata.Version(
          kind=BuildReport.SignedBuildMetadata.VersionKind
          .VERSION_KIND_PLATFORM, value='1234.56.0'),
      BuildReport.SignedBuildMetadata.Version(
          kind=BuildReport.SignedBuildMetadata.VersionKind
          .VERSION_KIND_MILESTONE, value='99'),
      BuildReport.SignedBuildMetadata.Version(
          kind=BuildReport.SignedBuildMetadata.VersionKind
          .VERSION_KIND_KEY_FIRMWARE_KEY, value='11'),
      BuildReport.SignedBuildMetadata.Version(
          kind=BuildReport.SignedBuildMetadata.VersionKind
          .VERSION_KIND_KEY_FIRMWARE, value='22'),
      BuildReport.SignedBuildMetadata.Version(
          kind=BuildReport.SignedBuildMetadata.VersionKind
          .VERSION_KIND_KEY_KERNEL_KEY, value='33'),
      BuildReport.SignedBuildMetadata.Version(
          kind=BuildReport.SignedBuildMetadata.VersionKind
          .VERSION_KIND_KEY_KERNEL, value='44'),
  ]

  expected_metadata = [
      BuildReport.SignedBuildMetadata(
          release_directory='/archive_dir/',
          status=FAILED,
          board='kukui',
          channel=CHANNEL_DEV,
          keyset='devkeys',
          keyset_is_mp=False,
          files=[
              BuildReport.SignedBuildMetadata.FileWithHashes(
                  filename='foo.bin', size=111),
              BuildReport.SignedBuildMetadata.FileWithHashes(
                  filename='bad-artifact', size=111)
          ],
          versions=expected_versions,
      ),
      BuildReport.SignedBuildMetadata(
          release_directory='/archive_dir/',
          status=PASSED,
          board='kukui',
          channel=CHANNEL_CANARY,
          keyset='notdevkeys',
          keyset_is_mp=True,
          files=[
              BuildReport.SignedBuildMetadata.FileWithHashes(
                  filename='bar.bin', size=111)
          ],
          versions=expected_versions,
      )
  ]

  api.assertions.assertEqual(
      len(expected_metadata), len(metadata),
      f'Expected {len(expected_metadata)} elements got {len(metadata)} elements'
  )
  api.assertions.assertEqual(expected_metadata, metadata)


def GenTests(api: RecipeTestApi):
  yield api.build_menu.test(
      'basic',
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='kukui-release-main',
  )
