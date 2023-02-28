# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

CHANGE_NUM = 12345
GERRIT_HOST = 'gerrit.host.test'

PROPERTIES = {
    'expected': Property(default=None),
    'simulated_response_from_server': Property(default=None),
}


def RunSteps(api, expected, simulated_response_from_server):
  api.assertions.assertEqual(
      expected,
      api.gerrit.get_change_topic(CHANGE_NUM, GERRIT_HOST,
                                  simulated_response_from_server))


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(expected="TOPIC",
                     simulated_response_from_server='"TOPIC"'))

  yield api.test(
      'basic-with-prefix',
      api.properties(expected="TOPIC",
                     simulated_response_from_server=')]}\'"TOPIC"'))

  yield api.test('not-string',
                 api.properties(simulated_response_from_server='{}'))

  yield api.test(
      'invalid-json',
      api.properties(expected="TOPIC",
                     simulated_response_from_server='INVALIDJSON)]}'))

  yield api.test('simulated_topic method', api.properties(expected="TOPIC"),
                 api.gerrit.simulated_topic("TOPIC", GERRIT_HOST, CHANGE_NUM))
