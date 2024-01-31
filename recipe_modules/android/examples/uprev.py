# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'android',
]



def RunSteps(api: RecipeApi):
  chroot = Chroot()
  sysroot = Sysroot(build_target=BuildTarget(name='build_target'))
  api.android.uprev(chroot, sysroot, 'android-package', 'android-version',
                    'android-branch')


def GenTests(api: RecipeTestApi):
  yield api.test(
      'mark-stable-success',
      api.android.set_mark_stable_success(),
  )
  yield api.test(
      'mark-stable-pinned',
      api.android.set_mark_stable_pinned(),
      status='FAILURE',
  )
  yield api.test(
      'mark-stable-early-exit',
      api.android.set_mark_stable_early_exit(),
  )
