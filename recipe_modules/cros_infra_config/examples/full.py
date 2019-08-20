# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_infra_config',
]

from PB.chromiumos.builder_config import BuilderConfig


def RunSteps(api):
  builder_config = api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)
  api.cros_infra_config.force_reload()

  api.assertions.assertEqual(builder_config.id.name, "postsubmit-orchestrator")

  # Sanity check that the jsonpb was parsed.
  children = builder_config.orchestrator.children
  api.assertions.assertEqual(len(children), 2)
  api.assertions.assertEqual(children[0], "amd64-generic-postsubmit")
  api.assertions.assertEqual(children[1], "arm-generic-postsubmit")

  api.cros_infra_config.get_test_config('config_name.cfg')

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
  yield api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator')
