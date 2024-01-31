# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test codes for sysroot archive API."""

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties

DEPS = [
    'build_menu',
    'cros_branch',
    'cros_build_api',
    'recipe_engine/properties',
    'sysroot_archive',
]



def RunSteps(api):
  api.sysroot_archive.archive_sysroot_build(common_pb2.Chroot(), Sysroot(),
                                            common_pb2.BuildTarget(name='foo'))

  api.sysroot_archive.archive_sysroot_build(common_pb2.Chroot(), Sysroot(),
                                            common_pb2.BuildTarget(name='foo'))


def GenTests(api):
  mock_output = '''
{
  "artifacts": {
    "sysroot": {
      "artifacts": [
        {
          "artifactType": 50,
          "paths": [
            {
              "location": 2,
              "path": "/path/to/archive/sysroot.tar.zst"
            }
          ]
        }
      ]
    }
  }
}'''

  yield api.test(
      'basic-cl0',
      api.cros_build_api.set_api_return('archive sysroot',
                                        'ArtifactsService/Get',
                                        data=(mock_output)),
      api.properties(
          **{
              '$chromeos/sysroot_archive':
                  SysrootArchiveApiProperties(
                      sysroot_enabled=SysrootArchiveApiProperties
                      .SysrootEnabled(
                          save_sysroot_archive=True,
                          use_sysroot_archive=True,
                          gs_bucket='foo',
                          chromeos_start_version='R120-15650.0.0',
                          chromeos_end_version='R120-15651.0.0',
                          chromeos_cl_diff_counts=0,
                      ))
          }))

  yield api.test(
      'basic-cl1',
      api.cros_build_api.set_api_return('archive sysroot',
                                        'ArtifactsService/Get',
                                        data=(mock_output)),
      api.properties(
          **{
              '$chromeos/sysroot_archive':
                  SysrootArchiveApiProperties(
                      sysroot_enabled=SysrootArchiveApiProperties
                      .SysrootEnabled(
                          save_sysroot_archive=True,
                          use_sysroot_archive=True,
                          gs_bucket='foo',
                          chromeos_start_version='R120-15650.0.0',
                          chromeos_end_version='R120-15651.0.0',
                          chromeos_cl_diff_counts=1,
                      ))
          }))

  yield api.test(
      'no-save',
      api.properties(
          **{
              '$chromeos/sysroot_archive':
                  SysrootArchiveApiProperties(
                      sysroot_enabled=SysrootArchiveApiProperties
                      .SysrootEnabled(
                          save_sysroot_archive=False,
                          use_sysroot_archive=True,
                          gs_bucket='foo',
                          chromeos_start_version='R120-15650.0.0',
                          chromeos_end_version='R120-15651.0.0',
                          chromeos_cl_diff_counts=0,
                      ))
          }))
