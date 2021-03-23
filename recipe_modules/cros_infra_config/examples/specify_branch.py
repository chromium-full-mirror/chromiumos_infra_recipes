# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'test_util',
]

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)


def RunSteps(api):
  builder_config = api.cros_infra_config.config
  api.cros_infra_config.force_reload()

  api.assertions.assertEqual(builder_config.id.name,
                             api.buildbucket.build.builder.builder)


def GenTests(api):

  def _config_step_name(ref, suffix='binaryproto'):
    filename = 'generated/builder_configs.{}'.format(suffix)
    return 'read builder configs.fetch {}:{}'.format(ref, filename)

  config_ref = 'refs/changes/45/12345/3'
  yield api.test(
      'specify_CL',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      config_ref=config_ref,
                  )
          }),
      api.cros_infra_config.override_builder_configs_test_data(
          api.cros_infra_config.builder_configs_test_data, ref=config_ref,
          binaryproto=False),
      api.cros_infra_config.override_builder_configs_test_data(
          api.cros_infra_config.builder_configs_test_data, ref=config_ref,
          iteration=2, binaryproto=False),
      api.test_util.test_child_build(
          'amd64-generic', bucket='staging',
          builder='staging-clang-tidy-toolchain').build,
      api.post_check(post_process.MustRun, _config_step_name(config_ref,
                                                             'cfg')))

  yield api.test(
      'prod-specify_CL',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      config_ref=config_ref,
                  )
          }),
      api.test_util.test_child_build('amd64-generic', bucket='toolchain',
                                     builder='clang-tidy-toolchain').build,
      api.post_check(post_process.MustRun, _config_step_name('HEAD')))
