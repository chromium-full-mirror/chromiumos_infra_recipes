# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that executes ChromeOS EC hardware tests on Dagwood test fixtures."""

from PB.recipes.chromeos.test_dagwood_firmware import TestDagwoodFirmwareProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/resultdb',
    'recipe_engine/step',
]

PROPERTIES = TestDagwoodFirmwareProperties


def RunSteps(api: RecipeApi, properties: TestDagwoodFirmwareProperties):
  with api.step.nest('dagwood hardware test') as pres:
    cmd = [
        'vpython3',
        api.resource('runner.py'),
    ]
    platforms = list(properties.platform) or ['realtek/rts5912']
    for p in platforms:
      cmd.extend(['--platform', p])

    for tp in properties.test_path:
      cmd.extend(['--test-path', tp])

    for ts in properties.test_scenario:
      cmd.extend(['--test-scenario', ts])

    for arg in properties.extra_args:
      cmd.append(f'--extra-args={arg}')

    cmd.extend(['--output-json', api.json.output()])

    base_variant = {'build_target': ','.join(platforms)}
    if api.resultdb.enabled:
      cmd = api.resultdb.wrap(cmd, base_variant=base_variant)

    try:
      step_res = api.step(
          'execute tests',
          cmd,
          step_test_data=lambda: api.json.test_api.output({
              'passed': 12,
              'failed': 0,
              'skipped': 0,
              'total': 12,
              'exit_code': 0,
          }),
      )
      summary = step_res.json.output or {}
      pres.step_text = (f"Passed: {summary.get('passed', 0)}, "
                        f"Failed: {summary.get('failed', 0)}, "
                        f"Skipped: {summary.get('skipped', 0)} "
                        f"(Total: {summary.get('total', 0)})")
      if api.buildbucket.build.id:
        b_id = api.buildbucket.build.id
        pres.links['Milo Test Results (All)'] = (
            f"https://ci.chromium.org/ui/b/{b_id}/test-results?q=ExactID%3A*")
    except StepFailure as e:
      pres.status = api.step.FAILURE
      pres.step_text = f"Dagwood test run failed: {e}"
      raise


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(
          TestDagwoodFirmwareProperties(
              platform=['realtek/rts5912'],
              test_path=['zephyr/test/ec-aic'],
              test_scenario=['aic.i2c'],
              extra_args=['--sram'],
          )),
      api.buildbucket.ci_build(project='chromeos', bucket='firmware',
                               builder='ec-dagwood-nightly'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'default_options',
      api.properties(TestDagwoodFirmwareProperties()),
      api.buildbucket.ci_build(project='chromeos', bucket='firmware',
                               builder='ec-dagwood-nightly'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'test_failure',
      api.properties(
          TestDagwoodFirmwareProperties(
              platform=['realtek/rts5912'],
              test_path=['zephyr/test/ec-aic'],
              test_scenario=['aic.i2c'],
          )),
      api.buildbucket.ci_build(project='chromeos', bucket='firmware',
                               builder='ec-dagwood-nightly'),
      api.step_data(
          'dagwood hardware test.execute tests',
          api.json.output({
              'passed': 10,
              'failed': 2,
              'skipped': 0,
              'total': 12,
              'exit_code': 1,
          }),
          retcode=1,
      ),
      api.post_process(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
