# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import CrosInfraConfigProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'test_util',
]



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
      'specify-CL',
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
          builder='staging-generic-toolchain-bot').build,
      api.post_check(post_process.MustRun, _config_step_name(config_ref,
                                                             'cfg')))

  yield api.test(
      'prod-specify-CL',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      config_ref=config_ref,
                  )
          }),
      api.test_util.test_child_build('amd64-generic', bucket='toolchain',
                                     builder='generic-toolchain-bot').build,
      api.post_check(post_process.MustRun, _config_step_name('HEAD')))
