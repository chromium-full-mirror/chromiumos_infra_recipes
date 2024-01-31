# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'deferrals',
]



class SpecialException(Exception):
  pass


def RunSteps(api):
  with api.deferrals.defer_exceptions(exception_types=[SpecialException]):
    raise SpecialException()
  with api.assertions.assertRaises(SpecialException):
    api.deferrals.raise_exceptions()
  with api.deferrals.defer_exceptions(exception_types=[SpecialException]):
    api.step('a failed step', ['ls'])
  api.step('this will NOT happen', ['ls'])  #pragma: no cover


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('a failed step', retcode=1),
      api.post_check(post_process.StepFailure, 'a failed step'),
      api.post_check(post_process.DoesNotRun, 'this will NOT happen'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
