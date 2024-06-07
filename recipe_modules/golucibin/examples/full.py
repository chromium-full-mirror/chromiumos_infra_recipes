# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test examples showing off golucibin."""

from recipe_engine import recipe_api

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'golucibin',
]


def RunSteps(api: recipe_api.RecipeApi):
  with api.step.nest('callsite-execute-luciexe'):
    api.golucibin.ensure_package('ctpv2', 'staging')
    api.golucibin.execute_luciexe('ctpv2', 'staging')


def GenTests(api: recipe_api.RecipeApi):
  yield api.test(
      'valid',
      api.golucibin.set_execute_luciexe_response('callsite-execute-luciexe',
                                                 'ctpv2'),
  )
