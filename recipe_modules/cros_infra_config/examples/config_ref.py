# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_infra_config',
]



def RunSteps(api):
  props = api.cros_infra_config.props_for_child_build
  # Log what we got.
  with api.step.nest('props') as step:
    step.step_text = json.dumps(props)
  # Make sure we got what we expected.
  api.assertions.assertEqual(
      api.properties.get('$chromeos/cros_infra_config'),
      props.get('$chromeos/cros_infra_config'))


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'properties-given',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      config_ref='refs/changes/33/123433/1')
          }))
