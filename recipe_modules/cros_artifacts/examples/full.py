# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_artifacts',
    'cros_build_api',
]

from PB.chromite.api import sysroot

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

  artifacts_info = common.ArtifactsByService(
      legacy=common.ArtifactsByService.Legacy(output_artifacts=[
          common.ArtifactsByService.Legacy.ArtifactInfo(
              artifact_types=[common.ArtifactsByService.Legacy.EBUILD_LOGS])
      ]), toolchain=common.ArtifactsByService.Toolchain(output_artifacts=[
          common.ArtifactsByService.Toolchain.ArtifactInfo(
              artifact_types=[
                  common.ArtifactsByService.Toolchain
                  .UNVERIFIED_CHROME_LLVM_ORDERFILE
              ], gs_locations=['publish_gs_location', 'pub2/%(gs_path)s'],
              acl_name='public-read')
      ]))

  # This verifies that we can upload artifacts, some of which get an acl
  # applied.  Legacy and Toolchain artifacts get us coverage of both paths in
  # the API 1.0.0 case.
  api.cros_artifacts.upload_artifacts(
      'target-toolchain',
      target,
      BuilderConfig.Id.TOOLCHAIN,
      'artifacts_gs_bucket',
      artifacts_info=artifacts_info,
      chroot=common.Chroot(path='/path/to/chroot'),
      sysroot=sysroot.Sysroot(path='/build/board',
                              build_target=common.BuildTarget(name='board')),
  )


def GenTests(api):
  yield api.test('basic')

  yield api.test('api-1.0.0',
                 api.properties(TestInputProperties(build_api_version='1.0.0')))
