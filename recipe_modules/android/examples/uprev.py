# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot

DEPS = [
    'android',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  chroot = Chroot()
  sysroot = Sysroot(build_target=BuildTarget(name='build_target'))
  api.android.uprev(chroot, sysroot, 'android-package', 'android-version')


def GenTests(api):
  yield api.test('mark-stable-success', api.android.set_mark_stable_success(),
                 api.post_check(post_process.StatusSuccess))
  yield api.test('mark-stable-pinned', api.android.set_mark_stable_pinned(),
                 api.post_check(post_process.StatusFailure))
  yield api.test('mark-stable-early-exit',
                 api.android.set_mark_stable_early_exit(),
                 api.post_check(post_process.StatusSuccess))
