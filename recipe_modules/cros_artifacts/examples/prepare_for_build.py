# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_artifacts',
    'cros_build_api',
]

from PB.chromite.api import sysroot as sysroot_pb
from PB.chromite.api.artifacts import PrepareForBuildResponse

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig

from PB.recipe_modules.chromeos.cros_artifacts.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  target = common.BuildTarget()
  target.name = 'target'

  # This should not be needed in general, and is used here only to exercise both
  # the 1.1.0 and 1.0.0.artifacts handling paths.
  if properties.build_api_version:
    api.cros_build_api.GetVersion(
        test_data=api.cros_build_api.Version.ParseVersion(
            properties.build_api_version).FormatResponse())

  chroot = common.Chroot(path='/path/to/chroot')
  sysroot = sysroot_pb.Sysroot(path='/build/board', build_target=target)
  # Short names to keep line lengths sane.
  Legacy = common.ArtifactsByService.Legacy
  Toolchain = common.ArtifactsByService.Toolchain

  # An artifact with a prepare service.  This should return
  # |properties.relevance|.
  resp = api.cros_artifacts.prepare_for_build(
      chroot=chroot, sysroot=sysroot, artifacts_info=common.ArtifactsByService(
          toolchain=Toolchain(
              input_artifacts=[
                  Toolchain.ArtifactInfo(
                      artifact_types=['UNVERIFIED_CHROME_LLVM_ORDERFILE'],
                      gs_locations=[
                          'chromeos-toolchain-artifacts/orderfile/unvetted'
                      ]),
                  Toolchain.ArtifactInfo(
                      artifact_types=['VERIFIED_CHROME_LLVM_ORDERFILE'],
                      gs_locations=[
                          'chromeos-toolchain-artifacts/orderfile/vetted'
                      ])
              ], output_artifacts=[
                  Toolchain.ArtifactInfo(
                      artifact_types=['VERIFIED_CHROME_LLVM_ORDERFILE'],
                      gs_locations=[
                          'chromeos-toolchain-artifacts/orderfile/vetted'
                      ])
              ])), test_data=properties.api_response)
  api.assertions.assertEqual(properties.relevance, resp)

  # API Version 1.0.0 has more logic in the module.
  if not api.cros_build_api.is_at_least_version(1, 1, 0):
    # An artifact with only EBUILD_LOGS, should always return POINTLESS.
    resp = api.cros_artifacts.prepare_for_build(
        chroot=chroot, sysroot=sysroot,
        artifacts_info=common.ArtifactsByService(
            legacy=Legacy(output_artifacts=[
                Legacy.ArtifactInfo(artifact_types=['EBUILD_LOGS'])
            ])), test_data=properties.api_response)
    api.assertions.assertEqual(PrepareForBuildResponse.POINTLESS, resp)

    # An artifact with no prepare service, should always return UNKNOWN
    resp = api.cros_artifacts.prepare_for_build(
        chroot=chroot, sysroot=sysroot,
        artifacts_info=common.ArtifactsByService(
            legacy=Legacy(output_artifacts=[
                Legacy.ArtifactInfo(artifact_types=['IMAGE_ZIP'])
            ])), test_data=properties.api_response)
    api.assertions.assertEqual(PrepareForBuildResponse.UNKNOWN, resp)

    # With no output artifacts, expect UNKNOWN.
    resp = api.cros_artifacts.prepare_for_build(
        chroot=chroot, sysroot=sysroot,
        artifacts_info=common.ArtifactsByService(),
        test_data=properties.api_response)
    api.assertions.assertEqual(PrepareForBuildResponse.UNKNOWN, resp)


def GenTests(api):
  for build_api_version in '1.0.0', None:
    for resp in 'UNKNOWN', 'POINTLESS', 'NEEDED':
      yield api.test(
          '%s_%s' % (resp.lower(), build_api_version or 'default'),
          api.properties(
              TestInputProperties(
                  api_response='{"build_relevance": "%s"}' % resp,
                  relevance=PrepareForBuildResponse.BuildRelevance.Value(resp),
                  build_api_version=build_api_version)))
