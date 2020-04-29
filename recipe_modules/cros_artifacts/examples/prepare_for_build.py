# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_artifacts',
]

from PB.chromite.api import sysroot
from PB.chromite.api.artifacts import PrepareForBuildResponse

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig

from PB.recipe_modules.chromeos.cros_artifacts.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties

def RunSteps(api, properties):
  target = common.BuildTarget()
  target.name = 'target'

  # An artifact with a prepare service.  This should return
  # |properties.relevance|.
  resp = api.cros_artifacts.prepare_for_build(
      [BuilderConfig.Artifacts.VERIFIED_CHROME_LLVM_ORDERFILE],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      input_artifacts=[BuilderConfig.Artifacts.InputArtifactInfo(
          input_artifact_type=(
              BuilderConfig.Artifacts.UNVERIFIED_CHROME_LLVM_ORDERFILE),
          input_artifact_gs_locations=[
              "chromeos-toolchain-artifacts/orderfile/unvetted"
          ]),
      ],
  )
  api.assertions.assertEqual(properties.relevance, resp)

  # An artifact with only EBUILD_LOGS, should always return POINTLESS.
  resp = api.cros_artifacts.prepare_for_build(
      [BuilderConfig.Artifacts.EBUILD_LOGS],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      input_artifacts=[],
  )
  api.assertions.assertEqual(PrepareForBuildResponse.POINTLESS, resp)

  # An artifact with no prepare service, should always return UNKNOWN
  resp = api.cros_artifacts.prepare_for_build(
      [BuilderConfig.Artifacts.IMAGE_ZIP],
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
      input_artifacts=[],
  )
  api.assertions.assertEqual(PrepareForBuildResponse.UNKNOWN, resp)


def GenTests(api):
  # cros_build_api/test_api returns UNKNOWN.
  yield (api.test('unknown') + #
         api.properties(
             TestInputProperties(relevance=PrepareForBuildResponse.UNKNOWN)))

  yield (api.test('pointless') + #
         api.step_data('prepare artifacts.call chromite.api.ToolchainService/'
                       'PrepareForBuild.read output file',
                       api.file.read_raw(
                           content='{"build_relevance": "POINTLESS"}')) + #
         api.properties(
             TestInputProperties(relevance=PrepareForBuildResponse.POINTLESS)))

  yield (api.test('needed') + #
         api.step_data('prepare artifacts.call chromite.api.ToolchainService/'
                       'PrepareForBuild.read output file',
                       api.file.read_raw(
                           content='{"build_relevance": "NEEDED"}')) + #
         api.properties(
             TestInputProperties(relevance=PrepareForBuildResponse.NEEDED)))
