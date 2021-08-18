# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

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
    step.step_text = str(props)
  # Make sure we got what we expected.
  api.assertions.assertEqual(
      api.properties.get('$chromeos/cros_infra_config'),
      props.get('$chromeos/cros_infra_config'))


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'properties_given',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(
                      config_ref='refs/changes/33/123433/1')
          }))
