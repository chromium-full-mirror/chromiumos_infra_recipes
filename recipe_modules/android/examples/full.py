# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

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
  yield api.test(
      'missing-api',
      api.cros_build_api.remove_endpoints(['PackageService/GetAndroidMetadata'
                                          ]))
  yield api.test('changes-no-uprev', api.properties(changes=True),
                 api.android.set_mark_stable_early_exit())

  # TODO(b/187888777): Remove when _get_android_metadata_fallback is removed.
  fallback_testcases = [
      ('android-pi', 'git_pi-arc', 'cheets', '7123456'),
      ('android-rvc', 'git_rvc-arc', 'bertha', '7123456'),
      ('android-sc', 'git_sc-arc-dev', 'bertha', '7123456'),
      ('android-mst', 'git_master-arc-dev', 'bertha', '7123456'),
      ('bad-android', 'git_pi-arc', 'bertha', '7123456'),
      ('missing-branch', '', 'bertha', '7123456'),
      ('missing-target', 'git_rvc-arc', '', '7123456'),
      ('no-android', '', '', ''),
  ]
  for name, branch, target, version in fallback_testcases:
    target_versions = {
        'android_branch_version': branch,
        'android_target_version': target,
        'android_version': version,
    }
    yield api.test(
        'fallback-' + name, api.properties(changes=True),
        api.cros_build_api.remove_endpoints(
            ['PackageService/GetAndroidMetadata']),
        api.cros_build_api.set_api_return(
            'check if an android uprev is required',
            'PackageService/GetTargetVersions', json.dumps(target_versions)))
