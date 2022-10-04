# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.builder_config import BuilderConfig

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  api.assertions.assertFalse(
      api.cros_infra_config.should_run(BuilderConfig.NO_RUN))
  api.assertions.assertTrue(api.cros_infra_config.should_run(BuilderConfig.RUN))
  api.assertions.assertTrue(
      api.cros_infra_config.should_run(BuilderConfig.RUN_EXIT))

  api.assertions.assertFalse(
      api.cros_infra_config.should_exit(BuilderConfig.NO_RUN))
  api.assertions.assertFalse(
      api.cros_infra_config.should_exit(BuilderConfig.RUN))
  api.assertions.assertTrue(
      api.cros_infra_config.should_exit(BuilderConfig.RUN_EXIT))


def GenTests(api):
  yield api.test('basic')
