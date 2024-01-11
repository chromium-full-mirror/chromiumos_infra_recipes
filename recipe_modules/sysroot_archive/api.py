# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sysroot archive functions."""

from PB.chromite.api import artifacts
from PB.chromite.api.sysroot import Sysroot
import PB.chromiumos.common as common_pb2
from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties
from recipe_engine import recipe_api


class SysrootArchiveApi(recipe_api.RecipeApi):
  """A module for interacting with sysroot archive."""

  def __init__(self, props: SysrootArchiveApiProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.sysroot_enabled = props.sysroot_enabled

  def archive_sysroot_build(self, chroot: common_pb2.Chroot, sysroot: Sysroot,
                            build_target: common_pb2.BuildTarget) -> None:
    """Archives sysroot into gs bucket.

    The gs path format of the archive should be:
      gs://bucket/board/chromeos_version~cl_diff_count-build_id/archive_name.

    Args:
      chroot: The chroot to use.
      sysroot: The sysroot to use.
      build_target: The build target of the sysroot archive.
    """
    if not self.sysroot_enabled.save_sysroot_archive:
      return

    with self.m.step.nest('archive sysroot'):
      tempdir = self.m.path.mkdtemp()
      artifact_info = common_pb2.ArtifactsByService(
          sysroot=common_pb2.ArtifactsByService.Sysroot(
              output_artifacts=[
                  common_pb2.ArtifactsByService.Sysroot.ArtifactInfo(
                      artifact_types=[
                          common_pb2.ArtifactsByService.Sysroot.ArtifactType
                          .SYSROOT_ARCHIVE
                      ])
              ],
          ))
      request = artifacts.GetRequest(
          chroot=chroot, sysroot=sysroot, artifact_info=artifact_info,
          result_path=common_pb2.ResultPath(
              path=common_pb2.Path(
                  path=str(tempdir), location=common_pb2.Path.OUTSIDE)))
      response = self.m.cros_build_api.ArtifactsService.Get(
          request, infra_step=True)

      build_id = str(
          self.m.buildbucket.build.id or self.m.led.run_id.replace('/', '_'))
      gs_archive_folder = '%s/%s' % (
          build_target.name, self.sysroot_enabled.chromeos_start_version)
      if self.sysroot_enabled.chromeos_cl_diff_counts:
        gs_archive_folder += '~%d' % self.sysroot_enabled.chromeos_cl_diff_counts
      gs_archive_folder += '-%s' % build_id

      for artifact in response.artifacts.sysroot.artifacts:
        if not artifact.failed and artifact.artifact_type == common_pb2.ArtifactsByService.Sysroot.ArtifactType.SYSROOT_ARCHIVE:
          for archive in artifact.paths:
            gs_path = self.m.path.join(gs_archive_folder,
                                       self.m.path.basename(archive.path))
            self.m.gsutil.upload(archive.path, self.sysroot_enabled.gs_bucket,
                                 gs_path)
