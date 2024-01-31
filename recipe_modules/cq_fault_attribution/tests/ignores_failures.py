# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cq_fault_attribution.cq_fault_attribution import \
  CqFaultAttributionApiProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'failures',
]



def RunSteps(api):
  with api.failures.ignore_exceptions():
    api.step('a failed step', ['ls'])


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cq_fault_attribution':
                  CqFaultAttributionApiProperties(enable_fault_attribution=True)
          }), api.step_data('a failed step', retcode=1),
      api.post_process(post_process.DropExpectation))
