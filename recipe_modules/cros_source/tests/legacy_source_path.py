# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'chromite',
    'cros_source',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'src_state',
]


def RunSteps(api):
  with api.cros_source.checkout_overlays_context(legacy=True):
    api.chromite.set_config('chromiumos_coverage')
    api.chromite.cbuildbot('cbuildbot', 'amd64-generic-full',
                           args=['--clobber', '--build-dir', '/here/there'])
    api.chromite.run()


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(cbb_config='auron-paladin'),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
      api.post_check(
          post_process.StepCommandContains, 'mount overlay chromiumos.mount', [
              'sudo', '-n', 'mount', '-t', 'overlay', '--options',
              ('lowerdir=/preload/chromeos,'
               'upperdir=[CLEANUP]/overlayfs/chromiumos/upperdir/chromiumos,'
               'workdir=[CLEANUP]/overlayfs/chromiumos/workdir/chromiumos,'
               'x-chromeos-overlay.name=chromiumos'), 'overlay',
              '[CLEANUP]/chromiumos'
          ]),
      api.post_check(
          post_process.StepCommandContains, 'mount overlay workspace.mount', [
              'sudo', '-n', 'mount', '-t', 'overlay', '--options',
              ('lowerdir=[CLEANUP]/chromiumos,'
               'upperdir=[CLEANUP]/overlayfs/workspace/upperdir/workspace,'
               'workdir=[CLEANUP]/overlayfs/workspace/workdir/workspace,'
               'x-chromeos-overlay.name=workspace'), 'overlay',
              '[START_DIR]/chromiumos_workspace'
          ]),
      api.post_process(post_process.MustRun, 'clean up overlayfs mounts'),
  )
