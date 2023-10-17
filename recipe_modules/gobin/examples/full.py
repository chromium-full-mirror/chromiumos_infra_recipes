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

  api.gobin.ensure_package('branch_util')
  # Again, make sure it doesn't do anything!
  api.gobin.ensure_package('branch_util')


def GenTests(api):
  CIPD_JSON = '''{
    "result": [
        {
            "package": "chromiumos/infra/branch_util/linux-amd64",
            "instance_id": "wzCA5zCcIkg0uYroNN91fpH1oQLMVHYaXM8RS9SuQwUC"
        }
    ]
}
'''

  yield api.test(
      'basic',
      api.step_data(
          'ensure chromiumos/infra/branch_util/${platform}.read [CLEANUP]/cipd.json',
          api.file.read_text(CIPD_JSON)),
      api.post_check(
          post_process.StepCommandContains,
          'ensure chromiumos/infra/branch_util/${platform}.cipd search', [
              'cipd', 'search', 'chromiumos/infra/branch_util/${platform}',
              '-tag', 'git_revision:deadbeef', '-json-output',
              '[CLEANUP]/cipd.json'
          ]),
      api.post_check(
          post_process.DoesNotRun,
          'ensure chromiumos/infra/branch_util/${platform} (1).cipd search'),
      api.post_process(post_process.DropExpectation),
  )
