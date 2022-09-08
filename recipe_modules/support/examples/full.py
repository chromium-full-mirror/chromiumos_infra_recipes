# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/json',
    'support',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  output = api.support.call('my-tool', {'input': 'data'})
  api.assertions.assertDictEqual(output, {'output': 'data'})


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('my-tool', stdout=api.json.output(dict(output='data'))),
  )
