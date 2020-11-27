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
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'git',
    'git_cl',
    'src_state',
]

from recipe_engine import post_process


def RunSteps(api):
  url = ('https://chrome-internal.googlesource.com/'
         'chrome/tools/build/internal.DEPS')
  path = api.path.mkdtemp()
  try:
    with api.step.nest('attempt forge commit to %s' %
                       url), api.context(cwd=path):
      api.git.set_global_config(['--list'])
      api.git.clone(url, timeout_sec=5 * 60)
      api.step('add trailing whitespace to DEPS',
               ['sed', '-i', '-e', '$a\\n', 'DEPS'])
      api.git.add(['DEPS'])
      api.git.commit('expecting rejection for forged commit',
                     author='Sean Abraham <seanabraham@google.com>')
      api.git_cl.upload(name='git cl upload')
      api.git.push(url, 'main')
  finally:
    zips = api.file.glob_paths('glob traces', api.depot_tools.root,
                               'traces/*.zip')
    zips = (['zcat'] + zips) if zips else None
    not zips or api.step('dump git-cl trace logs', zips)


def GenTests(api):
  yield api.test(
      'basic', api.post_check(post_process.DoesNotRun,
                              'dump git-cl trace logs'))

  yield api.test(
      'with-traces',
      api.step_data(
          'glob traces',
          api.file.glob_paths(['traces/20200918T145509.172161-traces.zip'])),
      api.post_check(post_process.MustRun, 'dump git-cl trace logs'))
