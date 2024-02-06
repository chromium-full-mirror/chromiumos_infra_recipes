# -*- coding: utf-8 -*-

# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the drop_cpu_cores function."""

from PB.recipe_modules.chromeos.bot_scaling.examples.drop_cpus import BotDropProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'bot_scaling',
]


PROPERTIES = BotDropProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(8, api.bot_scaling.get_num_cores())

  api.bot_scaling.drop_cpu_cores(min_cpus_left=properties.min_cpus_left,
                                 max_drop_ratio=properties.max_drop_ratio,
                                 test_rand=properties.test_rand)


def GenTests(api):
  yield api.test(
      'basic', api.buildbucket.ci_build(bucket='staging'),
      api.properties(
          BotDropProperties(min_cpus_left=4, max_drop_ratio=0.75,
                            test_rand=0.50)),
      api.post_check(post_process.MustRun, 'dropping cores.drop 4 cpu cores'))

  yield api.test(
      'basic-drop-6', api.buildbucket.ci_build(bucket='staging'),
      api.properties(
          BotDropProperties(min_cpus_left=1, max_drop_ratio=0.75,
                            test_rand=0.25)),
      api.post_check(post_process.MustRun, 'dropping cores.drop 2 cpu cores'))

  yield api.test(
      'basic-drop-0', api.buildbucket.ci_build(bucket='staging'),
      api.properties(
          BotDropProperties(min_cpus_left=1, max_drop_ratio=0.75,
                            test_rand=0.00)),
      api.post_check(post_process.DoesNotRunRE, 'dropping cores.drop.*'))

  yield api.test(
      'basic-drop-all-but-one', api.buildbucket.ci_build(bucket='staging'),
      api.properties(
          BotDropProperties(min_cpus_left=1, max_drop_ratio=0.75,
                            test_rand=1.00)),
      api.post_check(post_process.MustRun, 'dropping cores.drop 7 cpu cores'),
      api.post_check(post_process.DoesNotRunRE, 'dropping cores.drop 8.*'))

  yield api.test(
      'already-offline', api.buildbucket.ci_build(bucket='staging'),
      api.properties(
          BotDropProperties(min_cpus_left=4, max_drop_ratio=0.75,
                            test_rand=0.50)),
      api.step_data('dropping cores.ensure all cpus online',
                    stdout=api.raw_io.output('not null')),
      api.post_check(post_process.DoesNotRunRE, 'dropping cores.drop.*'))

  yield api.test(
      'no-drop-in-prod',
      api.buildbucket.ci_build(),
      api.properties(
          BotDropProperties(min_cpus_left=4, max_drop_ratio=0.75,
                            test_rand=0.50)),
      api.post_check(post_process.DoesNotRun, 'dropping cores'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-drop-legacy-led',
      api.buildbucket.ci_build(),
      api.properties(
          BotDropProperties(min_cpus_left=4, max_drop_ratio=0.75,
                            test_rand=0.50)),
      api.properties(**{'$recipe_engine/led': {
          'run_id': 'abc123',
      }}),
      api.post_check(post_process.DoesNotRun, 'dropping cores'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-drop-real-build-led',
      api.buildbucket.ci_build(),
      api.properties(
          BotDropProperties(min_cpus_left=4, max_drop_ratio=0.75,
                            test_rand=0.50)),
      api.properties(**{'$recipe_engine/led': {
          'shadowed_bucket': 'staging',
      }}),
      api.post_check(post_process.DoesNotRun, 'dropping cores'),
      api.post_process(post_process.DropExpectation),
  )
