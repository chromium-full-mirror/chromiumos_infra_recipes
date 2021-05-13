# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.android import MarkStableRequest
from PB.chromite.api.android import MarkStableStatusType
from PB.chromite.api.packages import GetAndroidMetadataRequest
from PB.chromite.api.packages import GetTargetVersionsRequest

from collections import namedtuple

# A namedtuple to describe an android uprev
AndroidUprev = namedtuple('AndroidUprev',
                          ['android_version', 'android_package'])

# The project for android ebuilds
ANDROID_PROJECT = 'chromeos/overlays/project-cheets-private'

# Map package name to ebuild path
EBUILD_PATH = 'chromeos-base/{package_name}/{package_name}-9999.ebuild'


class AndroidApi(recipe_api.RecipeApi):

  def __init__(self, props, *args, **kwargs):
    super(AndroidApi, self).__init__(*args, **kwargs)
    self._android_package = props.android_package
    self._android_version = props.android_version

  @property
  def android_package(self):
    return self._android_package

  @property
  def android_version(self):
    return self._android_version

  def _get_android_metadata_fallback(self, chroot, sysroot):
    """Retrieve Android metadata using PackageService/GetTargetVersions.

    Called when PackageService/GetAndroidMetadata is not available (before R92).
    TODO(b/187888777): Remove this.
    """
    request = GetTargetVersionsRequest(chroot=chroot,
                                       build_target=sysroot.build_target,
                                       packages=[])
    target_versions = self.m.cros_build_api.PackageService.GetTargetVersions(
        request)

    self._android_version = target_versions.android_version

    if not self._android_version:
      return

    android_branch = target_versions.android_branch_version
    android_target = target_versions.android_target_version

    if not android_branch:
      raise StepFailure('No android_branch provided')

    if not android_target:
      raise StepFailure('No android_target provided')

    # Map (branch, target) to package name
    if android_branch.startswith('git_pi-arc') and android_target == 'cheets':
      self._android_package = 'android-container-pi'
    elif android_branch.startswith(
        'git_rvc-arc') and android_target == 'bertha':
      self._android_package = 'android-vm-rvc'
    elif android_branch.startswith(
        'git_sc-arc-dev') and android_target == 'bertha':
      self._android_package = 'android-vm-sc'
    elif android_branch.startswith(
        'git_master-arc-dev') and android_target == 'bertha':
      self._android_package = 'android-vm-master'
    else:
      raise StepFailure('cannot decide the package name for '
                        'android_branch=%s android_target=%s' %
                        (android_branch, android_target))

  def _get_android_metadata(self, chroot, sysroot):
    """Retrieve Android metadata from the given sysroot."""
    if not self.m.cros_build_api.has_endpoint(
        self.m.cros_build_api.PackageService, 'GetAndroidMetadata'):
      self._get_android_metadata_fallback(chroot, sysroot)
      return

    metadata = self.m.cros_build_api.PackageService.GetAndroidMetadata(
        GetAndroidMetadataRequest(build_target=sysroot.build_target,
                                  chroot=chroot))
    self._android_package = metadata.android_package
    self._android_version = metadata.android_version

  def uprev_if_unstable_ebuild_changed(self, chroot, sysroot, patch_sets):
    """Uprev Android if changes are found in the unstable ebuild.

    Args:
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      sysroot (Sysroot): The Sysroot being used.
      patch_sets (list[gerrit.PatchSet]): List of patch sets (with FileInfo).
    """
    with self.m.step.nest('check if an android uprev is required') as pres:
      self._get_android_metadata(chroot, sysroot)

      if not self.android_package:
        pres.step_text = 'no android packages are being built'
        return

      unstable_ebuild = EBUILD_PATH.format(package_name=self.android_package)

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

    if not self.uprev(chroot, sysroot):
      raise StepFailure('Android did not uprev, check log for details')

  def uprev(self, chroot, sysroot):
    """Uprev the Android package.

    Args:
      chroot (chromiumos.Chroot): Information on the chroot for the build.
      sysroot (Sysroot): The Sysroot being used.

    Returns:
      bool: If the android package has been uprevved.
    """
    with self.m.step.nest('uprev android') as pres:
      request = MarkStableRequest(
          chroot=chroot,
          package_name=self.android_package,
          android_version=self.android_version,
          build_targets=[sysroot.build_target],
          skip_commit=True,
      )
      response = self.m.cros_build_api.AndroidService.MarkStable(request)

      if response.status == MarkStableStatusType.MARK_STABLE_STATUS_SUCCESS:
        pres.step_text = '%s revved to %s' % (self.android_package,
                                              response.android_atom.version)
        return True

      if response.status == MarkStableStatusType.MARK_STABLE_STATUS_EARLY_EXIT:
        pres.step_text = '%s not revved' % self.android_package
        return False

      raise StepFailure('MarkStable returned unhandled status %s' %
                        MarkStableStatusType.Name(response.status))
