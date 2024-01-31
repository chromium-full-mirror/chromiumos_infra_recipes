# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from typing import List

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot
from PB.recipe_modules.chromeos.android.examples.test import TestProperties
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'android',
    'cros_build_api',
    'gerrit',
]


PROPERTIES = TestProperties


def RunSteps(api: RecipeApi, properties: TestProperties):

  def patch_set(files: List[str]) -> PatchSet:
    """Return a patchset.

    Args:
      files: list of modified files.

    Returns:
      A patch set.
    """
    project = 'chromeos/overlays/project-cheets-private'
    return PatchSet({
        'host': 'test',
        'info': {
            'project': project
        },
        'patch_set': 3,
        'patch_set_revision': 'f000' * 10,
        'revision_info': {
            'files': {f: {} for f in files}
        }
    })

  chroot = Chroot()
  sysroot = Sysroot(build_target=BuildTarget(name='build_target'))
  files = ['some/path/that/isnt/important']
  if properties.changes:
    files += ['chromeos-base/android-vm-rvc/android-vm-rvc-9999.ebuild']
  patch_sets = [patch_set(files)]
  api.android.uprev_if_unstable_ebuild_changed(chroot, sysroot, patch_sets)


def GenTests(api: RecipeTestApi):
  yield api.test('no-changes-with-android')
  yield api.test('changes-with-android', api.properties(changes=True))
  yield api.test(
      'without-android',
      api.cros_build_api.set_api_return('check if an android uprev is required',
                                        'PackageService/GetAndroidMetadata',
                                        '{}'))
  yield api.test('changes-no-uprev', api.properties(changes=True),
                 api.android.set_mark_stable_early_exit())
