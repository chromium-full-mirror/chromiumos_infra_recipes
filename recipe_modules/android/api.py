# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from collections import namedtuple
from typing import List, Tuple

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

from PB.chromite.api.android import GetLatestBuildRequest
from PB.chromite.api.android import MarkStableRequest
from PB.chromite.api.android import MarkStableStatusType
from PB.chromite.api.android import WriteLKGBRequest
from PB.chromite.api.packages import GetAndroidMetadataRequest
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import Chroot
from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

# A namedtuple to describe an android uprev
AndroidUprev = namedtuple('AndroidUprev',
                          ['android_version', 'android_package'])

# The project for android ebuilds
ANDROID_PROJECT = 'chromeos/overlays/project-cheets-private'

# Map package name to ebuild path
EBUILD_PATH = 'chromeos-base/{package_name}/{package_name}-9999.ebuild'


class AndroidApi(recipe_api.RecipeApi):

  def _get_android_metadata(self, chroot: Chroot,
                            sysroot: Sysroot) -> Tuple[str, str]:
    """Retrieve Android metadata from the given sysroot.

    Args:
      chroot: Information on the chroot for the build.
      sysroot: The Sysroot being used.

    Returns:
      (android_package, android_version)
      Both can be empty in case Android isn't installed.
    """
    metadata = self.m.cros_build_api.PackageService.GetAndroidMetadata(
        GetAndroidMetadataRequest(build_target=sysroot.build_target,
                                  chroot=chroot))
    return metadata.android_package, metadata.android_version

  def uprev_if_unstable_ebuild_changed(self, chroot: Chroot, sysroot: Sysroot,
                                       patch_sets: List[PatchSet]):
    """Uprev Android if changes are found in the unstable ebuild.

    Args:
      chroot: Information on the chroot for the build.
      sysroot: The Sysroot being used.
      patch_sets: List of patch sets (with FileInfo).
    """
    with self.m.step.nest('check if an android uprev is required') as pres:
      android_package, android_version = self._get_android_metadata(
          chroot, sysroot)

      if not android_package:
        pres.step_text = 'no android packages are being built'
        return

      unstable_ebuild = EBUILD_PATH.format(package_name=android_package)

      uprev = False
      for patch_set in patch_sets:
        if (patch_set.project == ANDROID_PROJECT and
            unstable_ebuild in patch_set.file_infos):
          uprev = True
          break

      if not uprev:
        pres.step_text = 'no file diffs caused an android uprev'
        return

      pres.step_text = '%s caused an android uprev' % unstable_ebuild

    # We don't care if there's an actual uprev as long as there's no error. For
    # example, uprev is skipped when the CL itself includes a manual uprev.
    self.uprev(chroot, sysroot, android_package, android_version)

  def uprev(self, chroot: Chroot, sysroot: Sysroot, android_package: str,
            android_version: str) -> bool:
    """Uprev the given Android package to the given version.

    Args:
      chroot: Information on the chroot for the build.
      sysroot: The Sysroot being used.
      android_package: The Android package to uprev (e.g. android-vm-rvc).
      android_version: The Android version to uprev to (e.g. 7123456).

    Returns:
      If the android package has been uprevved.
    """
    with self.m.step.nest('uprev android') as pres:
      request = MarkStableRequest(
          chroot=chroot,
          package_name=android_package,
          android_version=android_version,
          build_targets=[sysroot.build_target],
          skip_commit=True,
      )
      response = self.m.cros_build_api.AndroidService.MarkStable(request)

      if response.status == MarkStableStatusType.MARK_STABLE_STATUS_SUCCESS:
        pres.step_text = '%s revved to %s' % (android_package,
                                              response.android_atom.version)
        return True

      if response.status == MarkStableStatusType.MARK_STABLE_STATUS_EARLY_EXIT:
        pres.step_text = '%s not revved' % android_package
        return False

      raise StepFailure('MarkStable returned unhandled status %s' %
                        MarkStableStatusType.Name(response.status))

  def get_latest_build(self, android_package: str) -> str:
    """Retrieves the latest Android version for the given Android package.

    Args:
      android_package: The Android package.

    Returns:
      The latest Android version (build ID).
    """
    with self.m.step.nest('get latest android build') as pres:
      request = GetLatestBuildRequest(android_package=android_package)
      response = self.m.cros_build_api.AndroidService.GetLatestBuild(request)

      pres.step_text = 'found ab/{} for package {}'.format(
          response.android_version, android_package)
      return response.android_version

  def write_lkgb(self, android_package: str, android_version: str) -> List[str]:
    """Sets LKGB of given Android package to given version.

    Args:
      android_package: The Android package to set LKGB for.
      android_version: The LKGB Android version.

    Returns:
      List of modified files.
    """
    with self.m.step.nest('write android lkgb') as pres:
      request = WriteLKGBRequest(android_package=android_package,
                                 android_version=android_version)
      response = self.m.cros_build_api.AndroidService.WriteLKGB(request)

      if not response.modified_files:
        pres.step_text = 'no files were modified'
      return response.modified_files
