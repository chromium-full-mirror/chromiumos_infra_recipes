# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
    'support',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  output = api.support.call('my-tool', {'input': 'data'})
  api.assertions.assertDictEqual(output, {'output': 'data'})

  # Call a second time to hit the CIPD path caching.
  api.support.call('my-tool', {'input': 'data'})


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('my-tool', stdout=api.json.output({'output': 'data'})),
      api.post_process(post_process.DropExpectation),
  )
