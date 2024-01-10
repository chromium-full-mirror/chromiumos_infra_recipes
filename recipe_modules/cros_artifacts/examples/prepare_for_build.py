# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import sysroot as sysroot_pb
from PB.chromite.api.artifacts import BuildSetupResponse
from PB.chromiumos import common
from PB.recipe_modules.chromeos.cros_artifacts.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_artifacts',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  target = common.BuildTarget()
  target.name = 'target'

  chroot = common.Chroot(path='/path/to/chroot')
  sysroot = sysroot_pb.Sysroot(path='/build/board', build_target=target)
  # Short names to keep line lengths reasonable.
  Legacy = common.ArtifactsByService.Legacy
  Toolchain = common.ArtifactsByService.Toolchain

  # An artifact with a prepare service.  This should return
  # |properties.relevance|.
  resp = api.cros_artifacts.prepare_for_build(
      chroot=chroot, sysroot=sysroot, artifacts_info=common.ArtifactsByService(
          toolchain=Toolchain(
              input_artifacts=[
                  Toolchain.ArtifactInfo(
                      artifact_types=['UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE'],
                      gs_locations=[
                          'chromeos-toolchain-artifacts/afdo/unvetted'
                      ]),
                  Toolchain.ArtifactInfo(
                      artifact_types=['VERIFIED_CHROME_BENCHMARK_AFDO_FILE'],
                      gs_locations=['chromeos-toolchain-artifacts/afdo/vetted'])
              ], output_artifacts=[
                  Toolchain.ArtifactInfo(
                      artifact_types=['VERIFIED_CHROME_BENCHMARK_AFDO_FILE'],
                      gs_locations=['chromeos-toolchain-artifacts/afdo/vetted'])
              ]),
      ), test_data=properties.api_response)
  api.assertions.assertEqual(properties.relevance, resp)

  resp = api.cros_artifacts.prepare_for_build(
      chroot=chroot, sysroot=sysroot, artifacts_info=common.ArtifactsByService(
          toolchain=Toolchain(
              input_artifacts=[
                  Toolchain.ArtifactInfo(
                      artifact_types=['UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE'],
                      gs_locations=[
                          'chromeos-toolchain-artifacts/afdo/unvetted'
                      ]),
                  Toolchain.ArtifactInfo(
                      artifact_types=['VERIFIED_CHROME_BENCHMARK_AFDO_FILE'],
                      gs_locations=['chromeos-toolchain-artifacts/afdo/vetted'])
              ], output_artifacts=[
                  Toolchain.ArtifactInfo(
                      artifact_types=['VERIFIED_CHROME_BENCHMARK_AFDO_FILE'],
                      gs_locations=['chromeos-toolchain-artifacts/afdo/vetted'])
              ]),
          legacy=Legacy(output_artifacts=[
              Legacy.ArtifactInfo(artifact_types=['IMAGE_ZIP'])
          ]),
      ), test_data=properties.api_response)
  api.assertions.assertEqual(properties.relevance, resp)

  resp = api.cros_artifacts.prepare_for_build(
      chroot=chroot, sysroot=sysroot, artifacts_info=common.ArtifactsByService(
          toolchain=Toolchain(
              input_artifacts=[
                  Toolchain.ArtifactInfo(
                      artifact_types=['VERIFIED_KERNEL_CWP_AFDO_FILE'],
                      gs_locations=[
                          'chromeos-prebuilt/afdo-job/cwp/kernel/amd64/5.15'
                      ]),
              ], output_artifacts=[]),
      ), test_data=properties.api_response)
  api.assertions.assertEqual(properties.kernel_afdo_relevance, resp)

  # API Version 1.0.0 has more logic in the module.
  if not api.cros_build_api.has_endpoint(api.cros_build_api.ArtifactsService,
                                         'BuildSetup'):
    # An artifact with only EBUILD_LOGS, should always return UNKNOWN.
    resp = api.cros_artifacts.prepare_for_build(
        chroot=chroot, sysroot=sysroot,
        artifacts_info=common.ArtifactsByService(
            legacy=Legacy(output_artifacts=[
                Legacy.ArtifactInfo(artifact_types=['EBUILD_LOGS'])
            ])), test_data=properties.api_response)
    api.assertions.assertEqual(BuildSetupResponse.UNKNOWN, resp)

    # An artifact with no prepare service, should always return UNKNOWN
    resp = api.cros_artifacts.prepare_for_build(
        chroot=chroot, sysroot=sysroot,
        artifacts_info=common.ArtifactsByService(
            legacy=Legacy(output_artifacts=[
                Legacy.ArtifactInfo(artifact_types=['IMAGE_ZIP'])
            ])), test_data=properties.api_response)
    api.assertions.assertEqual(BuildSetupResponse.UNKNOWN, resp)

    # With no output artifacts, expect UNKNOWN.
    resp = api.cros_artifacts.prepare_for_build(
        chroot=chroot, sysroot=sysroot,
        artifacts_info=common.ArtifactsByService(),
        test_data=properties.api_response)
    api.assertions.assertEqual(BuildSetupResponse.UNKNOWN, resp)


def GenTests(api):
  api.cros_build_api.remove_endpoints(['ArtifactsService/BuildSetup'])
  yield api.test(
      'testing_pointless',
      api.properties(
          TestInputProperties(
              relevance=BuildSetupResponse.POINTLESS,
              kernel_afdo_relevance=BuildSetupResponse.POINTLESS,
          )), api.cros_artifacts.set_prepare_pointless(True))

  for state in 'no-setup', 'default':
    for resp in 'UNKNOWN', 'POINTLESS', 'NEEDED':
      yield api.test(
          '%s_%s' % (resp.lower(), state),
          api.properties(
              TestInputProperties(
                  api_response='{"build_relevance": "%s"}' % resp,
                  relevance=BuildSetupResponse.BuildRelevance.Value(resp),
                  kernel_afdo_relevance=(
                      BuildSetupResponse.UNKNOWN if state == 'no-setup' else
                      BuildSetupResponse.BuildRelevance.Value(resp)),
              )),
          api.cros_build_api.remove_endpoints(
              ['ArtifactsService/BuildSetup'] if state == 'no-setup' else []))
