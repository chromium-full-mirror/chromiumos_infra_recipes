# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.builder_config import BuilderConfig
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
]



def RunSteps(api):
  api.assertions.assertFalse(
      api.cros_infra_config.should_run(BuilderConfig.NO_RUN))
  api.assertions.assertTrue(api.cros_infra_config.should_run(BuilderConfig.RUN))
  api.assertions.assertTrue(
      api.cros_infra_config.should_run(BuilderConfig.RUN_EXIT))
  api.assertions.assertTrue(
      api.cros_infra_config.should_run(BuilderConfig.RUN_SPEC_UNSPECIFIED,
                                       True))
  api.assertions.assertFalse(
      api.cros_infra_config.should_run(BuilderConfig.RUN_SPEC_UNSPECIFIED,
                                       False))

  api.assertions.assertFalse(
      api.cros_infra_config.should_exit(BuilderConfig.NO_RUN))
  api.assertions.assertFalse(
      api.cros_infra_config.should_exit(BuilderConfig.RUN))
  api.assertions.assertTrue(
      api.cros_infra_config.should_exit(BuilderConfig.RUN_EXIT))


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
