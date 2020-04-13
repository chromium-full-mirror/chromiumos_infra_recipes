# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for forcing forge commit failure.


Recipe used to force a forge commit failure so the failure response
can be analyzed to determine what user is being used for the invocation.
See https://crbug.com/1068743.
"""

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'git',
]


def RunSteps(api):
  url = ('https://chrome-internal.googlesource.com/'
         'chrome/tools/build/internal.DEPS')
  path = api.path.mkdtemp()
  with api.step.nest('attempt forge commit to %s' % url), api.context(cwd=path):
    api.git.clone(url, timeout_sec=5 * 60)
    api.step('add trailing whitespace to DEPS',
             ['sed', '-i', '-e', '$a\\n', 'DEPS'])
    api.git.add(['DEPS'])
    api.git.commit('expecting rejection for forged commit',
                   author='Sean Abraham <seanabraham@google.com>')
    api.git.push(url, 'master')


def GenTests(api):
  yield api.test('basic')
