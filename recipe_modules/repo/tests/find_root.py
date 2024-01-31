# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'repo',
]



def RunSteps(api):
  cwd = api.path['cleanup']

  with api.context(cwd=cwd):
    # diff_manifests_informational calls _find_root().  Use that to cover both
    # cases in one test.
    api.repo.diff_manifests_informational(
        cwd.join('manifest-internal/snapshot-a.xml'),
        cwd.join('manifest-internal/snapshot-b.xml'))

  # Next, call _find_root from a subdirectory.  Should not affect context.cwd.
  cwd = api.path['cleanup'].join('test', 'dir', 'sub')
  api.file.ensure_directory('test dir', cwd)
  expected = str(cwd)
  api.path.mock_add_paths(api.path['cleanup'].join('.repo'))
  with api.context(cwd=cwd):
    api.repo._find_root()  # pylint: disable=protected-access
    api.assertions.assertEqual(expected, str(api.context.cwd))


def GenTests(api):
  yield api.test('tests')
