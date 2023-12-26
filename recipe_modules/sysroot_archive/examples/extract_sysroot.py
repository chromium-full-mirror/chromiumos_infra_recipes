# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify sysroot_archive.extract_sysroot()."""

from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.sysroot_archive.examples.extract_sysroot import ExtractSysrootArchiveTestProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'build_menu',
    'cros_branch',
    'sysroot_archive',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = ExtractSysrootArchiveTestProperties


def RunSteps(api, properties):
  api.sysroot_archive.extract_best_archive(
      common_pb2.Chroot(), common_pb2.BuildTarget(name=properties.builder_name))


def GenTests(api):
  yield api.test(
      'use-archive',
      api.sysroot_archive.get_gsutil_list_testdata(api),
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, True, 'R120-15650.0.0', 'R120-15651.0.0', 0),
      api.properties(builder_name='board1'),
      api.post_check(
          post_process.MustRun,
          'find best sysroot archive.gsutil list',
      ),
      api.post_check(
          post_process.MustRun,
          'extract sysroot archive.call chromite.api.SysrootService/ExtractArchive.call response',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-match',
      api.sysroot_archive.get_gsutil_list_testdata(api),
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, True, 'R120-15651.0.0', 'R120-15652.0.0', 0),
      api.properties(builder_name='board1'),
      api.post_check(
          post_process.MustRun,
          'find best sysroot archive.gsutil list',
      ),
      api.post_check(
          post_process.DoesNotRun,
          'extract sysroot archive.call chromite.api.SysrootService/ExtractArchive.call response',
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-use-archive',
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, False, 'R120-15650.0.0', 'R120-15651.0.0', 0),
      api.properties(builder_name='board1'),
      api.post_check(
          post_process.DoesNotRun,
          'find best sysroot archive.gsutil list',
      ),
      api.post_check(
          post_process.DoesNotRun,
          'extract sysroot archive.call chromite.api.SysrootService/ExtractArchive.call response',
      ),
      api.post_process(post_process.DropExpectation),
  )
