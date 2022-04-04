# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.android.examples.test import TestProperties
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot

DEPS = [
    'recipe_engine/properties',
    'android',
    'cros_build_api',
    'gerrit',
]

PROPERTIES = TestProperties


def RunSteps(api, properties):

  def patch_set(files):
    """Return a patchset.

    Args:
      files (list[str]): list of modified files.

    Returns:
      A gerrit.PatchSet.
    """
    project = 'chromeos/overlays/project-cheets-private'
    return api.gerrit.PatchSet(
        dict(host='test', info=dict(project=project), patch_set='3',
             revision_info=dict(files={f: {} for f in files})))

  chroot = Chroot()
  sysroot = Sysroot(build_target=BuildTarget(name='build_target'))
  files = ['some/path/that/isnt/important']
  if properties.changes:
    files += ['chromeos-base/android-vm-rvc/android-vm-rvc-9999.ebuild']
  patch_sets = [patch_set(files)]
  api.android.uprev_if_unstable_ebuild_changed(chroot, sysroot, patch_sets)


def GenTests(api):
  yield api.test('no-changes-with-android')
  yield api.test('changes-with-android', api.properties(changes=True))
  yield api.test(
      'without-android',
      api.cros_build_api.set_api_return('check if an android uprev is required',
                                        'PackageService/GetAndroidMetadata',
                                        '{}'))
  yield api.test('changes-no-uprev', api.properties(changes=True),
                 api.android.set_mark_stable_early_exit())
