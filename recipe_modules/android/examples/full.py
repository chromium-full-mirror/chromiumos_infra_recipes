# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.android.examples.test import TestProperties
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot

DEPS = [
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/step',
    'android',
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
  api.android.try_uprev(chroot, sysroot, patch_sets)


TARGET_VERSIONS_WITH_ANDROID_PI = """
{
  "androidBranchVersion": "git_pi-arc",
  "androidTargetVersion": "cheets",
  "androidVersion": "7002143",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""
TARGET_VERSIONS_WITH_ANDROID_RVC = """
{
  "androidBranchVersion": "git_rvc-arc",
  "androidTargetVersion": "bertha",
  "androidVersion": "7002143",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""
TARGET_VERSIONS_WITH_ANDROID_SC = """
{
  "androidBranchVersion": "git_sc-arc-dev",
  "androidTargetVersion": "bertha",
  "androidVersion": "7002143",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""
TARGET_VERSIONS_WITH_ANDROID_MAIN = """
{
  "androidBranchVersion": "git_master-arc-dev",
  "androidTargetVersion": "bertha",
  "androidVersion": "7002143",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""
TARGET_VERSIONS_WITHOUT_ANDROID = """
{
  "androidBranchVersion": "",
  "androidTargetVersion": "",
  "androidVersion": "",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""
TARGET_VERSIONS_WITH_BAD_ANDROID = """
{
  "androidBranchVersion": "git_pi-arc",
  "androidTargetVersion": "bertha",
  "androidVersion": "7002143",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""
TARGET_VERSIONS_WITH_MISSING_ANDROID_BRANCH = """
{
  "androidTargetVersion": "bertha",
  "androidVersion": "7002143",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""
TARGET_VERSIONS_WITH_MISSING_ANDROID_TARGET = """
{
  "androidBranchVersion": "git_pi-arc",
  "androidVersion": "7002143",
  "chromeVersion": "89.0.4339.0",
  "fullVersion": "R89-13635.0.0",
  "milestoneVersion": "89",
  "platformVersion": "13635.0.0"
}
"""


def GenTests(api):
  android_pi_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITH_ANDROID_PI))
  android_rvc_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITH_ANDROID_RVC))
  android_sc_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITH_ANDROID_SC))
  android_main_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITH_ANDROID_MAIN))
  no_android_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITHOUT_ANDROID))
  bad_android_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITH_BAD_ANDROID))
  missing_android_branch_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITH_MISSING_ANDROID_BRANCH))
  missing_android_target_version = api.step_data(
      'get android version information.read output file',
      api.file.read_raw(TARGET_VERSIONS_WITH_MISSING_ANDROID_TARGET))

  def test_data(changes=True, with_android=True,
                android_steps=android_rvc_version):
    data = api.properties(TestProperties(changes=changes))
    data += android_steps if with_android else no_android_version
    return data

  yield api.test('changes-with-android',
                 test_data(changes=True, with_android=True))
  yield api.test('no-changes-with-android',
                 test_data(changes=False, with_android=True))
  yield api.test(
      'changes-with-android-p',
      test_data(changes=True, with_android=True,
                android_steps=android_pi_version))
  yield api.test(
      'changes-with-android-sc',
      test_data(changes=True, with_android=True,
                android_steps=android_sc_version))
  yield api.test(
      'changes-with-android-main',
      test_data(changes=True, with_android=True,
                android_steps=android_main_version))
  yield api.test(
      'with-missing-android-branch',
      test_data(changes=True, with_android=True,
                android_steps=missing_android_branch_version))
  yield api.test(
      'with-missing-android-target',
      test_data(changes=True, with_android=True,
                android_steps=missing_android_target_version))
  yield api.test('without-android', test_data(with_android=False))
  yield api.test(
      'with-bad-android',
      test_data(with_android=True, android_steps=bad_android_version))
