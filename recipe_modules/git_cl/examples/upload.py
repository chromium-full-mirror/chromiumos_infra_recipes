# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'git_cl',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  output = api.git_cl.upload(topic='tensorflow', reviewers=['jeff@google.com'],
                             ccs=['dean@google.com'],
                             hashtags=['foo-refactoring', 'bar-feature'],
                             send_mail=True, target_branch='HEAD', dry_run=True)
  api.assertions.assertEqual(output, b'pytorch forever')


def GenTests(api):
  yield api.test(
      'basic',
      api.git_cl.output('git_cl upload', 'pytorch forever'),
  )
