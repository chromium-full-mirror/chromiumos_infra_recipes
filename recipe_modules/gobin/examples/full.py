# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for standard `gobin` module usage."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'gobin',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  _ = api.gobin.supported_packages

  api.gobin.ensure_package('my_gobin')
  # Again, make sure it doesn't do anything!
  api.gobin.ensure_package('my_gobin')

  api.gobin.call('my_gobin', ['create', 'foo'])
  api.gobin.call('my_gobin', ['create', 'bar'], step_name='my command')


def GenTests(api):
  CIPD_JSON = '''{
    "result": [
        {
            "package": "chromiumos/infra/my_gobin/linux-amd64",
            "instance_id": "wzCA5zCcIkg0uYroNN91fpH1oQLMVHYaXM8RS9SuQwUC"
        }
    ]
}
'''

  yield api.test(
      'basic',
      api.step_data(
          'ensure my_gobin.find cipd instance for my_gobin for infra/infra commit deadbeef.read [CLEANUP]/cipd.json',
          api.file.read_text(CIPD_JSON)),
      api.post_check(
          post_process.StepCommandContains,
          'ensure my_gobin.find cipd instance for my_gobin for infra/infra commit deadbeef.cipd search',
          [
              'cipd', 'search', 'chromiumos/infra/my_gobin/${platform}', '-tag',
              'git_revision:deadbeef', '-json-output', '[CLEANUP]/cipd.json'
          ]),
      api.post_check(post_process.DoesNotRun,
                     'ensure my_gobin (1).cipd search'),
      api.post_check(
          post_process.StepCommandContains,
          'run my_gobin',
          ['[START_DIR]/cipd/my_gobin', 'create', 'foo'],
      ),
      api.post_check(
          post_process.StepCommandContains,
          'my command',
          ['[START_DIR]/cipd/my_gobin', 'create', 'bar'],
      ),
      api.post_process(post_process.DropExpectation),
  )
