# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_sdk',
    'sysroot_util',
]

from PB.chromite.api.artifacts import PrepareForBuildResponse
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.sysroot_util.tests.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  name = properties.builder_name or 'orderfile-generate-toolchain'
  config = api.cros_infra_config.get_builder_config(name)

  chroot = api.cros_sdk.chroot if properties.with_chroot else None
  relevance = api.sysroot_util.update_for_artifact_build(
      chroot, config.artifacts, config.build.prepare_for_build.additional_args,
      force_relevance=properties.force_build_relevance)
  api.assertions.assertEqual(relevance, properties.expected_relevance)


def GenTests(api):
  for name, value in PrepareForBuildResponse.BuildRelevance.items():
    # Skip UNSPECIFIED.
    if not value:
      continue
    for with_chroot in (False, True):
      for force in (False, True):
        test_name = 'with%s-chroot_force=%s_%s' % ('' if with_chroot else 'out',
                                                   force, name.title())
        yield api.test(
            test_name,
            api.properties(
                with_chroot=with_chroot, force_build_relevance=force,
                expected_relevance=PrepareForBuildResponse.NEEDED
                if force else value),
            api.step_data(
                'prepare artifacts.call chromite.api.ToolchainService/'
                'PrepareForBuild.read output file',
                api.file.read_raw(content='{"build_relevance": "%s"}' % name)),
        )
