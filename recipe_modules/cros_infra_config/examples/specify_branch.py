# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
]

from PB.chromiumos.builder_config import BuilderConfig

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)


def RunSteps(api):
  builder_config = api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)
  api.cros_infra_config.force_reload()

  api.assertions.assertEqual(builder_config.id.name, "clang-tidy-toolchain")


def GenTests(api):
  yield api.test(
      'specify_CL',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      config_ref='refs/changes/45/12345/3',
                  )
          }),
      api.buildbucket.ci_build(project='chromeos', bucket='toolchain',
                               builder='clang-tidy-toolchain'))
