# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'git_cl',
]


def RunSteps(api):
  output = api.git_cl.upload(topic='tensorflow', reviewers=['jeff@google.com'],
                             ccs=['dean@google.com'],
                             hashtags=['foo-refactoring',
                                       'bar-feature'], send_mail=True)
  api.assertions.assertEqual(output, 'pytorch forever')

def GenTests(api):
  yield api.test(
      'basic',
      api.git_cl.output('git_cl upload', 'pytorch forever'),
  )
