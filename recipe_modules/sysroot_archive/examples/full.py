# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test codes for sysroot archive API."""

from collections import namedtuple
from PB.chromite.api import depgraph
from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties

DEPS = [
    'recipe_engine/properties',
    'build_menu',
    'cros_branch',
    'sysroot_archive',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.sysroot_archive.archive_sysroot_build(
      common_pb2.BuildTarget(name='foo'), [])

  api.sysroot_archive.archive_sysroot_build(common_pb2.BuildTarget(name='foo'))
  # return without doing anything
  api.sysroot_archive.archive_sysroot_build(None, [])

  DepGraph = namedtuple('DepGraph', 'target')
  # pylint: disable=protected-access
  api.build_menu._dep_graph = DepGraph(
      target=depgraph.DepGraph(package_deps=[
          depgraph.PackageDepInfo(
              package_info=common_pb2.PackageInfo(
                  package_name='target-chrome-os-test', category='virtual',
                  version='foo'))
      ]))
  api.sysroot_archive.archive_sysroot_build(
      common_pb2.BuildTarget(name='foo'), [])


def GenTests(api):
  yield api.test(
      'basic_cl0',
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
      'basic_cl1',
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
      'no save',
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
