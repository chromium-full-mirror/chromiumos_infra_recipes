#  -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from PB.recipe_modules.chromeos.portage.tests.portage_stats_test import TestMetricsInputProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'portage',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestMetricsInputProperties

_NO_EMERGE_OUTPUT = ''
_BAD_TYPE = '1'
_FOOLED_OUTPUT = '''
[58787/86177] CXX obj/content/browser/browser/push_messaging_context.o
'''


def RunSteps(api, properties):
  result = api.portage.publish_emerge_stats(properties.step_name,
                                            properties.bapi_stdout,
                                            set_output_prop=True,
                                            publish_to_bq=True)
  if properties.expected:
    api.assertions.assertEqual(result, json.loads(properties.expected))


def GenTests(api):
  yield api.test(
      'success-install',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_SUCCESS_INSTALL_PACKAGES,
              expected=api.portage.EXAMPLE_SUCCESS_INSTALL_PACKAGES_EXPECTED)),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'failure-install',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_FAILURE_INSTALL_PACKAGES,
              expected=api.portage.EXAMPLE_FAILURE_INSTALL_PACKAGES_EXPECTED)),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'broken-install',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_BROKEN_INSTALL_PACKAGES)),
      api.post_process(post_process.PropertyEquals, 'failed_portage_stats',
                       True), api.post_check(post_process.StatusSuccess))

  yield api.test(
      'fooled-output',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_FOOLED_OUTPUT)),
      api.post_process(post_process.PropertiesDoNotContain, 'portage_stats'),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'empty-output',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_NO_EMERGE_OUTPUT)),
      api.post_process(post_process.PropertiesDoNotContain, 'portage_stats'),
      api.post_check(post_process.StatusSuccess))

  yield api.test(
      'bad-type',
      api.properties(
          TestMetricsInputProperties(step_name='test', bapi_stdout=_BAD_TYPE)),
      api.post_process(post_process.PropertiesDoNotContain, 'portage_stats'),
      api.post_check(post_process.StatusSuccess))
