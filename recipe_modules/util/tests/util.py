# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'util',
]

from RECIPE_MODULES.chromeos.util import util

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):

  @util.exponential_retry(retries=2)
  def test_retry():
    api.step('test', ['/bin/true'])
    return True

  api.assertions.assertTrue(test_retry())


def GenTests(api):

  yield api.test('basic-retry')

  yield api.test('retry-once', api.step_data('test', retcode=1))

  yield api.test('retry-twice', api.step_data('test', retcode=1),
                 api.step_data('test (2)', retcode=1))
