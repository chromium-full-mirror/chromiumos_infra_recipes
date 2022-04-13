# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import six

DEPS = [
    'recipe_engine/assertions',
    'git_cl',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  output = api.git_cl.status(field='url', fast=True, issue='3402394',
                             step_name='git cl status')
  api.assertions.assertEqual(output, six.ensure_binary('foo'))


def GenTests(api):
  yield api.test(
      'basic',
      api.git_cl.output('git cl status', 'foo'),
  )
