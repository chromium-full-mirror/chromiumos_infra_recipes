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

  def cipd_lookup_step_data(sha: str, package: str, instance_id: str):
    return api.step_data(
        f'find cipd instance for {package} for infra/infra commit {sha}.read [CLEANUP]/cipd.json',
        api.file.read_text(CIPD_JSON % (package, instance_id)))

  def cipd_lookup_step_datas(sha: str, packages: List[str], instance_id: str):
    return [
        cipd_lookup_step_data(sha, package, package + instance_id)
        for package in packages
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
