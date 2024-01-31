# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.ctpv2.ctpv2 import Ctpv2ModuleProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'ctpv2',
]



def RunSteps(api):
  api.assertions.assertEqual(api.ctpv2.cipd_package_label(), 'some-cipd-label')

  with api.step.nest('callsite-execute-luciexe'):
    api.ctpv2.is_enabled()
    api.ctpv2.execute_luciexe()
    api.ctpv2.ensure_ctpv2()


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
