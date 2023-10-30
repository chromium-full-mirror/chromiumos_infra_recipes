# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sysroot archive functions."""

from PB.chromite.api.sysroot import SysrootGenerateArchiveRequest
from PB.chromiumos import common
from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties
from recipe_engine import recipe_api


class SysrootArchiveApi(recipe_api.RecipeApi):
  """A module for interacting with sysroot archive."""

  def __init__(self, props: SysrootArchiveApiProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.sysroot_enabled = props.sysroot_enabled

  def archive_sysroot_build(self, build_target=None, packages=None):
    if not self.sysroot_enabled.save_sysroot_archive:
      return

    if not build_target:
      return

    if packages is None:
      packages = []

    with self.m.step.nest('archive sysroot'):
      wanted = [
          'target-chromium-os-dev',
          'target-chromium-os-factory',
          'target-chromium-os-factory-shim',
          'target-chrome-os',
          'target-chromium-os',
          'target-chrome-os-test',
          'target-chromium-os-test',
      ]

      # Add all dependency packages.
      if not self.m.build_menu.dep_graph:
        self.m.build_menu.get_dep_graph_and_validate_sdk_reuse()
      for package in self.m.build_menu.dep_graph.target.package_deps:
        package_info = package.package_info
        if package_info.category == 'virtual' and package_info.package_name in wanted:
          packages.append(package_info)

      # Create temparory directory.
      tmp_dir = self.m.path.mkdtemp(prefix='sysroot-archive')
      result_path = common.ResultPath(
          path=common.Path(path=str(tmp_dir), location=common.Path.OUTSIDE))

      request = SysrootGenerateArchiveRequest(
          build_target=self.m.build_menu.build_target,
          chroot=self.m.build_menu.chroot, target_dir=result_path,
          packages=packages)
      response = self.m.cros_build_api.SysrootService.GenerateArchive(request)
      archive_path = response.sysroot_archive.path

      # Upload to gs_bucket.
      build_id = str(
          self.m.buildbucket.build.id or self.m.led.run_id.replace('/', '_'))

      gs_archive_folder = '%s/%s' % (
          build_target.name, self.sysroot_enabled.chromeos_start_version)
      if self.sysroot_enabled.chromeos_cl_diff_counts:
        gs_archive_folder += '~%d' % self.sysroot_enabled.chromeos_cl_diff_counts
      gs_archive_folder += '-%s' % build_id
      gs_path = self.m.path.join(gs_archive_folder,
                                 self.m.path.basename(archive_path))
      self.m.gsutil.upload(archive_path, self.sysroot_enabled.gs_bucket,
                           gs_path)
