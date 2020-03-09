# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
    'sysroot_util',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import PrepareForBuildResponse
from PB.chromiumos.common import PrepareForBuildAdditionalArgs


def RunSteps(api):
  build_config = api.cros_infra_config.get_builder_config(
      'orderfile-generate-toolchain')

  artifacts = build_config.artifacts
  args = build_config.build.prepare_for_build.additional_args

  api.sysroot_util.update_for_artifact_build(artifacts, args)
  resp = api.sysroot_util.update_for_artifact_build(
      artifacts, args, force_relevance=True)
  api.assertions.assertEqual(resp, PrepareForBuildResponse.NEEDED)


def GenTests(api):
  yield api.test('basic')
