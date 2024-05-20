# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.ctpv2.ctpv2 import Ctpv2ModuleProperties
from PB.recipes.chromeos.test_platform.cros_test_platform import (
    CrosTestPlatformProperties,)


DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'ctpv2',
]

PROPERTIES = CrosTestPlatformProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(api.ctpv2.cipd_package_label(), 'some-cipd-label')

  with api.step.nest('callsite-execute-luciexe'):
    api.ctpv2.is_enabled()
    api.ctpv2.execute_luciexe()
    api.ctpv2.ensure_ctpv2()
    if properties.requests:
      api.ctpv2.set_allowed_pools({'test-pool'})
      api.ctpv2.filter_legacy_requests(properties.requests, True)
      api.ctpv2.filter_legacy_requests(properties.requests, False)


def GenTests(api):
  yield api.test(
      'custom-label',
      api.properties(
          **{
              '$chromeos/ctpv2':
                  Ctpv2ModuleProperties(
                      version=Ctpv2ModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      ))
          }) +  #
      api.ctpv2.mock_luciexe_call('callsite-execute-luciexe'),
  )
  yield api.test(
      'v2-with-qs',
      api.properties(
          **{
              '$chromeos/ctpv2':
                  Ctpv2ModuleProperties(
                      version=Ctpv2ModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      )),
              'requests': {
                  'fake-request': {
                      'params': {
                          'runViaCft': True,
                          'runCtpv2WithQs': True,
                      }
                  }
              }
          }) + api.ctpv2.mock_luciexe_call('callsite-execute-luciexe'),
  )
  yield api.test(
      'allowed-pool',
      api.properties(
          **{
              '$chromeos/ctpv2':
                  Ctpv2ModuleProperties(
                      version=Ctpv2ModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      )),
              'requests': {
                  'fake-request': {
                      'params': {
                          'decorations': {
                              'tags': ['pool:test-pool',]
                          },
                          'runCtpv2WithQs': True,
                      }
                  }
              }
          }) + api.ctpv2.mock_luciexe_call('callsite-execute-luciexe'),
  )
  yield api.test(
      'allowed-label-pool',
      api.properties(
          **{
              '$chromeos/ctpv2':
                  Ctpv2ModuleProperties(
                      version=Ctpv2ModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      )),
              'requests': {
                  'fake-request': {
                      'params': {
                          'decorations': {
                              'tags': ['fake', 'label-pool:test-pool']
                          },
                          'runCtpv2WithQs': True,
                      }
                  }
              }
          }) + api.ctpv2.mock_luciexe_call('callsite-execute-luciexe'),
  )
  yield api.test(
      'unallowed-pool',
      api.properties(
          **{
              '$chromeos/ctpv2':
                  Ctpv2ModuleProperties(
                      version=Ctpv2ModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      )),
              'requests': {
                  'fake-request': {
                      'params': {
                          'decorations': {
                              'tags': ['pool:unallowed-pool']
                          },
                          'runCtpv2WithQs': True,
                      }
                  }
              }
          }) + api.ctpv2.mock_luciexe_call('callsite-execute-luciexe'),
  )
  yield api.test(
      'invalid-ctpv2-request',
      api.properties(
          **{
              '$chromeos/ctpv2':
                  Ctpv2ModuleProperties(
                      version=Ctpv2ModuleProperties.Version(
                          cipd_label='some-cipd-label',
                      )),
              'requests': {
                  'fake-request': {
                      'params': {}
                  }
              }
          }) + api.ctpv2.mock_luciexe_call('callsite-execute-luciexe'),
  )
