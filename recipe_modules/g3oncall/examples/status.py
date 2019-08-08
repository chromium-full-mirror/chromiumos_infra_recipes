# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.g3oncall.examples.status import StatusProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'g3oncall',
]

PROPERTIES = StatusProperties


def RunSteps(api, properties):
  rotation = 'chromeos-ci-eng'
  status = api.g3oncall.status(rotation, step_name=properties.step_name)
  api.assertions.assertEqual(status.primary, properties.expected.primary)
  api.assertions.assertEqual(status.secondary, properties.expected.secondary)


def GenTests(api):
  step_name = 'status'
  primary = 'sidious'
  secondary = 'vader'
  yield (api.test('basic') + api.g3oncall.status(
      step_name, primary=primary, secondary=secondary) + api.properties(
          step_name=step_name,
          expected=StatusProperties.Expected(
              primary=primary,
              secondary=secondary,
          ),
      ))

  yield (api.test('non-list-json') +
         api.properties(step_name=step_name) + api.g3oncall.status_json(
             step_name, {'person': 'foo'}) + api.expect_exception('ValueError'))

  yield (api.test('deficient-list-json') + api.properties(step_name=step_name) +
         api.g3oncall.status_json(step_name, [{
             'person': 'foo'
         }]) + api.expect_exception('ValueError'))

  yield (api.test('missing-username-json') + api.properties(step_name=step_name)
         + api.g3oncall.status_json(step_name, [{
             'next': 'foo'
         }, {
             'next': 'bar'
         }]) + api.expect_exception('ValueError'))
