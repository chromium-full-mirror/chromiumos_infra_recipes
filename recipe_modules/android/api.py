# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.android import MarkStableRequest
from PB.chromite.api.packages import GetTargetVersionsRequest
from PB.chromiumos.common import PackageInfo

from collections import namedtuple

# A namedtuple to describe an android uprev
AndroidUprev = namedtuple(
    'AndroidUprev', ['android_version', 'android_branch', 'android_package'])

# The project for android ebuilds
ANDROID_PROJECT = 'chromeos/overlays/project-cheets-private'

# Map (branch,target) to package name
# TODO(boleynsu): find a clean way to avoid indexing by a tuple
ANDROID_PACKAGE = {
    ('git_pi-arc', 'cheets'): 'android-container-pi',
    ('git_pi-arc-m86', 'cheets'): 'android-container-pi',
    ('git_rvc-arc', 'bertha'): 'android-vm-rvc',
    ('git_master-arc-dev', 'bertha'): 'android-vm-master'
}

# Map package name to ebuild path
EBUILD_PATH = 'chromeos-base/{package_name}/{package_name}-9999.ebuild'


class AndroidApi(recipe_api.RecipeApi):

  def requires_uprev(self, chroot, sysroot, patch_sets):
    """Check if an android uprev is required.

    Args:
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      sysroot (Sysroot): The Sysroot being used.
      patch_sets (list[gerrit.PatchSet]): List of patch sets (with FileInfo).

    Returns:
      None|AndroidUprev
      Returns None if uprev is not required.
      Returns (android_version, android_branch, android_package), otherwise.
    """
    request = GetTargetVersionsRequest(chroot=chroot,
                                       build_target=sysroot.build_target,
                                       packages=[])
    target_versions = self.m.cros_build_api.PackageService.GetTargetVersions(
        request, name='get android version information')

    android_version = target_versions.android_version

    if not android_version:
      return None

    android_branch = target_versions.android_branch_version
    android_target = target_versions.android_target_version

    if not (android_branch, android_target) in ANDROID_PACKAGE:
      raise StepFailure('cannot decide the package name for '
                        'android_branch=%s android_target=%s' %
                        (android_branch, android_target))

    android_package = ANDROID_PACKAGE[(android_branch, android_target)]

    unstable_ebuild = EBUILD_PATH.format(package_name=android_package)

    with self.m.step.nest('check if an android uprev is required') as pres:
      for patch_set in patch_sets:
        if (patch_set.project == ANDROID_PROJECT and
            unstable_ebuild in patch_set.file_infos):
          pres.step_text = '%s caused an android uprev' % unstable_ebuild
          return AndroidUprev(android_version, android_branch, android_package)
      pres.step_text = 'no file diffs caused an android uprev'
      return None

  def try_uprev(self, chroot, sysroot, patch_sets):
    """Try to uprev android

    Args:
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      sysroot (Sysroot): The Sysroot being used.
      patch_sets (list[gerrit.PatchSet]): List of patch sets (with FileInfo).

    Returns:
      bool: If we upreved the android package.
    """
    requires_uprev = self.requires_uprev(chroot, sysroot, patch_sets)
    if requires_uprev:
      (android_version, android_branch, android_package) = requires_uprev
      with self.m.step.nest('try uprev android'):
        request = MarkStableRequest(
            chroot=chroot,
            tracking_branch='',
            package_name=android_package,
            android_build_branch=android_branch,
            android_version=android_version,
            build_targets=[sysroot.build_target],
        )
        self.m.cros_build_api.AndroidService.MarkStable(
            request, name='uprev android package %s' % android_package)
        return True
    return False
