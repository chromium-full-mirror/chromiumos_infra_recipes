# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Examples for get_latest_pin_value."""

from typing import List

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi

from PB.recipe_modules.chromeos.gobin.examples.get_latest_pin_value import GetLatestPinValueProperties
from RECIPE_MODULES.chromeos.gobin.api import SUPPORTED_PACKAGES

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'gobin',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = GetLatestPinValueProperties


def RunSteps(api: RecipeApi, properties: GetLatestPinValueProperties):
  api.assertions.assertEqual(
      api.gobin.get_latest_pin_value('deadbeef'), properties.expected_pin_value)


def GenTests(api):

  CIPD_JSON = '''{
    "result": [
        {
            "package": "chromiumos/infra/%s/linux-amd64",
            "instance_id": "%s"
        }
    ]
}
'''

  def cipd_lookup_step_data(sha: str, package: str, instance_id: str,
                            step_prefix=''):
    step_name = f'find cipd instance for {package} for infra/infra commit {sha}.read [CLEANUP]/cipd.json'
    if step_prefix:
      step_name = f'{step_prefix}.{step_name}'

    return api.step_data(step_name,
                         api.file.read_text(CIPD_JSON % (package, instance_id)))

  def cipd_lookup_step_datas(sha: str, packages: List[str], instance_id: str,
                             step_prefix=''):
    return [
        cipd_lookup_step_data(sha, package, package + instance_id, step_prefix)
        for package in packages
        if package != 'my_gobin'
    ]

  yield api.test(
      'basic',
      api.properties(
          expected_pin_value='abcd2',
      ),
      api.step_data(
          'get commits since deadbeef', stdout=api.raw_io.output_text('\n'.join(
              ['abcd1', 'abcd2', 'deadbeef']))),
      # Missing a package.
      *cipd_lookup_step_datas('abcd1', SUPPORTED_PACKAGES[:-1], '123'),
      api.step_data(
          f'find cipd instance for {SUPPORTED_PACKAGES[-1]} for infra/infra commit abcd1.read [CLEANUP]/cipd.json',
          api.file.read_text('{"result":[]}')),
      *cipd_lookup_step_datas('abcd2', SUPPORTED_PACKAGES, '123'),
      # A package needs to have a different instance id between deadbeef and
      # abcd2 to update the pin. Once a different instance id is found the pin
      # is considered different, so only mock one call.
      cipd_lookup_step_datas(
          'deadbeef', SUPPORTED_PACKAGES, 'xyz',
          'check changed instances between deadbeef and abcd2')[0],
      api.post_process(
          post_process.StepTextEquals,
          'check changed instances between deadbeef and abcd2',
          r'instance ids have changed in package chromiumos/infra/branch_util/${platform}: branch_utilxyz -> branch_util123',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-changed-instances',
      api.properties(
          expected_pin_value='deadbeef',
      ),
      api.step_data(
          'get commits since deadbeef', stdout=api.raw_io.output_text('\n'.join(
              ['abcd1', 'abcd2', 'deadbeef']))),
      # No packages have changed instance id between deadbeef and abcd1. This
      # also implies nothing has changed between deadbeef and abcd2 (since it
      # is between deadbeef and abcd2), so it doesn't need to be checked.
      *cipd_lookup_step_datas('abcd1', SUPPORTED_PACKAGES, '123'),
      *cipd_lookup_step_datas(
          'deadbeef', SUPPORTED_PACKAGES, '123',
          'check changed instances between deadbeef and abcd1'),
      api.post_process(post_process.StepTextEquals,
                       'check changed instances between deadbeef and abcd1',
                       'no changes'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'fallback-to-current-pin',
      api.properties(
          expected_pin_value='deadbeef',
      ),
      api.step_data(
          'get commits since deadbeef',
          stdout=api.raw_io.output_text('\n'.join(['abcd1', 'deadbeef']))),
      # Missing a package.
      *cipd_lookup_step_datas('abcd1', SUPPORTED_PACKAGES[:-1], '123'),
      api.step_data(
          f'find cipd instance for {SUPPORTED_PACKAGES[-1]} for infra/infra commit abcd1.read [CLEANUP]/cipd.json',
          api.file.read_text('{"result":[]}')),
      api.post_process(post_process.DropExpectation),
  )
