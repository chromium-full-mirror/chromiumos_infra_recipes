# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify methods for signing versions."""

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

from PB.chromiumos.build_report import BuildReport
from PB.chromiumos import signing as signing_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'signing_utils',
]



def RunSteps(api: RecipeApi):

  expected_platform_version = BuildReport.SignedBuildMetadata.Version(
      kind=BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_PLATFORM,
      value='1234.56.0')

  expected_milestone_version = BuildReport.SignedBuildMetadata.Version(
      kind=BuildReport.SignedBuildMetadata.VersionKind.VERSION_KIND_MILESTONE,
      value='99')

  expected_keyset_versions = [
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

  platform_version = api.signing_utils.get_platform_version()
  milestone_version = api.signing_utils.get_milestone_version()

  artifact = signing_pb2.ArchiveArtifacts(
      build_target='kukui',
      keyset_versions=signing_pb2.KeysetVersions(
          firmware_key_version=11,
          firmware_version=22,
          kernel_key_version=33,
          kernel_version=44,
      ),
  )
  keyset_versions = api.signing_utils.get_keyset_version_list(artifact)

  api.assertions.assertEqual(platform_version, expected_platform_version)
  api.assertions.assertEqual(milestone_version, expected_milestone_version)
  api.assertions.assertEqual(keyset_versions, expected_keyset_versions)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'versions',
      api.post_process(post_process.DropExpectation),
  )
