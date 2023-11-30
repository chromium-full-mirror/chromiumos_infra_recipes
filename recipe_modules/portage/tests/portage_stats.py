#  -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

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
_MULTIPLE_IDENTICAL = '''
[binary  N     ] sys-apps/baselayout-2.2-r1::chromiumos to /build/eve/ USE="kvm_host -auto_seed_etc_files" 60 KiB
[binary  N     ] sys-apps/baselayout-2.2-r1::chromiumos to /build/eve/ USE="kvm_host -auto_seed_etc_files" 60 KiB
[binary  N     ] sys-apps/baselayout-2.2-r1::chromiumos to /build/eve/ USE="kvm_host -auto_seed_etc_files" 60 KiB
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
  )

  yield api.test(
      'ignored-emerge-packages',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_IGNORED_EMERGE_PACKAGES,
              expected=api.portage.EXAMPLE_IGNORED_EMERGE_PACKAGES_EXPECTED)),
  )

  yield api.test(
      'two-emerge-init-sdk',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_DOUBLE_EMERGE_INIT_SDK,
              expected=api.portage.EXAMPLE_DOUBLE_EMERGE_INIT_SDK_EXPECTED)),
      api.post_check(post_process.StepTextContains, 'adding emerge metrics',
                     ['Soft failure finding portage stats']),
  )

  yield api.test(
      'fatal-is-non-fatal',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_SUCCESS_INSTALL_PACKAGES,
              expected=api.portage.EXAMPLE_SUCCESS_INSTALL_PACKAGES_EXPECTED)),
      # Oh no bigquery just refused to write!
      api.step_data('adding emerge metrics.insert to bq', retcode=1),
  )

  yield api.test(
      'failure-install',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_FAILURE_INSTALL_PACKAGES,
              expected=api.portage.EXAMPLE_FAILURE_INSTALL_PACKAGES_EXPECTED)),
  )

  yield api.test(
      'broken-install',
      api.properties(
          TestMetricsInputProperties(
              step_name='test',
              bapi_stdout=api.portage.EXAMPLE_BROKEN_INSTALL_PACKAGES)),
      api.post_process(post_process.PropertyEquals, 'failed_portage_stats',
                       True),
  )

  yield api.test(
      'fooled-output',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_FOOLED_OUTPUT)),
      api.post_process(post_process.PropertiesDoNotContain, 'portage_stats'),
  )

  yield api.test(
      'empty-output',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_NO_EMERGE_OUTPUT)),
      api.post_process(post_process.PropertiesDoNotContain, 'portage_stats'),
  )

  yield api.test(
      'bad-type',
      api.properties(
          TestMetricsInputProperties(step_name='test', bapi_stdout=_BAD_TYPE)),
      api.post_process(post_process.PropertiesDoNotContain, 'portage_stats'),
  )

  yield api.test(
      'multiple-identical-packages',
      api.properties(
          TestMetricsInputProperties(step_name='test',
                                     bapi_stdout=_MULTIPLE_IDENTICAL)),
      api.post_process(post_process.PropertiesDoNotContain, 'portage_stats'),
  )
